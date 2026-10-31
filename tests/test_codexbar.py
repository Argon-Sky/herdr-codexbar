import json
import unittest
from unittest import mock

from herdr_codexbar import codexbar

from .helpers import NOW, fixture, snapshot


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.providers = snapshot()["providers"]

    def test_plan_names_follow_codexbar(self):
        plans = {name: data["plan"] for name, data in self.providers.items()}
        self.assertEqual(plans, {
            "claude": "Claude Pro",
            "codex": "ChatGPT Plus",
            "antigravity": "Google AI Pro",
            "opencodego": "OpenCode Go",
            "commandcode": "Command Code GOAT",
            "copilot": "Copilot Individual",
            "grok": "X Premium+",
            "qwencloud": "Qwen Cloud Essential",
        })

    def test_windows_are_labelled_and_sorted(self):
        pool = self.providers["opencodego"]["pools"][""]
        self.assertEqual([window["label"] for window in pool], ["5h", "7d", "30d"])
        self.assertIsNone(pool[0]["resetsAt"])

    def test_copilot_month_has_a_default_length(self):
        (month,) = self.providers["copilot"]["pools"][""]
        self.assertEqual((month["label"], month["pace"]), ("30d", -9.0))
        (week,) = self.providers["grok"]["pools"][""]
        self.assertEqual(week["label"], "7d")

    def test_qwen_cloud_month_without_pace(self):
        (month,) = self.providers["qwencloud"]["pools"][""]
        self.assertEqual((month["label"], month["used"], month["pace"]), ("30d", 0.4, None))

    def test_pace_uses_codexbar_sign_and_on_pace(self):
        claude = self.providers["claude"]["pools"][""]
        self.assertEqual([window["pace"] for window in claude], [-25.0, 0.0])

    def test_runs_out_at_is_codexbars_eta_after_updated_at(self):
        codex = self.providers["codex"]["pools"][""]
        self.assertEqual([window["runsOutAt"] for window in codex], [None, "2026-01-10T14:30:00+00:00"])
        # Lasts until reset, no willLastToReset, no pace at all, and Antigravity's pools, which carry no pace.
        self.assertEqual([window["runsOutAt"] for window in self.providers["claude"]["pools"][""]], [None, None])
        self.assertIsNone(self.providers["copilot"]["pools"][""][0]["runsOutAt"])
        self.assertIsNone(self.providers["qwencloud"]["pools"][""][0]["runsOutAt"])
        for pool in self.providers["antigravity"]["pools"].values():
            self.assertEqual([window["runsOutAt"] for window in pool], [None, None])

    def test_runs_out_at_needs_a_finite_eta_of_zero_or_more(self):
        def runs_out(**pace):
            return codexbar.runs_out_at({"willLastToReset": False, **pace}, NOW)
        self.assertEqual(runs_out(etaSeconds=0), "2026-01-10T12:00:00+00:00")
        self.assertEqual(runs_out(etaSeconds=90.5), "2026-01-10T12:01:30.500000+00:00")
        for eta in (None, -1, True, False, float("nan"), float("inf"), "9000", 1e30):
            self.assertIsNone(runs_out(etaSeconds=eta), eta)
        self.assertIsNone(runs_out())
        self.assertIsNone(codexbar.runs_out_at({"willLastToReset": True, "etaSeconds": 60}, NOW))
        self.assertIsNone(codexbar.runs_out_at({"willLastToReset": 0, "etaSeconds": 60}, NOW))
        self.assertIsNone(codexbar.runs_out_at({"willLastToReset": False, "etaSeconds": 60}, None))
        self.assertIsNone(codexbar.runs_out_at(None, NOW))

    def test_antigravity_splits_pools_and_ignores_per_model_windows(self):
        pools = self.providers["antigravity"]["pools"]
        self.assertEqual(sorted(pools), ["claude-gpt", "gemini"])
        self.assertEqual([window["used"] for window in pools["gemini"]], [10.0, 20.0])
        self.assertFalse(pools["claude-gpt"][1]["known"])

    def test_unsupported_providers_are_skipped(self):
        self.assertNotIn("broken", self.providers)
        self.assertNotIn("unsupported-example", self.providers)

    def test_a_provider_codexbar_cannot_read_is_kept_as_failed(self):
        raw = [
            {"provider": "opencodego", "source": "auto", "error": {"code": 1, "kind": "provider", "message": "OpenCode Go API error: HTTP 500: HTTPError"}},
            {"provider": "broken", "error": {"code": 1, "kind": "provider", "message": "boom"}},
        ]
        snapshot = codexbar.normalize(raw, {"opencodego": "OpenCode Go"}, NOW)
        self.assertEqual(snapshot["providers"], {"opencodego": {"name": "OpenCode Go", "plan": "OpenCode Go", "pools": {}, "failed": True}})
        self.assertNotIn("HTTP 500", json.dumps(snapshot))
        self.assertNotIn("failed", self.providers["claude"])

    def test_a_failed_record_never_replaces_a_read_one(self):
        raw = fixture("codexbar-usage.json") + [{"provider": "claude", "error": {"kind": "provider"}}]
        self.assertNotIn("failed", codexbar.normalize(raw, now=NOW)["providers"]["claude"])

    def test_poll_writes_failed_providers_beside_read_ones_and_refuses_only_failures(self):
        class Result:
            stdout = json.dumps([{"provider": "opencodego", "error": {"kind": "provider"}}])
        with self.assertRaises(ValueError):
            codexbar.poll(lambda *args, **kwargs: Result())
        Result.stdout = json.dumps(fixture("codexbar-usage.json")[:1] + [{"provider": "opencodego", "error": {"kind": "provider"}}])
        providers = codexbar.poll(lambda *args, **kwargs: Result())["providers"]
        self.assertEqual((sorted(providers), providers["opencodego"]["failed"]), (["claude", "opencodego"], True))

    def test_poll_dates_the_snapshot_when_codexbar_answered(self):
        calls = []

        class Clock:
            @staticmethod
            def now(tz=None):
                calls.append("now")
                return NOW

        def runner(args, **kwargs):
            calls.append(args[1])

            class Result:
                stdout = json.dumps(fixture("codexbar-usage.json")[:2] if args[1] == "usage" else [])
            return Result()

        with mock.patch.object(codexbar, "datetime", Clock):
            snapshot = codexbar.poll(runner)
        self.assertEqual(calls, ["usage", "now", "config"])
        self.assertEqual(snapshot["providers"]["codex"]["pools"][""][1]["runsOutAt"], "2026-01-10T14:30:00+00:00")

    def test_no_account_details_are_kept(self):
        text = json.dumps(snapshot())
        self.assertNotIn("example.com", text)
        self.assertNotIn("Example Org", text)

    def test_snapshot_round_trip_and_staleness(self):
        data = snapshot()
        codexbar.write_json(codexbar.SNAPSHOT, data)
        self.assertEqual(codexbar.SNAPSHOT.stat().st_mode & 0o777, 0o600)
        self.assertEqual(codexbar.read_snapshot(NOW), data)
        later = NOW.replace(hour=13)
        self.assertIsNone(codexbar.read_snapshot(later))

    def test_poll_refuses_empty_output(self):
        class Result:
            stdout = "[]"
        with self.assertRaises(ValueError):
            codexbar.poll(lambda *args, **kwargs: Result())


if __name__ == "__main__":
    unittest.main()
