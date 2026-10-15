"""Observe one terminal's connection to an existing Codex daemon.

The original HTTP upgrade and WebSocket bytes pass through unchanged; only replies to this terminal's requests establish its thread.
Sidebar work runs separately so an unavailable Herdr never stalls the connection.
"""

import json
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import tempfile
import threading
import time

from . import harnesses, panes

SESSION_SOURCE = "herdr:codex"


class Observer:
    def __init__(self, env, runner=subprocess.run):
        self.env = dict(env)
        self.runner = runner
        self.pending = {}
        self.lock = threading.Lock()
        self.events = queue.Queue()
        self.thread = None
        self.usage = None
        self.bound = False
        self.closed = False
        self.worker = threading.Thread(target=self.work, daemon=True)
        self.worker.start()

    def sent(self, message, connection=None):
        if message.get("method") in ("thread/start", "thread/resume", "thread/fork", "turn/start") and "id" in message:
            params = message.get("params") or {}
            with self.lock:
                self.pending[connection, message["id"]] = {"method": message["method"], "params": {key: params[key] for key in ("threadId", "model", "effort") if key in params}}

    def received(self, message, connection=None):
        with self.lock:
            request = self.pending.pop((connection, message.get("id")), None) if "id" in message else None
        event = None
        if request and isinstance(message.get("result"), dict):
            result = message["result"]
            thread = result.get("thread") or {}
            summary = {"thread": {key: thread[key] for key in ("id", "path", "modelProvider", "ephemeral") if key in thread}, "model": result.get("model"), "reasoningEffort": result.get("reasoningEffort")}
            event = (request["method"], request.get("params") or {}, summary)
        elif message.get("method") in ("thread/tokenUsage/updated", "turn/completed"):
            params = message.get("params") or {}
            event = (message["method"], {key: params[key] for key in ("threadId", "tokenUsage") if key in params}, {})
        if event and (request or self.events.qsize() < 64):
            # Backpressure belongs to the transport, never to optional sidebar updates.
            self.events.put_nowait((*event, time.time_ns()))

    def disconnected(self, connection):
        with self.lock:
            self.pending = {key: value for key, value in self.pending.items() if key[0] is not connection}

    def work(self):
        while True:
            try:
                event = self.events.get(timeout=1)
            except queue.Empty:
                if not self.closed and self.thread and not self.bound:
                    try:
                        # Session replies can arrive before Herdr recognizes the terminal process.
                        self.update("retry", {"threadId": self.thread["id"]}, {}, time.time_ns())
                    except Exception:
                        pass
                continue
            try:
                if event is None:
                    return
                self.update(*event)
            except Exception:
                pass  # Sidebar failures must never interrupt a Codex session.
            finally:
                self.events.task_done()

    def update(self, method, params, result, sequence):
        if self.closed:
            return
        if method in ("thread/start", "thread/resume", "thread/fork"):
            thread = result.get("thread") or {}
            # Codex also starts temporary background threads on the terminal's connection.
            if thread.get("ephemeral") is True or not isinstance(thread.get("id"), str) or not thread["id"]:
                return
            self.thread = {**thread, "model": result.get("model"), "effort": result.get("reasoningEffort")}
            self.usage = None
            self.bound = False
        elif self.thread and params.get("threadId") == self.thread["id"]:
            if method == "thread/tokenUsage/updated":
                self.usage = params.get("tokenUsage")
            elif method == "turn/start":
                for key in ("model", "effort"):
                    if params.get(key):
                        self.thread[key] = params[key]
        else:
            return
        if not self.bound:
            args = [panes.herdr_bin(self.env), "pane", "report-agent-session", self.env["HERDR_PANE_ID"], "--source", SESSION_SOURCE, "--agent", "codex", "--agent-session-id", self.thread["id"], "--seq", str(sequence)]
            self.runner(args, check=True, capture_output=True, timeout=5, env=self.env)
        data = harnesses.codex({"transcript_path": self.thread.get("path"), "model": self.thread.get("model")})
        data["model"] = self.thread.get("model") or data["model"]
        data["provider_id"] = self.thread.get("modelProvider") or data["provider_id"]
        data["effort"] = self.thread.get("effort") or data["effort"]
        if self.usage:
            used = harnesses.number((self.usage.get("last") or {}).get("totalTokens"))
            limit = harnesses.number(self.usage.get("modelContextWindow"))
            data.update(context_used=used, context_limit=limit, context_percent=harnesses.codex_context_percent(used, limit))
        self.bound = False
        self.bound = bool(panes.report({**data, "session": self.thread["id"]}, self.env, self.runner))

    def close(self):
        if self.closed:
            return
        self.closed = True
        # Give the worker a bounded opportunity to finish before removing this connection's rows.
        self.events.put_nowait(None)
        self.worker.join(timeout=2)
        if not self.worker.is_alive() and self.thread:
            try:
                panes.clear("codex", self.env, self.runner, session=self.thread["id"])
            except Exception:
                pass


class WebSocketObserver:
    """Read uncompressed JSON frames without participating in the WebSocket protocol."""

    MAX_MESSAGE = 64 * 1024 * 1024

    def __init__(self, observe):
        self.observe = observe
        self.buffer = bytearray()
        self.upgraded = False
        self.disabled = False
        self.fragments = None
        self.skip = 0

    def feed(self, data):
        if self.disabled:
            return
        self.buffer.extend(data)
        if not self.upgraded:
            end = self.buffer.find(b"\r\n\r\n")
            if end == -1:
                if len(self.buffer) > 65536:
                    self.disabled = True
                    self.buffer.clear()
                return
            del self.buffer[:end + 4]
            self.upgraded = True
        while True:
            if self.skip:
                count = min(self.skip, len(self.buffer))
                del self.buffer[:count]
                self.skip -= count
                if self.skip:
                    return
            if len(self.buffer) < 2:
                return
            first, second = self.buffer[:2]
            size, offset = second & 127, 2
            if size in (126, 127):
                width = 2 if size == 126 else 8
                if len(self.buffer) < offset + width:
                    return
                size = int.from_bytes(self.buffer[offset:offset + width], "big")
                offset += width
            masked = bool(second & 128)
            if len(self.buffer) < offset + (4 if masked else 0):
                return
            mask = self.buffer[offset:offset + 4] if masked else None
            offset += 4 if masked else 0
            if size > self.MAX_MESSAGE:
                del self.buffer[:offset]
                self.skip = size
                self.fragments = None
                continue
            if len(self.buffer) < offset + size:
                return
            payload = self.buffer[offset:offset + size]
            del self.buffer[:offset + size]
            if masked:
                payload = bytearray(value ^ mask[index % 4] for index, value in enumerate(payload))
            opcode, final = first & 15, bool(first & 128)
            if opcode >= 8:
                continue  # Ping, pong and close are forwarded by the socket relay.
            if opcode in (1, 2):
                self.fragments = payload if not first & 112 else None
            elif opcode == 0 and self.fragments is not None:
                self.fragments.extend(payload)
            else:
                self.fragments = None
            if self.fragments is not None and len(self.fragments) > self.MAX_MESSAGE:
                self.fragments = None
            if final and self.fragments is not None:
                message, self.fragments = self.fragments, None
                try:
                    parsed = json.loads(message)
                    if isinstance(parsed, dict):
                        self.observe(parsed)
                except Exception:
                    pass  # Observation is optional; forwarding must keep working.


def relay(source, destination, observe):
    frames = WebSocketObserver(observe)
    try:
        while data := source.recv(65536):
            # Record outgoing request IDs before the daemon can send its reply.
            try:
                frames.feed(data)
            except Exception:
                pass
            destination.sendall(data)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def run(socket_path, command, env=os.environ):
    """Keep the TUI attached to the verified daemon; own only a temporary local socket."""
    if command[1:3] != ["--remote", f"unix://{socket_path}"] or env.get("HERDR_ENV") != "1" or not panes.PANE_ID.fullmatch(env.get("HERDR_PANE_ID", "")) or not env.get("HERDR_SOCKET_PATH"):
        raise ValueError("Codex sidebar connection requires Herdr context and the launcher's verified socket")
    observer = Observer(env)
    handlers = {}
    connections = set()
    threads = set()
    lock = threading.Lock()
    terminal = None
    accepting = None
    stopped = threading.Event()
    try:
        # macOS Unix sockets have a short path limit; the private directory protects the listener.
        with tempfile.TemporaryDirectory(prefix="hc-", dir="/tmp") as directory:
            local = str(Path(directory) / "codex.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connections.add(listener)
            listener.bind(local)
            Path(local).chmod(0o600)
            listener.listen()
            listener.settimeout(0.2)

            def forward(client):
                upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                receiving = None
                try:
                    with lock:
                        if stopped.is_set():
                            return
                        connections.add(upstream)
                    upstream.connect(socket_path)
                    receiving = threading.Thread(target=relay, args=(upstream, client, lambda message: observer.received(message, client)), daemon=True)
                    receiving.start()
                    relay(client, upstream, lambda message: observer.sent(message, client))
                    receiving.join()
                except OSError:
                    pass
                finally:
                    for connection in (client, upstream):
                        try:
                            connection.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        connection.close()
                    if receiving:
                        receiving.join(timeout=1)
                    observer.disconnected(client)
                    with lock:
                        connections.difference_update((client, upstream))
                        threads.discard(threading.current_thread())

            def accept():
                # Codex uses separate connections for the TUI and session pickers, and may reconnect.
                while not stopped.is_set():
                    try:
                        client, _ = listener.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    with lock:
                        if stopped.is_set():
                            client.close()
                            return
                        connections.add(client)
                        thread = threading.Thread(target=forward, args=(client,), daemon=True)
                        threads.add(thread)
                        thread.start()

            accepting = threading.Thread(target=accept, daemon=True)
            accepting.start()
            terminal = subprocess.Popen([*command[:2], f"unix://{local}", *command[3:]], env=dict(env))
            # The TUI receives terminal SIGINT directly in the foreground process group.
            handlers[signal.SIGINT] = signal.signal(signal.SIGINT, lambda signum, frame: None)
            for sig in (signal.SIGTERM, signal.SIGHUP):
                handlers[sig] = signal.signal(sig, lambda signum, frame: terminal.send_signal(signum) if terminal.poll() is None else None)
            return terminal.wait()
    finally:
        stopped.set()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if terminal and terminal.poll() is None:
            terminal.terminate()
            try:
                terminal.wait(timeout=2)
            except subprocess.TimeoutExpired:
                terminal.kill()
                terminal.wait()
        if accepting:
            accepting.join(timeout=1)
        with lock:
            active_connections = list(connections)
            active_threads = list(threads)
        for connection in active_connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        for thread in active_threads:
            thread.join(timeout=1)
        observer.close()
