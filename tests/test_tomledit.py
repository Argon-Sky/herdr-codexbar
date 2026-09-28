import tomllib
import unittest

from herdr_codexbar import tomledit

ROWS = '[["agent"], ["$hc_q1"]]'
DEFAULTS = {"ui": {"sidebar_width": 65, "sidebar_max_width": 80}, "ui.sidebar.agents": {"row_gap": 1}}
CONFIG = """# my config
onboarding = false

[ui]
# keep this comment
tab_bar_right = [
  { type = "command", command = "date +%H:%M # clock", interval_seconds = 60 },
]
sidebar_width = 48

[ui.sidebar.agents]
rows = [
  ["state_icon", "agent"],  # mine
]

[ui.sidebar.agents.rows_by_agent]
pi = [["agent"]]
"""


class SetupTests(unittest.TestCase):
    def test_edits_only_our_keys(self):
        text, undo = tomledit.setup(CONFIG, ROWS, DEFAULTS)
        config = tomllib.loads(text)["ui"]
        self.assertEqual([item["command"] for item in config["tab_bar_right"]], ["date +%H:%M # clock"])
        self.assertEqual(config["sidebar"]["agents"]["rows"], [["agent"], ["$hc_q1"]])
        self.assertEqual(config["sidebar_width"], 48)
        self.assertEqual(config["sidebar"]["agents"]["rows_by_agent"], {"pi": [["agent"]]})
        self.assertIn("# keep this comment", text)
        self.assertEqual(config["sidebar"]["agents"]["row_gap"], 1)
        self.assertEqual(undo, {"rows": '[\n  ["state_icon", "agent"],  # mine\n]', "added": ["sidebar_max_width", "row_gap"]})

    def test_is_idempotent(self):
        text, _ = tomledit.setup(CONFIG, ROWS, DEFAULTS)
        self.assertEqual(tomledit.setup(text, ROWS, DEFAULTS)[0], text)

    def test_uninstall_restores_the_original(self):
        text, undo = tomledit.setup(CONFIG, ROWS, DEFAULTS)
        self.assertEqual(tomledit.uninstall(text, undo), CONFIG)

    def test_empty_config(self):
        text, undo = tomledit.setup("", ROWS, DEFAULTS)
        config = tomllib.loads(text)["ui"]
        self.assertEqual((config["sidebar_width"], config["sidebar_max_width"], config["sidebar"]["agents"]["row_gap"]), (65, 80, 1))
        self.assertEqual(undo["added"], ["sidebar_width", "sidebar_max_width", "row_gap"])
        restored = tomllib.loads(tomledit.uninstall(text, undo))
        self.assertEqual(restored, {"ui": {"sidebar": {"agents": {}}}})

    def test_refuses_dotted_and_inline_forms(self):
        for config in ('ui.sidebar.agents.rows = []\n', '[ui]\nsidebar = { agents = { rows = [] } }\n', '[ui.sidebar]\nagents.rows = []\n'):
            with self.assertRaises(tomledit.Unsupported, msg=config):
                tomledit.setup(config, ROWS, DEFAULTS)



class TableTests(unittest.TestCase):
    def test_set_keeps_other_keys_and_remove_restores(self):
        config = '[ui]\ntheme = "dark"\n\n[ui.status_line]\ntype = "builtin"\npadding = 2\n\n[[plugins]]\nname = "x"\n'
        text = tomledit.set_table(config, "ui.status_line", {"type": '"command"', "command": '"hc hook grok"'})
        self.assertEqual(tomllib.loads(text)["ui"]["status_line"], {"type": "command", "command": "hc hook grok", "padding": 2})
        self.assertEqual(tomllib.loads(text)["plugins"], [{"name": "x"}])
        self.assertEqual(tomledit.remove_table(text, "ui.status_line"), '[ui]\ntheme = "dark"\n\n[[plugins]]\nname = "x"\n')

    def test_set_appends_a_missing_table(self):
        text = tomledit.set_table('[ui]\ntheme = "dark"\n', "ui.status_line", {"type": '"command"'})
        self.assertEqual(text, '[ui]\ntheme = "dark"\n\n[ui.status_line]\ntype = "command"\n')
        self.assertEqual(tomledit.remove_table(text, "ui.status_line"), '[ui]\ntheme = "dark"\n')
        with self.assertRaises(tomledit.Unsupported):
            tomledit.set_table('ui.status_line = { type = "builtin" }\n', "ui.status_line", {"type": '"command"'})

if __name__ == "__main__":
    unittest.main()
