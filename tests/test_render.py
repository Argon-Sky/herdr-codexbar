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

    def test_quota_parts_have_fixed_widths(self):
        parts = [render.quota_parts(window, NOW) for window in self.providers["claude"]["pools"][""]]
        blank = render.BLANK
        self.assertEqual(parts[0], {"label": f"{blank}5h", "bar": render.progress_bar(95), "state": "reserve", "left": f"{blank}95% left", "pace": f"■ 25% in reserve{blank * 0}", "reset": "↻  3h 31m"})
        self.assertEqual((parts[1]["state"], parts[1]["pace"]), ("pace", "◪ on pace" + blank * 7))
        for key in ("label", "left", "pace", "reset"):
            self.assertEqual(len({len(part[key]) for part in parts}), 1, key)

    def test_deficit_and_unstarted_window(self):
        codex = render.quota_parts(self.providers["codex"]["pools"][""][1], NOW)
        self.assertEqual((codex["state"], codex["pace"].rstrip(render.BLANK)), ("deficit", "□ 30% in deficit"))
        opencode = render.quota_parts(self.providers["opencodego"]["pools"][""][0], NOW)
        self.assertEqual((opencode["reset"], opencode["pace"]), ("↻      5h", render.BLANK * render.PACE_WIDTH))

    def test_pace_is_derived_when_codexbar_has_none(self):
        # OpenCode Go 30d: 56% used with 22.5 of 30 days left -> 25% expected.
        self.assertEqual(round(render.pace_delta(self.providers["opencodego"]["pools"][""][2], NOW)), 31)

    def test_unknown_window(self):
        parts = render.quota_parts(self.providers["antigravity"]["pools"]["claude-gpt"][1], NOW)
        self.assertEqual((parts["label"], parts["left"], parts["bar"], parts["pace"]), (f"{render.BLANK}7d", "unknown", None, None))

    def test_tab_bar_lists_every_provider(self):
        self.assertEqual(render.tab_bar(snapshot()), "CC 95/60 · GPT 100/0 · Agy 90/80 3p 100/- · OC 100/18/44 · CMD 4")
        self.assertEqual(render.tab_bar(None), "[quota unavailable]")


if __name__ == "__main__":
    unittest.main()
