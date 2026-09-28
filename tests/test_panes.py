import json
import subprocess
import unittest

from herdr_codexbar import codexbar, panes, render

from .helpers import NOW, Runner, snapshot

ENV = {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/tmp/herdr.sock", "HERDR_PANE_ID": "w1:p2", "HERDR_BIN_PATH": "/bin/herdr"}


def report(**values):
    return {"harness": "claude", "provider_id": "anthropic", "model": "Opus 5.5", "effort": "high", "context_used": 120_000, "context_limit": 1_000_000, "context_percent": 12, **values}


class RouteTests(unittest.TestCase):
    def test_provider_ids(self):
        self.assertEqual(panes.route(report()), ("claude", None))
        self.assertEqual(panes.route(report(harness="opencode", provider_id="opencode-go")), ("opencodego", None))
        self.assertEqual(panes.route(report(harness="opencode", provider_id="commandcode")), ("commandcode", None))
        self.assertEqual(panes.route(report(harness="codex", provider_id="openai")), ("codex", None))
        self.assertEqual(panes.route(report(harness="opencode", provider_id="github-copilot")), ("copilot", None))
        self.assertEqual(panes.route(report(harness="pi", provider_id="openai-codex")), ("codex", None))
        self.assertEqual(panes.route(report(harness="kilo", provider_id="xai")), ("grok", None))
        self.assertEqual(panes.route(report(harness="opencode", provider_id="opencode")), (None, None))

    def test_antigravity_pool_follows_the_model(self):
        self.assertEqual(panes.route(report(harness="antigravity", provider_id="antigravity", model="Gemini 3 Pro")), ("antigravity", "gemini"))
        self.assertEqual(panes.route(report(harness="antigravity", provider_id="antigravity", model="Claude Sonnet 5")), ("antigravity", "claude-gpt"))


class TokenTests(unittest.TestCase):
    def test_meta_tokens(self):
        values = panes.meta_tokens(report())
        self.assertEqual({key: value for key, value in values.items() if value}, {"hc_model": "Opus 5.5", "hc_effort": "high", "hc_context_1": "context 12%", "hc_tokens": "120k / 1M"})
        self.assertEqual(set(values), set(panes.META_TOKENS))

    def test_context_bands(self):
        self.assertEqual([panes.context_band(percent) for percent in (0, 24, 25, 50, 51, 75, 76, 100)], [1, 1, 2, 2, 3, 3, 4, 4])
        self.assertEqual(panes.meta_tokens(report(context_percent=None, context_limit=None, effort=None))["hc_tokens"], "120k")

    def test_quota_tokens(self):
        values = panes.quota_tokens("antigravity", "gemini", snapshot(), NOW)
        self.assertEqual((values["hc_plan"], values["hc_pool"]), ("Google AI Pro", "Gemini"))
        self.assertEqual(values["hc_q1_label"], f"{render.BLANK}5h")
        self.assertEqual([key for key in values if key.startswith("hc_q1_bar") and values[key]], ["hc_q1_bar_reserve"])
        self.assertIsNone(values["hc_q3_label"])
        self.assertEqual(set(values), set(panes.QUOTA_TOKENS))

    def test_stale_snapshot_and_unknown_provider(self):
        self.assertEqual(panes.quota_tokens("claude", None, None)["hc_q1_label"], "quota unavailable")
        self.assertEqual(panes.quota_tokens(None, None, snapshot()), dict.fromkeys(panes.QUOTA_TOKENS))
        self.assertEqual(panes.quota_tokens("unsupported-example", None, snapshot()), dict.fromkeys(panes.QUOTA_TOKENS))


class DisplayNameTests(unittest.TestCase):
    def test_command_code_shows_the_bare_agent_id(self):
        runner = Runner()
        entry = {"pane": "w1:p2", "socket": "/tmp/herdr.sock", "herdr": "/bin/herdr", "harness": "commandcode", "provider": "commandcode", "pool": None}
        panes.publish(entry, dict.fromkeys(panes.QUOTA_TOKENS), runner)
        self.assertEqual(runner.calls[0][6:10], ["--agent", "cmd", "--display-agent", "cmd"])
        self.assertTrue(all("--display-agent" not in call for call in runner.calls[1:]))
        panes.publish({**entry, "harness": "claude"}, {"hc_plan": None}, runner)
        self.assertNotIn("--display-agent", runner.calls[-1])
        panes.publish(entry, {"hc_plan": None}, runner, remove=True)
        self.assertEqual(runner.calls[-1][6:], ["--clear-display-agent", "--clear-token", "hc_plan"])


class ErrorTests(unittest.TestCase):
    def test_reports_herdrs_message_not_the_command(self):
        error = subprocess.CalledProcessError(1, ["herdr", "--token", "hc_plan=Claude Pro"], output='{"error":{"code":"metadata_token_limit","message":"pane metadata may contain at most 32 tokens"}}')
        self.assertEqual(panes.herdr_error(error), "pane metadata may contain at most 32 tokens")
        self.assertEqual(panes.herdr_error(subprocess.CalledProcessError(2, ["herdr"], output=b"")), "herdr exited with status 2")


class ReportTests(unittest.TestCase):
    def setUp(self):
        for path in panes.PANES_DIR.glob("*.json"):
            path.unlink()
        codexbar.write_json(codexbar.SNAPSHOT, snapshot())

    def test_publishes_and_registers(self):
        runner = Runner()
        panes.report(report(), ENV, runner, NOW)
        self.assertEqual(runner.calls[0][:6], ["/bin/herdr", "pane", "report-metadata", "w1:p2", "--source", "user:herdr-codexbar"])
        tokens = runner.tokens()
        self.assertEqual(tokens["hc_plan"], "Claude Pro")
        self.assertEqual(tokens["hc_model"], "Opus 5.5")
        self.assertIsNone(tokens["hc_q3_label"])
        self.assertTrue(all(call.count("--token") + call.count("--clear-token") <= panes.MAX_UPDATES for call in runner.calls))
        entry = json.loads(panes.registration_path("w1:p2").read_text())
        self.assertEqual((entry["provider"], entry["pool"]), ("claude", None))

    def test_ignores_panes_outside_herdr(self):
        runner = Runner()
        panes.report(report(), {**ENV, "HERDR_ENV": ""}, runner, NOW)
        panes.report(report(), {**ENV, "HERDR_PANE_ID": "../../etc"}, runner, NOW)
        self.assertEqual(runner.calls, [])

    def test_refresh_updates_prunes_and_clears(self):
        for pane in ("w1:p1", "w1:p2", "w1:p3"):
            panes.report(report(), {**ENV, "HERDR_PANE_ID": pane}, Runner(), NOW)
        runner = Runner({"w1:p1": "claude", "w1:p2": "codex"})  # p2 now runs Codex; p3 closed.
        self.assertEqual(panes.refresh_panes(snapshot(), runner, NOW), 0)
        published = {call[3]: call for call in runner.calls if call[1:3] == ["pane", "report-metadata"]}
        self.assertEqual(sorted(published), ["w1:p1", "w1:p2"])
        self.assertIn("--token", published["w1:p1"])
        self.assertNotIn("--token", published["w1:p2"])
        self.assertEqual([path.name for path in panes.PANES_DIR.glob("*.json")], ["w1_p1.json"])


if __name__ == "__main__":
    unittest.main()
