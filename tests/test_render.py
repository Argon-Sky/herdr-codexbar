import unittest

from herdr_codexbar import render

from .helpers import NOW, snapshot

EMPTY, MIDDLE, FULL = "", "", ""


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.providers = snapshot()["providers"]

    def test_progress_bar_is_full_only_at_100(self):
        self.assertEqual(render.progress_bar(100), "" + "" * 10 + "")
        self.assertEqual(render.progress_bar(99)[-1], "")
        self.assertEqual(render.progress_bar(0), "" + "" * 10 + "")
        self.assertEqual(len(render.progress_bar(50)), render.BAR_CELLS)

    def test_quota_rows_have_fixed_columns(self):
        rows = [render.quota_row(window, NOW) for window in self.providers["claude"]["pools"][""]]
        bar = render.progress_bar(95)
        self.assertEqual(rows[0], f"5h  {bar}  95% left  ■ 25% in reserve   ↻  3h 31m")
        self.assertEqual(rows[1], f"7d  {render.progress_bar(60)}  60% left  {'◪ on pace':<17}  ↻  6d 18h")
        self.assertEqual(len({row.index("↻") for row in rows}), 1)

    def test_deficit_and_unstarted_window(self):
        codex = self.providers["codex"]["pools"][""]
        self.assertIn("□ 30% in deficit", render.quota_row(codex[1], NOW))
        opencode = self.providers["opencodego"]["pools"][""]
        self.assertTrue(render.quota_row(opencode[0], NOW).endswith("↻      5h"))

    def test_pace_is_derived_when_codexbar_has_none(self):
        # OpenCode Go 30d: 56% used with 22.5 of 30 days left -> 25% expected.
        self.assertEqual(round(render.pace_delta(self.providers["opencodego"]["pools"][""][2], NOW)), 31)

    def test_unknown_window(self):
        self.assertEqual(render.quota_row(self.providers["antigravity"]["pools"]["claude-gpt"][1], NOW), "7d  unknown")

    def test_tab_bar_lists_every_provider(self):
        self.assertEqual(render.tab_bar(snapshot()), "CC 95/60 · GPT 100/0 · Agy 90/80 3p 100/- · OC 100/18/44 · CMD 4")
        self.assertEqual(render.tab_bar(None), "[quota unavailable]")


if __name__ == "__main__":
    unittest.main()
