import io
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
        for directory in (".claude", ".codex", ".gemini/antigravity-cli", ".config/opencode", ".commandcode", ".copilot", ".grok", ".pi/agent", ".config/kilo", ".omp/agent", ".prime/agent", ".qwen"):
            (self.home / directory).mkdir(parents=True)
        (self.home / ".codex/hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]}}))
        (self.home / ".config/opencode/cli.json").write_text(json.dumps({"plugins": ["./herdr-opencode"]}))
        (self.home / ".copilot/settings.json").write_text(json.dumps({"theme": "github"}))
        (self.home / ".qwen/settings.json").write_text(json.dumps({"ui": {"autoModeAcknowledged": True}, "env": {"QWEN_KEY": "sk-secret"}}, indent=2))
        (self.home / ".grok/config.toml").write_text('[ui]\ntheme = "dark"\n\n[[marketplace.sources]]\nname = "x"\n')
        patches = [
            mock.patch.dict(os.environ, {"HOME": str(self.home), "HERDR_CODEXBAR_BIN": BIN}),
            mock.patch.object(install, "run", return_value=None),  # Never touch the real Herdr or brew.
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop("CODEX_HOME", None)
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
        qwen = self.read(".qwen/settings.json")
        self.assertEqual(qwen["ui"], {"autoModeAcknowledged": True, "statusLine": {"type": "command", "command": f"{BIN} hook qwen"}})
        self.assertEqual(qwen["env"], {"QWEN_KEY": "sk-secret"})
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

    def test_qwen_preset_status_line_needs_force(self):
        (self.home / ".qwen/settings.json").write_text(json.dumps({"ui": {"statusLine": {"type": "preset", "items": ["git-branch"]}}}))
        with self.assertRaises(install.Conflict):
            install.plan(self.home, BIN)
        install.setup(force=True)
        self.assertEqual(self.read(".qwen/settings.json")["ui"]["statusLine"]["command"], f"{BIN} hook qwen")

    def test_diff_hides_env_values(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            install.setup(dry_run=True)
        self.assertIn('"QWEN_KEY": "…"', output.getvalue())
        self.assertNotIn("sk-secret", output.getvalue())

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

    def test_detects_the_codex_daemon(self):
        pid_file = self.home / ".codex/app-server-daemon/daemon.pid"
        self.assertFalse(install.codex_daemon_running(self.home))
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text(json.dumps({"pid": os.getpid()}))
        self.assertTrue(install.codex_daemon_running(self.home))
        pid_file.write_text("not json")
        self.assertFalse(install.codex_daemon_running(self.home))

    def test_custom_codex_home_is_the_only_codex_target(self):
        directory = self.home / "isolated codex"
        directory.mkdir()
        personal = (self.home / ".codex/hooks.json").read_text()
        with mock.patch.dict(os.environ, CODEX_HOME=str(directory)):
            changes, _ = install.plan(self.home, BIN)
            paths = {path for path, _, _ in changes}
            self.assertIn(directory / "hooks.json", paths)
            self.assertIn(directory / "config.toml", paths)
            self.assertIn(directory / "herdr-codexbar.json", paths)
            self.assertNotIn(self.home / ".codex/hooks.json", paths)
            install.setup()
            self.assertEqual(install.plan(self.home, BIN)[0], [])
            self.assertEqual(json.loads((directory / "herdr-codexbar.json").read_text()), {"command": BIN})
            self.assertTrue(tomllib.loads((directory / "config.toml").read_text())["features"]["hooks"])
            install.uninstall()
            self.assertEqual(list(directory.iterdir()), [])
        self.assertEqual((self.home / ".codex/hooks.json").read_text(), personal)

    def test_custom_codex_home_is_detected_without_personal_home(self):
        directory = self.home / "bot"
        directory.mkdir()
        (self.home / ".codex/hooks.json").unlink()
        (self.home / ".codex").rmdir()
        with mock.patch.dict(os.environ, CODEX_HOME=str(directory)):
            self.assertIn("codex", install.installed(self.home))
            pid_file = directory / "app-server-daemon/daemon.pid"
            pid_file.parent.mkdir()
            pid_file.write_text(json.dumps({"pid": os.getpid()}))
            self.assertTrue(install.codex_daemon_running(self.home))

    def test_codex_setup_preserves_settings_and_refuses_disabled_hooks(self):
        path = self.home / ".codex/config.toml"
        original = '# User settings\nmodel = "example"\n[features]\nother = true # keep\n'
        path.write_text(original)
        changes = install.codex_config(self.home, BIN)
        install.write(changes, self.home)
        self.assertIn('other = true # keep', path.read_text())
        install.write(install.codex_config(self.home, BIN, remove=True), self.home)
        self.assertEqual(path.read_text(), original)
        path.write_text('[features]\nhooks = false\n')
        with self.assertRaises(install.Conflict):
            install.codex_config(self.home, BIN)
        self.assertEqual(path.read_text(), '[features]\nhooks = false\n')

    def test_uninstall_keeps_user_owned_hook_setting(self):
        path = self.home / ".codex/config.toml"
        path.write_text('[features]\nhooks = true # user setting\n')
        install.write(install.codex_config(self.home, BIN), self.home)
        install.write(install.codex_config(self.home, BIN, remove=True), self.home)
        self.assertEqual(path.read_text(), '[features]\nhooks = true # user setting\n')

    def test_uninstall_keeps_preexisting_empty_features_table_and_comments(self):
        path = self.home / ".codex/config.toml"
        original = '# User settings\n[features]\n# Keep this comment\n'
        path.write_text(original)
        install.write(install.codex_config(self.home, BIN), self.home)
        install.write(install.codex_config(self.home, BIN, remove=True), self.home)
        self.assertEqual(path.read_text(), original)

    def test_bridge_diagnostics_validate_the_active_descriptor(self):
        directory = self.home / "bot"
        directory.mkdir()
        descriptor = directory / "herdr-codexbar.json"
        with mock.patch.dict(os.environ, CODEX_HOME=str(directory)):
            self.assertFalse(install.codex_bridge_installed(self.home))
            descriptor.write_text("not JSON")
            self.assertFalse(install.codex_bridge_installed(self.home))
            descriptor.write_text(json.dumps({"command": "/missing/command"}))
            self.assertFalse(install.codex_bridge_installed(self.home))
            command = directory / "sidebar"
            command.write_text("#!/bin/sh\nexit 0\n")
            command.chmod(0o755)
            descriptor.write_text(json.dumps({"command": str(command)}))
            self.assertTrue(install.codex_bridge_installed(self.home))


if __name__ == "__main__":
    unittest.main()
