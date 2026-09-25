import json
import unittest

from herdr_codexbar import codexbar

from .helpers import NOW, snapshot


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
        })

    def test_windows_are_labelled_and_sorted(self):
        pool = self.providers["opencodego"]["pools"][""]
        self.assertEqual([window["label"] for window in pool], ["5h", "7d", "30d"])
        self.assertIsNone(pool[0]["resetsAt"])

    def test_pace_uses_codexbar_sign_and_on_pace(self):
        claude = self.providers["claude"]["pools"][""]
        self.assertEqual([window["pace"] for window in claude], [-25.0, 0.0])

    def test_antigravity_splits_pools_and_ignores_per_model_windows(self):
        pools = self.providers["antigravity"]["pools"]
        self.assertEqual(sorted(pools), ["claude-gpt", "gemini"])
        self.assertEqual([window["used"] for window in pools["gemini"]], [10.0, 20.0])
        self.assertFalse(pools["claude-gpt"][1]["known"])

    def test_unsupported_providers_and_errors_are_skipped(self):
        self.assertNotIn("broken", self.providers)
        self.assertNotIn("unsupported-example", self.providers)

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
