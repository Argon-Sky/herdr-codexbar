import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from herdr_codexbar import install

BIN = "/opt/homebrew/bin/herdr-codexbar"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        for directory in (".claude", ".codex", ".gemini/antigravity-cli", ".config/opencode", ".commandcode", ".copilot", ".grok", ".pi/agent", ".config/kilo", ".omp/agent", ".prime/agent"):
            (self.home / directory).mkdir(parents=True)
        (self.home / ".codex/hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]}}))
        (self.home / ".config/opencode/cli.json").write_text(json.dumps({"plugins": ["./herdr-opencode"]}))
        (self.home / ".copilot/settings.json").write_text(json.dumps({"theme": "github"}))
        (self.home / ".grok/config.toml").write_text('[ui]\ntheme = "dark"\n\n[[marketplace.sources]]\nname = "x"\n')
        patches = [
            mock.patch.dict(os.environ, {"HOME": str(self.home), "HERDR_CODEXBAR_BIN": BIN}),
            mock.patch.object(install, "run", return_value=None),  # Never touch the real Herdr or brew.
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        install.UNDO.unlink(missing_ok=True)

    def read(self, relative):
        return json.loads((self.home / relative).read_text())

    def test_setup_wires_every_agent_and_is_idempotent(self):
        install.setup()
        self.assertEqual(self.read(".claude/settings.json")["statusLine"]["command"], f"{BIN} hook claude")
        self.assertEqual(self.read(".gemini/antigravity-cli/settings.json")["statusLine"]["command"], f"{BIN} hook antigravity")
        self.assertEqual(self.read(".copilot/settings.json"), {"theme": "github", "statusLine": {"type": "command", "command": f"{BIN} hook copilot", "padding": 0}})
        grok = tomllib.loads((self.home / ".grok/config.toml").read_text())
        self.assertEqual(grok["ui"], {"theme": "dark", "status_line": {"type": "command", "command": f"{BIN} hook grok"}})
        self.assertEqual(grok["marketplace"]["sources"], [{"name": "x"}])
        hooks = self.read(".codex/hooks.json")["hooks"]
        self.assertEqual(sorted(hooks), ["PostCompact", "PostToolUse", "SessionStart", "Stop"])
        self.assertEqual(hooks["Stop"][0]["hooks"][0]["command"], "notify")
        self.assertEqual(hooks["SessionStart"][0]["matcher"], "startup|resume|clear|compact")
        self.assertEqual(self.read(".config/opencode/cli.json")["plugins"], ["./herdr-opencode", "./herdr-codexbar"])
        shim = (self.home / ".config/opencode/herdr-codexbar/tui.js").read_text()
        self.assertIn('create("/opt/homebrew/bin/herdr-codexbar")', shim)
        self.assertIn('/herdr_codexbar/agents/opencode.js', shim)
        self.assertEqual(self.read(".config/kilo/tui.json"), {"plugin": ["./herdr-codexbar/tui.js"]})
        self.assertIn('/herdr_codexbar/agents/kilo.js', (self.home / ".config/kilo/herdr-codexbar/tui.js").read_text())
        for directory, harness, agent in ((".pi", "pi", ""), (".omp", "omp", ""), (".prime", "prime", "prime-agent")):
            extension = (self.home / directory / "agent/extensions/herdr-codexbar.ts").read_text()
            self.assertIn(f'const COMMAND = "{BIN}";', extension)
            self.assertIn(f'const HARNESS = "{harness}";', extension)
            self.assertIn(f'const AGENT = "{agent}";', extension)
        mod = (self.home / ".commandcode/mods/herdr-codexbar.ts").read_text()
        self.assertIn(f'const COMMAND = "{BIN}";', mod)
        config = tomllib.loads((self.home / ".config/herdr/config.toml").read_text())
        self.assertIn("$hc_q1_label", str(config["ui"]["sidebar"]["agents"]["rows"]))
        self.assertEqual(install.plan(self.home, BIN)[0], [])

    def test_paths_with_spaces_are_quoted(self):
        changes, _ = install.plan(self.home, "/Users/me/My Tools/herdr-codexbar")
        text = dict((str(path), new) for path, _, new in changes)[str(self.home / ".claude/settings.json")]
        self.assertIn("'/Users/me/My Tools/herdr-codexbar' hook claude", text)

    def test_foreign_status_line_needs_force(self):
        (self.home / ".claude/settings.json").write_text(json.dumps({"statusLine": {"type": "command", "command": "~/status.sh"}, "theme": "dark"}))
        with self.assertRaises(install.Conflict):
            install.plan(self.home, BIN)
        install.setup(force=True)
        settings = self.read(".claude/settings.json")
        self.assertEqual((settings["statusLine"]["command"], settings["theme"]), (f"{BIN} hook claude", "dark"))

    def test_dry_run_writes_nothing(self):
        install.setup(dry_run=True)
        self.assertFalse((self.home / ".claude/settings.json").exists())
        self.assertFalse((self.home / ".config/herdr/config.toml").exists())

    def test_uninstall_restores_everything(self):
        config = self.home / ".config/herdr/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[ui.sidebar.agents]\nrows = [["agent"]]\n')
        before = {path: path.read_text() for path in self.home.rglob("*") if path.is_file()}
        install.setup()
        install.uninstall()
        after = {path: path.read_text() for path in self.home.rglob("*") if path.is_file()}
        self.assertEqual(after.pop(self.home / ".claude/settings.json"), "{}\n")
        self.assertEqual(after.pop(self.home / ".gemini/antigravity-cli/settings.json"), "{}\n")
        self.assertEqual(after.pop(config).strip().removesuffix("[ui]").strip(), before.pop(config).strip())
        grok = self.home / ".grok/config.toml"
        self.assertEqual(after.pop(grok), before.pop(grok))
        self.assertEqual({path: json.loads(text) for path, text in after.items()}, {path: json.loads(text) for path, text in before.items()})


if __name__ == "__main__":
    unittest.main()
