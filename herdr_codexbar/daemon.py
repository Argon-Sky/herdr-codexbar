"""Route Codex hooks that run in Codex's shared app server to the panes that show their threads.

The shared server runs every thread's hooks with the environment of the terminal that started it, so `HERDR_PANE_ID` names that terminal, not the one showing the thread, and Herdr binds the thread to it. Codex's default terminal title, "[activity | ]<thread name> | <project>", says which pane shows a thread: a pane matches when its title shows the thread's name and its directory is the thread's. Before Codex names a thread, it goes to the only Codex pane in its directory whose title shows no name. Anything else is no match: the thread waits, a background check looks again while Codex names a new thread, and the poller tries again after that.
"""

import json
import os
import re
import sqlite3
import subprocess
import time
import unicodedata
from contextlib import closing
from datetime import datetime
from pathlib import Path

from . import STATE_DIR, codexbar, harnesses, panes
from .paths import codex_home

PENDING_DIR = STATE_DIR / "codex-threads"
PENDING_TTL = 3600  # Phone threads never shown in a pane would otherwise wait forever.
WAIT = 30  # Codex names a thread a few seconds after its first turn.
WAIT_STEP = 2
WAIT_LIMIT = 300  # Hooks of a thread that never matches, such as one resumed from another folder, would otherwise keep a waiter going.
THREAD_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TUI = "codex-tui"
STATE_DB = "state_5.sqlite"  # Codex's thread database.
NAMING = 10  # Codex shows a new name in the title a moment after it writes it to the session index.


def server_pid(home=None):
    try:
        pid = json.loads((codex_home(home) / "app-server-daemon/daemon.pid").read_text())["pid"]
        os.kill(pid, 0)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return pid


def runs_in_server(home=None, runner=subprocess.run, pid=None):
    """Whether this process descends from Codex's shared app server. Raises if the process table cannot be read, so a hook publishes nothing rather than trust the wrong pane."""
    server = server_pid(home)
    if server is None:
        return False
    result = runner(["ps", "-A", "-o", "pid=,ppid="], check=True, capture_output=True, text=True, timeout=5)
    parents = dict(tuple(map(int, line.split())) for line in result.stdout.splitlines() if line.strip())
    pid = pid or os.getpid()
    for _ in range(len(parents) + 1):
        pid = parents.get(pid)
        if pid in (None, 0, 1):
            return False
        if pid == server:
            return True
    return False


def thread_names(home=None):
    """Thread ID -> name from Codex's session index; the newest entry wins."""
    names = {}
    try:
        with (codex_home(home) / "session_index.jsonl").open(encoding="utf-8") as index:
            for line in index:
                try:
                    entry = json.loads(line)
                    names[entry["id"]] = entry.get("thread_name") or ""
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return names


def just_named(home=None):
    """IDs of threads Codex named in the last NAMING seconds, whose titles may not show the name yet."""
    fresh = set()
    try:
        with (codex_home(home) / "session_index.jsonl").open(encoding="utf-8") as index:
            for line in index:
                try:
                    entry = json.loads(line)
                    if time.time() - datetime.fromisoformat(entry["updated_at"]).timestamp() < NAMING:
                        fresh.add(entry["id"])
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return fresh


def archived_threads(home=None):
    """IDs of archived threads. Codex unarchives a thread before it resumes one, so their names cannot be in a title unless they are still open."""
    try:
        return {found.group() for path in (codex_home(home) / "archived_sessions").iterdir() if (found := THREAD_ID.search(path.name))}
    except OSError:
        return set()


def title_name(title):
    """The thread name in Codex's default terminal title, without the activity and the project; empty before the thread has one."""
    segments = (title or "").split(" | ")
    first = segments[0]
    if len(segments) > 1 and (first.endswith("] Action Required") or len(first) <= 3 and not any(unicodedata.category(char).startswith("L") for char in first)):
        segments = segments[1:]
    return " | ".join(segments[:-1])


def title_project(title):
    """The project at the end of Codex's default terminal title; empty when the title has none."""
    segments = (title or "").split(" | ")
    return segments[-1] if len(segments) > 1 else ""


def project(cwd):
    """The project Codex's title shows for a folder: the name of its git repository's root, or of the worktree's, and outside git the folder's own name. None for a folder that no longer exists."""
    folder = Path(cwd or "")
    if not cwd or not folder.is_dir():
        return None
    for directory in (folder, *folder.parents):
        if (directory / ".git").exists():
            return directory.name or None
    return folder.name or None


def thread_folders(threads, home=None):
    """Thread ID -> folder from Codex's thread database, read-only and only those two columns; empty when it cannot be read."""
    if not threads:
        return {}
    try:
        with closing(sqlite3.connect(f"{(codex_home(home) / STATE_DB).absolute().as_uri()}?mode=ro", uri=True, timeout=1)) as database:
            return dict(database.execute(f"SELECT id, cwd FROM threads WHERE id IN ({', '.join('?' * len(threads))})", sorted(threads)).fetchall())
    except sqlite3.Error:
        return {}


def shows(shown, name):
    """Whether a title's name is this thread's; Codex cuts long names to 45 characters and "..."."""
    return bool(name) and (shown == name or shown.endswith("...") and name.startswith(shown[:-3]))


def same_directory(pane, cwd):
    directory = pane.get("foreground_cwd") or pane.get("cwd")
    return bool(directory and cwd) and os.path.normpath(directory) == os.path.normpath(cwd)


def match(thread, data, names, candidates, archived=(), home=None):
    """The panes that show a root thread: by its name in the title and its directory, or, before Codex names it, the only unnamed Codex pane in its directory.

    Another unarchived thread with a name the title could show is a collision, and nothing matches, unless the project at the end of the title tells them apart: it must be this thread's project and not the other's. When either project is unknown, the collision stands.
    """
    if data.get("thread_source") not in (None, "user") or not data.get("cwd"):
        return []
    in_directory = [pane for pane in candidates if same_directory(pane, data["cwd"])]
    name = names.get(thread)
    if name:
        found = []
        for pane in in_directory:
            title = pane.get("terminal_title_stripped")
            shown = title_name(title)
            if not shows(shown, name):
                continue
            others = {other_id for other_id, other in names.items() if other_id != thread and other_id not in archived and shows(shown, other)}
            if others:
                mine, segment = project(data["cwd"]), title_project(title)
                if mine is None:
                    return []
                if mine != segment:
                    continue  # The pane shows a thread of the same name from another project.
                folders = thread_folders(others, home)
                if any(project(folders.get(other)) in (None, segment) for other in others):
                    return []
            found.append(pane)
        return found
    if data.get("originator") != TUI:
        return []  # Threads started elsewhere, such as from the ChatGPT app, have no pane of their own.
    unnamed = [pane for pane in in_directory if not title_name(pane.get("terminal_title_stripped"))]
    return unnamed if len(unnamed) == 1 else []


def publish(thread, data, targets, now=None, runner=subprocess.run):
    provider, pool = panes.route(data)
    snapshot = codexbar.read_snapshot(now)
    for pane in targets:
        entry = {"pane": pane["pane_id"], "socket": pane["socket"], "herdr": pane["herdr"], "harness": "codex", "provider": provider, "pool": pool, "session": thread, "shared": True}
        panes.register(entry)
        panes.publish(entry, {**panes.meta_tokens(data), **panes.quota_tokens(provider, pool, snapshot, now)}, runner)
    drop_elsewhere(thread, {pane["pane_id"] for pane in targets}, runner)


def pending_path(thread):
    return PENDING_DIR / f"{thread}.json"


def report(thread, transcript, data, runner=subprocess.run, now=None, home=None):
    """Publish a shared-server hook's report to the panes that show its thread, or keep it for the poller."""
    if not THREAD_ID.fullmatch(thread or ""):
        return
    if data.get("thread_source") not in (None, "user"):
        return  # Subagents and reviews belong to their parent's pane.
    candidates = panes.agent_panes("codex", runner)
    names = thread_names(home)
    targets = match(thread, data, names, candidates, archived_threads(home), home)
    drop_moved([pane for pane in candidates if pane not in targets], names, just_named(home), runner)
    if targets:
        publish(thread, data, targets, now, runner)
        pending_path(thread).unlink(missing_ok=True)
    elif transcript:
        codexbar.write_json(pending_path(thread), {"transcript": transcript, "at": time.time()})
        if data.get("originator") == TUI:
            wait_in_background(thread, runner, now, home)
    panes.discover(candidates, "codex", harnesses.codex_provider(home), codexbar.read_snapshot(now), runner, now)


def place(thread, waiting, names, candidates, archived, runner=subprocess.run, now=None, home=None):
    """Publish a waiting thread to the panes that show it now, from its transcript as it is now."""
    data = harnesses.codex({"transcript_path": waiting["transcript"]})
    targets = match(thread, data, names, candidates, archived, home)
    if targets:
        publish(thread, data, targets, now, runner)
        pending_path(thread).unlink(missing_ok=True)
    return bool(targets)


def wait(thread, runner=subprocess.run, now=None, home=None, sleep=time.sleep, clock=time.time):
    """Look again for a waiting thread's pane while Codex names it, until no hook has left it waiting for WAIT seconds."""
    start = clock()
    while clock() - start < WAIT_LIMIT:
        sleep(WAIT_STEP)
        try:
            waiting = json.loads(pending_path(thread).read_text())
        except (OSError, ValueError):
            return  # A later hook or the poller placed it.
        if clock() - waiting["at"] > WAIT:
            return  # The poller takes over.
        if place(thread, waiting, thread_names(home), panes.agent_panes("codex", runner), archived_threads(home), runner, now, home):
            return


def wait_in_background(thread, runner=subprocess.run, now=None, home=None, fork=os.fork):
    """Run `wait` in a detached process, at most one per thread, so the hook returns at once."""
    marker = PENDING_DIR / f"{thread}.wait"
    try:
        if time.time() - marker.stat().st_mtime > 2 * WAIT_LIMIT:
            marker.unlink()  # Left by a waiter that was killed.
    except OSError:
        pass
    try:
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return
    if fork():
        return
    try:
        os.setsid()
        quiet = os.open(os.devnull, os.O_RDWR)
        for stream in (0, 1, 2):
            os.dup2(quiet, stream)  # Let go of the hook's pipes, so Codex does not wait for this process.
        wait(thread, runner, now, home)
    finally:
        marker.unlink(missing_ok=True)
        os._exit(0)


def retry(runner=subprocess.run, now=None, home=None):
    """Match threads whose hooks found no pane yet, now that Codex may have named them."""
    names = None
    for path in PENDING_DIR.glob("*.json"):
        try:
            waiting = json.loads(path.read_text())
            if time.time() - waiting["at"] > PENDING_TTL or not os.path.isfile(waiting["transcript"]):
                path.unlink(missing_ok=True)
                continue
            if names is None:
                names, candidates, archived = thread_names(home), panes.agent_panes("codex", runner, panes.recorded_herdr()), archived_threads(home)
            place(path.stem, waiting, names, candidates, archived, runner, now, home)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            continue


def drop_moved(candidates, names, fresh=(), runner=subprocess.run):
    """Drop the details from panes that now show another thread than the one registered there."""
    for pane in candidates:
        try:
            entry = json.loads(panes.registration_path(pane["pane_id"]).read_text())
        except (OSError, ValueError):
            continue
        if entry.get("shared") and not still_shown(entry, pane, names, fresh):
            panes.keep_quota(entry, runner)


def drop_elsewhere(thread, kept, runner=subprocess.run):
    """Drop a thread's details from the other panes registered to it, such as the one it was resumed away from."""
    for path in panes.PANES_DIR.glob("*.json"):
        try:
            entry = json.loads(path.read_text())
            if entry.get("shared") and entry.get("session") == thread and entry["pane"] not in kept:
                panes.keep_quota(entry, runner)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            continue


def still_shown(entry, pane, names, fresh=()):
    """Whether a pane still shows the thread registered for it: its title shows the thread's name, or no name while the thread has none or Codex has only just named it. Another name, or no name after `/new`, means Codex switched threads there."""
    shown = title_name(pane.get("terminal_title_stripped"))
    name = names.get(entry["session"])
    if not shown:
        return not name or entry["session"] in fresh
    return shows(shown, name)
