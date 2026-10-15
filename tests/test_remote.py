import json
from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import unittest
from unittest import mock

from herdr_codexbar import codexbar, panes, remote

from .helpers import Runner, snapshot
from .test_panes import ENV


class ObserverTests(unittest.TestCase):
    def setUp(self):
        codexbar.write_json(codexbar.SNAPSHOT, snapshot())
        for path in panes.PANES_DIR.glob("*.json"):
            path.unlink()
        self.runner = Runner()
        self.observer = remote.Observer(ENV, self.runner)
        self.addCleanup(self.observer.close)

    def reply(self, method="thread/start", thread="thread-one", identifier=1):
        self.observer.sent({"id": identifier, "method": method, "params": {}})
        self.observer.received({"id": identifier, "result": {"thread": {"id": thread, "modelProvider": "openai"}, "model": "test-model", "reasoningEffort": "high"}})
        self.observer.events.join()

    def test_binds_only_responses_to_its_own_requests(self):
        self.observer.received({"method": "thread/started", "params": {"thread": {"id": "other-terminal"}}})
        self.observer.received({"id": 99, "result": {"thread": {"id": "unrelated"}}})
        self.assertEqual(self.runner.calls, [])
        self.reply()
        entry = json.loads(panes.registration_path(ENV["HERDR_PANE_ID"]).read_text())
        self.assertEqual(entry["session"], "thread-one")
        self.assertEqual(self.runner.tokens()["hc_model"], "test-model")
        self.assertEqual(self.runner.tokens()["hc_effort"], "high")

    def test_usage_updates_only_the_bound_thread(self):
        self.reply()
        usage = {"last": {"totalTokens": 56_000}, "modelContextWindow": 400_000}
        for thread in ("another-thread", "thread-one"):
            self.observer.received({"method": "thread/tokenUsage/updated", "params": {"threadId": thread, "tokenUsage": usage}})
            self.observer.events.join()
            self.assertEqual(self.runner.tokens().get("hc_tokens"), "56k / 400k" if thread == "thread-one" else None)
        self.assertEqual(self.runner.tokens()["hc_context_1"], "context 11%")

    def test_resume_rebinds_and_failed_requests_keep_previous_session(self):
        self.reply()
        self.observer.sent({"id": 2, "method": "thread/resume"})
        self.observer.received({"id": 2, "error": {"message": "not found"}})
        self.assertEqual(self.observer.thread["id"], "thread-one")
        self.reply(method="thread/resume", thread="thread-two", identifier=3)
        self.assertEqual(self.runner.sessions[ENV["HERDR_PANE_ID"]], "thread-two")

    def test_old_connection_cannot_clear_replacement_session(self):
        self.reply()
        entry = json.loads(panes.registration_path(ENV["HERDR_PANE_ID"]).read_text())
        panes.register({**entry, "session": "replacement"})
        self.observer.close()
        self.assertTrue(panes.registration_path(ENV["HERDR_PANE_ID"]).exists())

    def test_reporting_failure_does_not_stop_observation(self):
        with mock.patch.object(panes, "report", side_effect=OSError("server unreachable")):
            self.reply()
        self.reply(thread="thread-two", identifier=2)
        self.assertEqual(json.loads(panes.registration_path(ENV["HERDR_PANE_ID"]).read_text())["session"], "thread-two")

    def test_ignored_session_binding_is_retried_on_the_next_usage_update(self):
        original = self.runner

        def ignore_binding(args, **kwargs):
            if args[1:3] == ["pane", "report-agent-session"]:
                return mock.Mock(returncode=0)
            return original(args, **kwargs)

        self.observer.runner = ignore_binding
        self.reply()
        self.assertFalse(self.observer.bound)
        self.assertFalse(panes.registration_path(ENV["HERDR_PANE_ID"]).exists())
        self.observer.runner = original
        self.observer.received({"method": "thread/tokenUsage/updated", "params": {"threadId": "thread-one", "tokenUsage": {"last": {"totalTokens": 20_000}}}})
        self.observer.events.join()
        self.assertTrue(self.observer.bound)
        self.assertEqual(self.runner.sessions[ENV["HERDR_PANE_ID"]], "thread-one")

    def test_initial_report_retries_after_herdr_detects_the_process(self):
        detected = threading.Event()
        published = threading.Event()
        original = self.runner

        def delayed_detection(args, **kwargs):
            result = original(args, **kwargs)
            if args[1:3] == ["pane", "get"] and not detected.is_set():
                pane = json.loads(result.stdout)
                pane["result"]["pane"].pop("agent", None)
                result.stdout = json.dumps(pane)
            if args[1:3] == ["pane", "report-metadata"] and "hc_model=test-model" in args:
                published.set()
            return result

        self.observer.runner = delayed_detection
        self.reply()
        self.assertFalse(self.observer.bound)
        detected.set()
        self.assertTrue(published.wait(3), "an idle resumed session must publish without another Codex event")
        self.assertEqual(self.runner.tokens()["hc_model"], "test-model")

    def test_request_ids_are_scoped_to_each_connection(self):
        for connection in ("terminal", "picker"):
            self.observer.sent({"id": 1, "method": "thread/resume"}, connection)
        self.observer.disconnected("picker")
        self.observer.received({"id": 1, "result": {"thread": {"id": "wrong-session"}}}, "picker")
        self.observer.events.join()
        self.assertIsNone(self.observer.thread)
        self.observer.received({"id": 1, "result": {"thread": {"id": "terminal-session"}}}, "terminal")
        self.observer.events.join()
        self.assertEqual(self.observer.thread["id"], "terminal-session")

    def test_temporary_background_threads_do_not_replace_the_terminal_session(self):
        self.reply()
        self.observer.sent({"id": 2, "method": "thread/start", "params": {"ephemeral": True}})
        self.observer.received({"id": 2, "result": {"thread": {"id": "background-task", "ephemeral": True}, "model": "background-model"}})
        self.observer.events.join()
        self.assertEqual(self.observer.thread["id"], "thread-one")
        self.assertEqual(self.runner.sessions[ENV["HERDR_PANE_ID"]], "thread-one")
        self.assertEqual(self.runner.tokens()["hc_model"], "test-model")


class RelayTests(unittest.TestCase):
    def test_terminal_can_open_concurrent_connections_and_reconnect(self):
        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                while data := self.request.recv(65536):
                    self.request.sendall(data)

        with tempfile.TemporaryDirectory(prefix="hc-test-", dir="/tmp") as directory:
            upstream = str(Path(directory) / "server.sock")
            with socketserver.ThreadingUnixStreamServer(upstream, Echo) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                self.addCleanup(worker.join, 2)
                command = ["codex", "--remote", f"unix://{upstream}"]
                with mock.patch.object(remote.subprocess, "Popen") as popen, mock.patch.object(remote, "Observer"):
                    terminal = popen.return_value
                    terminal.poll.return_value = 0

                    def exercise_connections():
                        local = popen.call_args.args[0][2].removeprefix("unix://")
                        clients = []
                        try:
                            for index in range(3):
                                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                                clients.append(client)
                                client.settimeout(2)
                                client.connect(local)
                                data = b"GET / HTTP/1.1\r\n\r\n" + frame({"id": index})
                                client.sendall(data)
                                received = bytearray()
                                while len(received) < len(data):
                                    chunk = client.recv(65536)
                                    self.assertTrue(chunk, "the observer disconnected the terminal")
                                    received.extend(chunk)
                                self.assertEqual(received, data)
                                if index == 1:
                                    for connection in clients:
                                        connection.close()
                            return 0
                        finally:
                            for client in clients:
                                client.close()

                    terminal.wait.side_effect = exercise_connections
                    try:
                        self.assertEqual(remote.run(upstream, command, ENV), 0)
                    finally:
                        server.shutdown()

    def test_forwards_bytes_unchanged_even_when_observer_fails(self):
        data = b'GET / HTTP/1.1\r\nUpgrade: websocket\r\n\r\n' + frame({"id": 1, "method": "thread/start", "padding": "x" * 128_000}, masked=True)
        caller, source = socket.socketpair()
        destination, backend = socket.socketpair()
        for connection in (caller, source, destination, backend):
            connection.settimeout(3)
            self.addCleanup(connection.close)
        observer = mock.Mock(side_effect=RuntimeError("optional observer failed"))
        worker = threading.Thread(target=remote.relay, args=(source, destination, observer), daemon=True)
        worker.start()
        # Read concurrently: the message deliberately exceeds a pipe/socket's initial buffer.
        received = bytearray()

        def read():
            while chunk := backend.recv(65536):
                received.extend(chunk)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        caller.sendall(data)
        caller.shutdown(socket.SHUT_WR)
        worker.join(timeout=3)
        reader.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(received, data)
        observer.assert_called_once()

    def test_requires_the_verified_socket_and_herdr_context(self):
        for command, env in ((["codex", "--remote", "unix:///different"], ENV), (["codex", "--remote", "unix:///verified"], {})):
            with self.assertRaises(ValueError):
                remote.run("/verified", command, env)


def frame(payload, masked=False, opcode=1, final=True, compressed=False):
    data = json.dumps(payload).encode() if isinstance(payload, dict) else payload
    size = len(data)
    header = bytes([(128 if final else 0) | (64 if compressed else 0) | opcode])
    flag = 128 if masked else 0
    header += bytes([flag | size]) if size < 126 else bytes([flag | (126 if size < 65536 else 127)]) + size.to_bytes(2 if size < 65536 else 8, "big")
    if masked:
        mask = b"abcd"
        header += mask
        data = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
    return header + data


class WebSocketObserverTests(unittest.TestCase):
    def observe(self):
        messages = []
        observer = remote.WebSocketObserver(messages.append)
        observer.feed(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n")
        observer.feed(b"\r\n")
        return observer, messages

    def test_split_masked_frames_of_all_length_encodings(self):
        observer, messages = self.observe()
        expected = [{"id": index, "padding": "x" * length} for index, length in enumerate((1, 200, 128_000))]
        data = b"".join(frame(message, masked=True) for message in expected)
        for offset in range(0, len(data), 117):
            observer.feed(data[offset:offset + 117])
        self.assertEqual(messages, expected)

    def test_fragmented_json_and_interleaved_ping(self):
        observer, messages = self.observe()
        data = b'{"id":1,"method":"thread/start"}'
        observer.feed(frame(data[:10], masked=True, final=False))
        observer.feed(frame(b"ping", opcode=9))
        observer.feed(frame(data[10:], masked=True, opcode=0))
        self.assertEqual(messages, [{"id": 1, "method": "thread/start"}])

    def test_non_json_and_compressed_frames_do_not_stop_later_observation(self):
        observer, messages = self.observe()
        observer.feed(frame(b"not JSON") + frame(b"compressed", compressed=True) + frame({"id": 2}))
        self.assertEqual(messages, [{"id": 2}])

    def test_oversized_message_is_skipped_without_losing_next_frame(self):
        observer, messages = self.observe()
        observer.MAX_MESSAGE = 100
        data = frame(b"x" * 200) + frame({"id": 3})
        for offset in range(0, len(data), 17):
            observer.feed(data[offset:offset + 17])
        self.assertEqual(messages, [{"id": 3}])
