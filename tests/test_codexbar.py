import json
import os
import time
import unittest
from datetime import datetime, timezone
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

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
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
        # A Codex reset credit's id, title and description stay out with the account fields.
        for value in ("codex-reset-credit-v1-", "0123456789abcdef", "Example reset gift", "A free reset", "reset_type", "granted_at"):
            self.assertNotIn(value, text)

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


class CreditTests(unittest.TestCase):
    """Credits still usable, from CodexBar's three sources. Limit reset expiries are read on the Mac's clock, pinned here to Warsaw so CI agrees."""

    def setUp(self):
        self.zone = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Warsaw"
        time.tzset()

    def tearDown(self):
        if self.zone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.zone
        time.tzset()

    def read(self, usage, now=NOW):
        return codexbar.credits(usage, now)

    def resets(self, value, secondary=None, now=NOW):
        row = {"label": "Limit Reset Credits", "value": value}
        if secondary is not None:
            row["secondaryValue"] = secondary
        return self.read({"details": [{"rows": [row]}]}, now)

    def cloud(self, now=NOW, **row):
        return self.read({"details": [{"title": "Cloud credits", "rows": [{"id": "claude-cloud-credits", "label": "Cloud credits", **row}]}]}, now)

    def test_each_source_in_the_fixture(self):
        providers = snapshot()["providers"]
        self.assertEqual(providers["codex"]["credits"], [
            {"kind": "reset", "count": 1, "expiresAt": "2026-01-16T22:07:17+00:00"},
            {"kind": "reset", "count": 2, "expiresAt": "2026-01-20T10:00:00+00:00"},
            {"kind": "reset", "count": 1, "expiresAt": None},
        ])
        self.assertEqual(providers["claude"]["credits"], [
            {"kind": "cloud", "amount": 248.526216, "currency": "USD", "expiresAt": "2026-01-15T07:59:00+00:00"},
            {"kind": "reset", "count": 1, "expiresAt": None},
        ])
        # "tomorrow, 1:00 AM" from 13:00 in Warsaw: the start of 11 January there.
        self.assertEqual(providers["grok"]["credits"], [{"kind": "reset", "count": 2, "expiresAt": "2026-01-10T23:00:00+00:00"}])

    def test_nothing_else_is_a_credit(self):
        providers = snapshot()["providers"]
        # Copilot's seat row counts credits used; Codex's paid credits and every providerCost are spend, not credits that lapse.
        for name in ("copilot", "antigravity", "opencodego", "commandcode", "qwencloud"):
            self.assertNotIn("credits", providers[name], name)
        self.assertNotIn("12.5", json.dumps(providers["codex"]))
        other = [{"id": "claude-model-breakdown", "label": "Opus", "value": "40%", "usageValue": 40}, {"label": "Admin spend", "value": "$3.00", "usageValue": 3},
                 {"id": "copilot-seat-credits", "label": "Credits used", "value": "4", "usageValue": 4}]
        self.assertEqual(self.read({"details": [{"rows": other}], "providerCost": {"used": 1, "limit": 5}}), [])

    def test_an_empty_or_absent_source_leaves_no_credits(self):
        self.assertEqual(self.read({}), [])
        self.assertEqual(self.read({"codexResetCredits": None}), [])
        self.assertEqual(self.read({"codexResetCredits": {"credits": [], "availableCount": 0}}), [])
        self.assertEqual(self.read({"codexResetCredits": {"credits": [{"status": "redeemed"}, {"status": "expired"}, {"status": "redeeming"}, {"status": "new-status"}]}}), [])
        raw = [{"provider": "codex", "usage": {"primary": {"windowMinutes": 300, "usedPercent": 1}, "codexResetCredits": {"credits": []}}}]
        self.assertNotIn("credits", codexbar.normalize(raw, now=NOW)["providers"]["codex"])

    def test_codex_counts_available_unexpired_credits_whatever_availablecount_says(self):
        credits = [{"status": "available", "expires_at": "2026-01-10T12:00:00Z"}, {"status": "available", "expires_at": "2026-01-10T12:00:01Z"},
                   {"status": "available", "expires_at": None}, {"status": "Available", "expires_at": "2026-01-11T00:00:00Z"}]
        self.assertEqual(self.read({"codexResetCredits": {"credits": credits, "availableCount": 0}}), [
            {"kind": "reset", "count": 1, "expiresAt": "2026-01-10T12:00:01+00:00"},
            {"kind": "reset", "count": 1, "expiresAt": None},
        ])

    def test_codex_credits_that_cannot_be_read(self):
        unreadable = [{"kind": "reset", "expiresAt": None, "unreadable": True}]
        for block in ("3 credits", [], {"credits": "none"}, {"availableCount": 2}, {"credits": [{"status": "available"}, "x"]}, {"credits": [{"status": 1}]}, {"credits": [{"expires_at": "2026-01-16T00:00:00Z"}]}):
            self.assertEqual(self.read({"codexResetCredits": block}), unreadable, block)
        credits = [{"status": "available", "expires_at": "next week"}, {"status": "available", "expires_at": 1767225600}, {"status": "available", "expires_at": "2026-01-16"},
                   {"status": "redeemed", "expires_at": "soon"}, {"status": "available", "expires_at": "2026-01-16T00:00:00Z"}]
        self.assertEqual(self.read({"codexResetCredits": {"credits": credits}}), [
            {"kind": "reset", "count": 3, "expiresAt": None, "unreadable": True},
            {"kind": "reset", "count": 1, "expiresAt": "2026-01-16T00:00:00+00:00"},
        ])

    def test_cloud_credits_as_codexbar_reads_its_row_back(self):
        self.assertEqual(self.cloud(value="$12.00 of $25.00 remaining", secondaryValue="Expires 2026-01-12T07:59:00Z", usageValue=12),
                         [{"kind": "cloud", "amount": 12.0, "currency": "USD", "expiresAt": "2026-01-12T07:59:00+00:00"}])
        self.assertEqual(self.cloud(value="$12.00 of $25.00 remaining", usageValue=12), [{"kind": "cloud", "amount": 12.0, "currency": "USD", "expiresAt": None}])
        # Expired, a stored expiry the clock has passed, locked, and spent: none is usable.
        self.assertEqual(self.cloud(value="Expired", secondaryValue="Expired 2026-01-09T07:59:00Z"), [])
        self.assertEqual(self.cloud(value="Expired", usageValue=5), [])
        self.assertEqual(self.cloud(value="$12.00 of $25.00 remaining", secondaryValue="Expires 2026-01-10T12:00:00Z", usageValue=12), [])
        self.assertEqual(self.cloud(value="Unavailable", secondaryValue="Expires 2026-01-12T07:59:00Z"), [])
        self.assertEqual(self.cloud(value="Unavailable", usageValue=None), [])
        self.assertEqual(self.cloud(value="$0.00 of $25.00 remaining", secondaryValue="Expires 2026-01-12T07:59:00Z", usageValue=0), [])

    def test_cloud_credits_that_cannot_be_read(self):
        unreadable = [{"kind": "cloud", "expiresAt": None, "unreadable": True}]
        for row in ({"value": "$12.00 left"}, {"value": "$12.00", "usageValue": "12"}, {"value": "x", "usageValue": -1}, {"value": "x", "usageValue": True}, {"value": "x", "usageValue": float("nan")},
                    {"value": "x", "usageValue": float("inf")}, {"usageValue": None}):
            self.assertEqual(self.cloud(**row), unreadable, row)
        self.assertEqual(self.cloud(value="$12.00", secondaryValue="Expires next week", usageValue=12),
                         [{"kind": "cloud", "amount": 12.0, "currency": "USD", "expiresAt": None, "unreadable": True}])
        self.assertEqual(self.cloud(value="$12.00", secondaryValue=7, usageValue=12),
                         [{"kind": "cloud", "amount": 12.0, "currency": "USD", "expiresAt": None, "unreadable": True}])

    def test_limit_reset_expiries_from_codexbars_formatter(self):
        def expiry(secondary, now=NOW):
            (entry,) = self.resets("1 available", secondary, now)
            return entry["expiresAt"]
        # The CLI's en_US_POSIX forms (UsageFormatter.resetDescription): today at its time, tomorrow and later from the start of that day in Warsaw.
        self.assertEqual(expiry("Expires 6:40\u202fPM"), "2026-01-10T17:40:00+00:00")
        self.assertEqual(expiry("Expires tomorrow, 1:00\u202fAM"), "2026-01-10T23:00:00+00:00")
        self.assertEqual(expiry("Expires Jan 16 at 4:40\u202fPM"), "2026-01-15T23:00:00+00:00")
        # The owner's words too: today, either order, full month names, any case, 24-hour times.
        self.assertEqual(expiry("Expires today, 11:30 pm"), "2026-01-10T22:30:00+00:00")
        self.assertEqual(expiry("Expires 16 january"), "2026-01-15T23:00:00+00:00")
        self.assertEqual(expiry("Expires SEPT 3, 16:40"), "2026-09-02T22:00:00+00:00")
        # Past daylight saving time and into next year.
        self.assertEqual(expiry("Expires Mar 30 at 9:00\u202fAM"), "2026-03-29T22:00:00+00:00")
        self.assertEqual(expiry("Expires Jan 2 at 9:00\u202fAM", datetime(2026, 12, 30, 12, 0, tzinfo=timezone.utc)), "2027-01-01T23:00:00+00:00")
        self.assertEqual(expiry("Expires Jan 9 at 9:00\u202fAM"), "2027-01-08T23:00:00+00:00", "a month and day already past this year is next year's")

    def test_limit_reset_rows(self):
        self.assertEqual(self.resets("3 available"), [{"kind": "reset", "count": 3, "expiresAt": None}])
        self.assertEqual(self.resets("0 available"), [])
        # A time today the clock has passed, as when CodexBar formatted it a moment before: no longer usable.
        self.assertEqual(self.resets("1 available", "Expires 11:59\u202fAM"), [])
        for value in ("available", "1 left", "one available", 2, None):
            self.assertEqual(self.resets(value, "Expires tomorrow, 1:00\u202fAM"), [{"kind": "reset", "expiresAt": None, "unreadable": True}], value)
        # A date in another language or form keeps its count, marked unreadable.
        for secondary in ("Expires morgen, 13:00", "Expires 11 lis", "Expires Nov 31", "Expires Smarch 3", "Expires 13:00\u202fPM", "Expires 9:75", "Expires today", "Expires", "", "Renews 6 Nov"):
            self.assertEqual(self.resets("2 available", secondary), [{"kind": "reset", "count": 2, "expiresAt": None, "unreadable": True}], secondary)

    def test_order_skipped_shapes_and_failed_providers(self):
        usage = {"codexResetCredits": {"credits": [{"status": "available"}, {"status": "available", "expires_at": "2026-01-20T00:00:00Z"}]},
                 "details": ["row", {"rows": "x"}, {"title": "no rows"}, {"rows": [7, {"label": "Limit Reset Credits", "value": "1 available", "secondaryValue": "Expires tomorrow, 1:00\u202fAM"},
                                                                                     {"id": "claude-cloud-credits", "value": "?"}]}]}
        self.assertEqual([(entry["kind"], entry["expiresAt"], entry.get("unreadable", False)) for entry in self.read(usage)], [
            ("cloud", None, True), ("reset", "2026-01-10T23:00:00+00:00", False), ("reset", "2026-01-20T00:00:00+00:00", False), ("reset", None, False)])
        self.assertEqual(self.read({"details": {"rows": []}}), [])
        raw = [{"provider": "claude", "error": {"kind": "provider"}, "usage": None, "details": [{"rows": [{"label": "Limit Reset Credits", "value": "1 available"}]}]}]
        self.assertNotIn("credits", codexbar.normalize(raw, now=NOW)["providers"]["claude"])


if __name__ == "__main__":
    unittest.main()
