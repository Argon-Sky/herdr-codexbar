import tomllib
import unittest

from herdr_codexbar import tomledit

ROWS = '[["agent"], ["$hc_q1"]]'
COMMAND = "/opt/homebrew/bin/herdr-codexbar bar"
DEFAULTS = {"sidebar_width": 62, "sidebar_max_width": 80}
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
        text, undo = tomledit.setup(CONFIG, COMMAND, ROWS, DEFAULTS)
        config = tomllib.loads(text)["ui"]
        self.assertEqual([item["command"] for item in config["tab_bar_right"]], ["date +%H:%M # clock", COMMAND])
        self.assertEqual(config["sidebar"]["agents"]["rows"], [["agent"], ["$hc_q1"]])
        self.assertEqual(config["sidebar_width"], 48)
        self.assertEqual(config["sidebar"]["agents"]["rows_by_agent"], {"pi": [["agent"]]})
        self.assertIn("# keep this comment", text)
        self.assertEqual(undo, {"rows": '[\n  ["state_icon", "agent"],  # mine\n]', "added": ["sidebar_max_width"]})

    def test_is_idempotent_and_replaces_an_old_command(self):
        text, _ = tomledit.setup(CONFIG, COMMAND, ROWS, DEFAULTS)
        self.assertEqual(tomledit.setup(text, COMMAND, ROWS, DEFAULTS)[0], text)
        moved, _ = tomledit.setup(text, "/usr/local/bin/herdr-codexbar bar", ROWS, DEFAULTS)
        commands = [item["command"] for item in tomllib.loads(moved)["ui"]["tab_bar_right"]]
        self.assertEqual(commands, ["date +%H:%M # clock", "/usr/local/bin/herdr-codexbar bar"])

    def test_uninstall_restores_the_original(self):
        text, undo = tomledit.setup(CONFIG, COMMAND, ROWS, DEFAULTS)
        self.assertEqual(tomledit.uninstall(text, undo), CONFIG)

    def test_empty_config(self):
        text, undo = tomledit.setup("", COMMAND, ROWS, DEFAULTS)
        config = tomllib.loads(text)["ui"]
        self.assertEqual((config["sidebar_width"], config["sidebar_max_width"]), (62, 80))
        self.assertEqual(undo["added"], ["sidebar_width", "sidebar_max_width"])
        restored = tomllib.loads(tomledit.uninstall(text, undo))
        self.assertEqual(restored, {"ui": {"tab_bar_right": [], "sidebar": {"agents": {}}}})

    def test_single_line_array(self):
        text, _ = tomledit.setup('[ui]\ntab_bar_right = [{ type = "command", command = "a" }]\n', COMMAND, ROWS, DEFAULTS)
        self.assertEqual(len(tomllib.loads(text)["ui"]["tab_bar_right"]), 2)

    def test_refuses_dotted_and_inline_forms(self):
        for config in ('ui.tab_bar_right = []\n', '[ui]\nsidebar = { agents = { rows = [] } }\n', '[ui.sidebar]\nagents.rows = []\n'):
            with self.assertRaises(tomledit.Unsupported, msg=config):
                tomledit.setup(config, COMMAND, ROWS, DEFAULTS)


if __name__ == "__main__":
    unittest.main()
