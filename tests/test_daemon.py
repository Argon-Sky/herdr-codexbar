import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from herdr_codexbar import cli, codexbar, daemon, panes

from .helpers import NOW, Runner, snapshot

THREAD = "01a1697d-d44e-7a23-968e-b5c3a321ac4e"
OTHER = "01a16982-0000-7000-8000-000000000001"
APP = "/Users/me/app"
WAIT_IN_BACKGROUND = daemon.wait_in_background


def data(**values):
    return {"harness": "codex", "provider_id": "openai", "model": "gpt-5.5", "effort": "high", "context_used": 56_000, "context_limit": 400_000, "originator": "codex-tui", "thread_source": "user", "cwd": APP, **values}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        patch = mock.patch.dict(os.environ, CODEX_HOME=str(self.home))
        patch.start()
        self.addCleanup(patch.stop)
        for directory in (panes.PANES_DIR, daemon.PENDING_DIR):
            for path in directory.glob("*.json"):
                path.unlink()
        for path in daemon.PENDING_DIR.glob("*.wait"):
            path.unlink()
        codexbar.write_json(codexbar.SNAPSHOT, snapshot())
        self.runner = Runner()
        waiting = mock.patch.object(daemon, "wait_in_background")  # Never fork in tests.
        self.waiting = waiting.start()
        self.addCleanup(waiting.stop)

    def names(self, **names):
        """Thread ID -> name, written to Codex's session index."""
        (self.home / "session_index.jsonl").write_text("".join(json.dumps({"id": thread, "thread_name": name, "updated_at": "2026-01-10T12:00:00Z"}) + "\n" for thread, name in names.items()))

    def pane(self, pane_id, title="app", cwd=APP, agent="codex", **values):
        self.runner.agents[pane_id] = agent
        self.runner.details[pane_id] = {"terminal_title_stripped": title, "foreground_cwd": cwd, **values}

    def published(self):
        return sorted({call[3] for call in self.runner.calls if call[1:3] == ["pane", "report-metadata"]})

    def transcript(self, **meta):
        path = self.home / f"rollout-{len(list(self.home.glob('rollout-*')))}.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {"model_provider": "openai", "originator": "codex-tui", "thread_source": "user", "cwd": APP, **meta}}) + "\n")
        return str(path)


class TitleTests(unittest.TestCase):
    def test_thread_name_from_codex_title(self):
        self.assertEqual(daemon.title_name("Fix the login bug | app"), "Fix the login bug")
        self.assertEqual(daemon.title_name("⠙ | Fix the login bug | app"), "Fix the login bug")
        self.assertEqual(daemon.title_name("[!] Action Required | Fix the login bug | app"), "Fix the login bug")
        self.assertEqual(daemon.title_name("Compare A | B | app"), "Compare A | B")
        self.assertEqual(daemon.title_name("app"), "")
        self.assertEqual(daemon.title_name(None), "")

    def test_truncated_names(self):
        self.assertTrue(daemon.shows("Fix", "Fix"))
        self.assertTrue(daemon.shows("Plan the very long trip...", "Plan the very long trip to the coast"))
        self.assertFalse(daemon.shows("Plan the very long trip...", "Plan another trip"))
        self.assertFalse(daemon.shows("", ""))


class ServerTests(Fixture):
    def test_detects_hooks_run_by_the_shared_server(self):
        self.assertFalse(daemon.runs_in_server())  # No server.
        pid_file = self.home / "app-server-daemon/daemon.pid"
        pid_file.parent.mkdir()
        pid_file.write_text(json.dumps({"pid": os.getpid()}))

        def ps(table):
            class Result:
                stdout = "".join(f"{pid} {parent}\n" for pid, parent in table.items())
            return lambda *args, **kwargs: Result()
        self.assertTrue(daemon.runs_in_server(runner=ps({30: 20, 20: os.getpid(), os.getpid(): 1}), pid=30))
        self.assertFalse(daemon.runs_in_server(runner=ps({30: 20, 20: 1, os.getpid(): 1}), pid=30))
        with self.assertRaises(OSError):
            daemon.runs_in_server(runner=mock.Mock(side_effect=OSError), pid=30)


class RouteTests(Fixture):
    def test_reports_to_the_pane_showing_the_thread_not_the_one_that_started_the_server(self):
        self.names(**{THREAD: "Fix the login bug", OTHER: "Write docs"})
        self.pane("w1:p1", "Write docs | app", agent_session={"kind": "id", "value": THREAD})  # Started the server; Herdr bound the thread here.
        self.pane("w1:p2", "Fix the login bug | app")
        daemon.report(THREAD, "/unused", data(), self.runner, NOW)
        self.assertEqual(self.published(), ["w1:p2"])
        entry = json.loads(panes.registration_path("w1:p2").read_text())
        self.assertEqual((entry["session"], entry["shared"], entry["socket"]), (THREAD, True, "/tmp/herdr.sock"))
        self.assertNotIn("Fix the login bug", panes.registration_path("w1:p2").read_text())
        self.assertEqual(self.runner.tokens()["hc_model"], "gpt-5.5")

    def test_every_pane_showing_the_thread(self):
        self.names(**{THREAD: "Fix the login bug"})
        self.pane("w1:p1", "Fix the login bug | app")
        self.pane("w1:p2", "Fix the login bug | app")
        self.pane("w1:p3", "Fix the login bug | other", cwd="/Users/me/other")
        daemon.report(THREAD, "/unused", data(), self.runner, NOW)
        self.assertEqual(self.published(), ["w1:p1", "w1:p2"])

    def test_name_collision_matches_nothing(self):
        self.names(**{THREAD: "Fix the login bug", OTHER: "Fix the login bug"})
        self.pane("w1:p1", "Fix the login bug | app")
        daemon.report(THREAD, self.transcript(), data(), self.runner, NOW)
        self.assertEqual(self.published(), [])
        self.assertTrue(daemon.pending_path(THREAD).exists())

    def test_archived_threads_cannot_collide(self):
        self.names(**{THREAD: "Fix the login bug", OTHER: "Fix the login bug"})
        (self.home / "archived_sessions").mkdir()
        (self.home / f"archived_sessions/rollout-2026-01-02T10-00-00-{OTHER}.jsonl.zst").touch()
        self.pane("w1:p1", "Fix the login bug | app")
        daemon.report(THREAD, self.transcript(), data(), self.runner, NOW)
        self.assertEqual(self.published(), ["w1:p1"])

    def test_archived_thread_still_running_keeps_its_name(self):
        self.names(**{THREAD: "Fix the login bug"})
        (self.home / "archived_sessions").mkdir()
        (self.home / f"archived_sessions/rollout-2026-01-02T10-00-00-{THREAD}.jsonl").touch()  # Archived from the resume picker while open.
        self.pane("w1:p1", "app")  # Another thread, not named yet.
        daemon.report(THREAD, self.transcript(), data(), self.runner, NOW)
        self.assertEqual(self.published(), [])

    def repo(self, *parts, worktree=False):
        """A folder at the root of a git repository, or of one of its worktrees."""
        folder = self.home.joinpath("code", *parts)
        folder.mkdir(parents=True)
        if worktree:
            (folder / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
        else:
            (folder / ".git").mkdir()
        return str(folder)

    def state(self, **folders):
        """Codex's thread database, with the columns herdr-codexbar must not read next to the ones it does."""
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("create table threads (id text primary key, cwd text not null, title text, creator_account_id text)")
            db.executemany("insert into threads values (?, ?, 'Fix the login bug', 'acct-secret')", folders.items())
        db.close()

    def collide(self, mine, other, title_project="app", state=True):
        """THREAD in `mine`, OTHER of the same name in `other`; one pane in THREAD's folder shows the name."""
        self.names(**{THREAD: "Fix the login bug", OTHER: "Fix the login bug"})
        if state:
            self.state(**{THREAD: mine, OTHER: other})
        self.pane("w1:p1", f"Fix the login bug | {title_project}", cwd=mine)
        daemon.report(THREAD, self.transcript(cwd=mine), data(cwd=mine), self.runner, NOW)
        return self.published()

    def test_same_name_in_other_projects_does_not_collide(self):
        self.assertEqual(self.collide(self.repo("app"), self.repo("other")), ["w1:p1"])

    def test_same_name_in_a_subfolder_of_another_project_does_not_collide(self):
        other = self.repo("other")
        Path(other, "src").mkdir()
        self.assertEqual(self.collide(self.repo("app"), str(Path(other, "src"))), ["w1:p1"])

    def test_same_name_in_worktrees_with_the_same_root_name_collides(self):
        self.assertEqual(self.collide(self.repo("a", "app", worktree=True), self.repo("b", "app", worktree=True)), [])

    def test_same_name_in_a_subfolder_of_the_same_project_collides(self):
        mine = self.repo("app")
        Path(mine, "docs").mkdir()
        self.assertEqual(self.collide(mine, str(Path(mine, "docs"))), [])

    def test_unknown_projects_keep_the_strict_rule(self):
        mine, other = self.repo("app"), self.repo("other")
        self.assertEqual(self.collide(mine, other, state=False), [])  # No thread database.
        self.setUp()
        self.state(**{THREAD: mine})
        self.assertEqual(self.collide(mine, other, state=False), [])  # No row for the other thread.
        self.setUp()
        self.assertEqual(self.collide(mine, str(self.home / "gone")), [])  # The other folder no longer exists.
        self.setUp()
        self.assertEqual(self.collide(str(self.home / "gone"), other, title_project="gone"), [])  # Nor does this one.

    def plain(self, *parts):
        """A folder outside any git repository."""
        folder = self.home.joinpath("files", *parts)
        folder.mkdir(parents=True)
        return str(folder)

    def test_folders_outside_git_are_their_own_project(self):
        self.assertEqual(self.collide(self.plain("notes"), self.repo("other"), title_project="notes"), ["w1:p1"])
        self.setUp()
        self.assertEqual(self.collide(self.repo("app"), self.plain("misc")), ["w1:p1"])

    def test_same_name_folders_outside_git_collide(self):
        self.assertEqual(self.collide(self.plain("a", "notes"), self.plain("b", "notes"), title_project="notes"), [])
        self.setUp()
        self.assertEqual(self.collide(self.plain("notes"), self.repo("notes"), title_project="notes"), [])

    def test_subfolders_outside_git_are_their_own_project(self):
        parent = self.plain("trips")
        self.assertEqual(self.collide(self.plain("trips", "spain"), parent, title_project="spain"), ["w1:p1"])
        self.setUp()
        self.assertEqual(self.collide(self.plain("2025", "spain"), self.plain("2026", "spain"), title_project="spain"), [])

    def test_title_from_another_project_is_not_this_thread(self):
        mine, other = self.repo("app"), self.repo("other")
        self.names(**{THREAD: "Fix the login bug", OTHER: "Fix the login bug"})
        self.state(**{THREAD: mine, OTHER: other})
        self.pane("w1:p1", "Fix the login bug | app", cwd=mine)
        self.pane("w1:p2", "Fix the login bug | other", cwd=mine)  # OTHER, resumed here from its own folder.
        daemon.report(THREAD, self.transcript(cwd=mine), data(cwd=mine), self.runner, NOW)
        self.assertEqual(self.published(), ["w1:p1"])

    def test_thread_folders_reads_only_ids_and_folders(self):
        self.state(**{THREAD: "/Users/me/app"})
        with mock.patch.object(sqlite3, "connect", wraps=sqlite3.connect) as connect:
            self.assertEqual(daemon.thread_folders({THREAD, OTHER}), {THREAD: "/Users/me/app"})
        self.assertIn("mode=ro", connect.call_args.args[0])
        self.assertEqual(daemon.thread_folders(set()), {})

    def test_unnamed_thread_takes_the_only_unnamed_pane_in_its_directory(self):
        self.pane("w1:p1", "app")
        self.pane("w1:p2", "Write docs | app")
        self.pane("w1:p3", "other", cwd="/Users/me/other")
        daemon.report(THREAD, "/unused", data(), self.runner, NOW)
        self.assertEqual(self.published(), ["w1:p1"])

    def test_two_unnamed_panes_in_one_directory_wait(self):
        self.pane("w1:p1", "app")
        self.pane("w1:p2", "app")
        daemon.report(THREAD, self.transcript(), data(), self.runner, NOW)
        self.assertEqual(self.published(), [])

    def test_threads_started_outside_a_terminal_never_take_a_pane_by_directory(self):
        self.pane("w1:p1", "app")
        daemon.report(THREAD, self.transcript(), data(originator="codex_chatgpt_ios_remote"), self.runner, NOW)
        self.assertEqual(self.published(), [])

    def test_phone_thread_resumed_in_a_pane_matches_by_title(self):
        self.names(**{THREAD: "Fix the login bug"})
        self.pane("w1:p1", "Fix the login bug | app")
        daemon.report(THREAD, "/unused", data(originator="codex_chatgpt_ios_remote"), self.runner, NOW)
        self.assertEqual(self.published(), ["w1:p1"])

    def test_subagents_are_skipped(self):
        self.pane("w1:p1", "app")
        daemon.report(THREAD, self.transcript(), data(thread_source="subagent"), self.runner, NOW)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(daemon.pending_path(THREAD).exists())

    def test_rejects_malformed_thread_ids(self):
        daemon.report("../../etc", self.transcript(), data(), self.runner, NOW)
        self.assertEqual(self.runner.calls, [])


class HookTests(Fixture):
    def hook(self, **patches):
        payload = io.StringIO(json.dumps({"session_id": THREAD, "transcript_path": self.transcript()}))
        with mock.patch("sys.stdin", payload), mock.patch.object(panes, "report") as standalone, mock.patch.object(daemon, "report") as shared:
            with mock.patch.object(daemon, "runs_in_server", **patches):
                self.assertEqual(cli.hook("codex"), 0)
        return standalone, shared

    def test_shared_server_hooks_ignore_the_inherited_pane(self):
        standalone, shared = self.hook(return_value=True)
        standalone.assert_not_called()
        self.assertEqual(shared.call_args.args[0], THREAD)
        self.assertEqual(shared.call_args.args[2]["cwd"], APP)

    def test_terminal_hooks_report_for_their_own_pane(self):
        standalone, shared = self.hook(return_value=False)
        standalone.assert_called_once()
        shared.assert_not_called()

    def test_unknown_process_table_publishes_nothing(self):
        standalone, shared = self.hook(side_effect=OSError)
        standalone.assert_not_called()
        shared.assert_not_called()


class RetryTests(Fixture):
    def test_waiting_thread_matches_once_named(self):
        self.pane("w1:p1", "app")
        self.pane("w1:p2", "app")
        transcript = self.transcript()
        daemon.report(THREAD, transcript, data(), self.runner, NOW)
        self.assertEqual(self.published(), [])
        self.names(**{THREAD: "Fix the login bug"})
        self.runner.details["w1:p2"]["terminal_title_stripped"] = "Fix the login bug | app"
        daemon.retry(self.runner, NOW)
        self.assertEqual(self.published(), ["w1:p2"])
        self.assertFalse(daemon.pending_path(THREAD).exists())

    def test_waiting_threads_expire(self):
        codexbar.write_json(daemon.pending_path(THREAD), {"transcript": self.transcript(), "at": time.time() - daemon.PENDING_TTL - 1})
        codexbar.write_json(daemon.pending_path(OTHER), {"transcript": "/missing.jsonl", "at": time.time()})
        daemon.retry(self.runner, NOW)
        self.assertEqual(list(daemon.PENDING_DIR.glob("*.json")), [])


class WaitTests(Fixture):
    TURN = json.dumps({"type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "high"}}) + "\n"

    def setUp(self):
        super().setUp()
        self.now = time.time()
        self.steps = {}  # Seconds into the wait -> what happens then.
        self.pane("w1:p1", "app")
        self.pane("w1:p2", "app")

    def sleep(self, seconds):
        before = self.now - self.begun
        self.now += seconds
        for at, step in self.steps.items():
            if before < at <= self.now - self.begun:
                step()

    def wait(self):
        self.begun = self.now
        daemon.wait(THREAD, self.runner, NOW, sleep=self.sleep, clock=lambda: self.now)

    def codex_names_the_thread(self):
        self.names(**{THREAD: "Fix the login bug"})
        self.runner.details["w1:p1"]["terminal_title_stripped"] = "Fix the login bug | app"

    def looks(self):
        return sum(call[1:3] == ["pane", "list"] for call in self.runner.calls)

    def test_thread_named_after_its_hook_reaches_its_pane_without_the_poller(self):
        transcript = self.transcript()  # At SessionStart: no turn yet, so no model.
        daemon.report(THREAD, transcript, data(model=None), self.runner, NOW)
        self.assertEqual(self.published(), [])
        self.waiting.assert_called_once()
        with open(transcript, "a") as source:
            source.write(self.TURN)  # The first turn, then Codex names the thread.
        self.steps[4] = self.codex_names_the_thread
        self.wait()
        self.assertEqual(self.published(), ["w1:p1"])  # With the transcript's model, not the hook's.
        self.assertFalse(daemon.pending_path(THREAD).exists())

    def test_a_later_hook_keeps_it_waiting(self):
        transcript = self.transcript()
        with open(transcript, "a") as source:
            source.write(self.TURN)
        codexbar.write_json(daemon.pending_path(THREAD), {"transcript": transcript, "at": self.now})
        self.steps[24] = lambda: codexbar.write_json(daemon.pending_path(THREAD), {"transcript": transcript, "at": self.now})
        self.steps[34] = self.codex_names_the_thread
        self.wait()
        self.assertEqual(self.published(), ["w1:p1"])

    def test_waiting_ends_without_hooks(self):
        codexbar.write_json(daemon.pending_path(THREAD), {"transcript": self.transcript(), "at": self.now})
        self.wait()
        self.assertEqual(self.published(), [])
        self.assertTrue(daemon.pending_path(THREAD).exists())  # The poller takes over.
        self.assertLessEqual(self.looks(), daemon.WAIT // daemon.WAIT_STEP + 1)

    def test_waiting_has_a_limit_while_hooks_keep_coming(self):
        transcript = self.transcript()
        codexbar.write_json(daemon.pending_path(THREAD), {"transcript": transcript, "at": self.now})
        for at in range(0, 2 * daemon.WAIT_LIMIT, daemon.WAIT_STEP):
            self.steps[at] = lambda: codexbar.write_json(daemon.pending_path(THREAD), {"transcript": transcript, "at": self.now})
        self.wait()
        self.assertLessEqual(self.looks(), daemon.WAIT_LIMIT // daemon.WAIT_STEP + 1)

    def test_stops_once_the_thread_is_placed_elsewhere(self):
        codexbar.write_json(daemon.pending_path(THREAD), {"transcript": self.transcript(), "at": self.now})

        def placed():
            daemon.pending_path(THREAD).unlink()
            self.codex_names_the_thread()
        self.steps[1] = placed
        self.wait()
        self.assertEqual(self.published(), [])

    def test_one_waiter_per_thread(self):
        fork = mock.Mock(return_value=1)
        daemon.PENDING_DIR.mkdir(parents=True, exist_ok=True)
        WAIT_IN_BACKGROUND(THREAD, fork=fork)
        WAIT_IN_BACKGROUND(THREAD, fork=fork)
        self.assertEqual(fork.call_count, 1)
        WAIT_IN_BACKGROUND(OTHER, fork=fork)
        self.assertEqual(fork.call_count, 2)

    def test_matched_and_phone_threads_start_no_waiter(self):
        self.names(**{THREAD: "Fix the login bug"})
        self.runner.details["w1:p1"]["terminal_title_stripped"] = "Fix the login bug | app"
        daemon.report(THREAD, self.transcript(), data(), self.runner, NOW)
        daemon.report(OTHER, self.transcript(), data(originator="codex_chatgpt_ios_remote"), self.runner, NOW)
        self.waiting.assert_not_called()


class RefreshTests(Fixture):
    def refresh(self):
        names = daemon.thread_names()
        return panes.refresh_panes(snapshot(), self.runner, NOW, still_shown=lambda entry, pane: daemon.still_shown(entry, pane, names))

    def test_keeps_rows_while_the_pane_shows_the_thread_and_ignores_herdrs_binding(self):
        self.names(**{THREAD: "Fix the login bug"})
        self.pane("w1:p1", "Fix the login bug | app")
        daemon.report(THREAD, "/unused", data(), self.runner, NOW)
        self.assertEqual(self.refresh(), 0)
        self.assertTrue(panes.registration_path("w1:p1").exists())

    def test_clears_rows_after_the_pane_switches_threads(self):
        self.names(**{THREAD: "Fix the login bug", OTHER: "Write docs"})
        self.pane("w1:p1", "Fix the login bug | app")
        daemon.report(THREAD, "/unused", data(), self.runner, NOW)
        self.runner.details["w1:p1"]["terminal_title_stripped"] = "Write docs | app"
        self.runner.calls.clear()
        self.assertEqual(self.refresh(), 0)
        self.assertFalse(panes.registration_path("w1:p1").exists())
        self.assertIsNone(self.runner.tokens()["hc_model"])

if __name__ == "__main__":
    unittest.main()
