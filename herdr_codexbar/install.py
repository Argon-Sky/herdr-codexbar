"""`check`, `setup` and `uninstall`: wire each installed harness, Herdr's config and the poller.

Every change is planned first as (path, old contents, new contents), so
`setup --dry-run` shows exactly the diff `setup` would write. Existing files are
backed up before they change. Settings we did not write are never replaced
without `--force`.
"""

import copy
import difflib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from . import ISSUES_URL, STATE_DIR, codexbar, panes, tomledit

MARKER = "herdr-codexbar"
# Not resolved: under Homebrew this stays on the stable `opt` path across upgrades.
PACKAGE = Path(__file__).parent.absolute()
UNDO = STATE_DIR / "setup.json"
BACKUPS = STATE_DIR / "backups"
# Quota rows are 61 columns, plus 4 for the sidebar's indent and border; Herdr's
# defaults (26, capped at 36) would cut them off. Setup leaves a few columns spare.
# A blank row separates agents.
MIN_SIDEBAR_WIDTH = 65
DEFAULTS = {"ui": {"sidebar_width": 70, "sidebar_max_width": 80}, "ui.sidebar.agents": {"row_gap": 1}}
MIN_HERDR = (0, 9, 1)
ROWS = """[
  [
    { token = "state_icon", dim = false },
    { token = "workspace", fg = "#FEFEFE", dim = false },
    { token = "tab", fg = "#FEFEFE", dim = false },
  ],
  [
    { token = "agent", fg = "#FEFEFE", dim = false },
    { token = "$hc_plan", fg = "#FFD700", dim = false },
    { token = "$hc_pool", fg = "#FEFEFE", dim = false },
  ],
  [
    { token = "$hc_model", fg = "#B695F3", dim = false },
    { token = "$hc_effort", fg = "#B695F3", dim = false },
    { token = "$hc_context_1", fg = "#EAEAEA", dim = false },
    { token = "$hc_context_2", fg = "#F3FA9A", dim = false },
    { token = "$hc_context_3", fg = "#F09995", dim = false },
    { token = "$hc_context_4", fg = "#EC625C", dim = false },
    { token = "$hc_tokens", fg = "#FEFEFE", dim = false },
  ],
  [
    { token = "$hc_q1_label", fg = "#FEFEFE", dim = false },
    { token = "$hc_q1_bar", fg = "#FEFEFE", dim = false },
    { token = "$hc_q1_bar_reserve", fg = "#85F789", dim = false },
    { token = "$hc_q1_bar_pace", fg = "#A1E7FA", dim = false },
    { token = "$hc_q1_bar_deficit", fg = "#EC625C", dim = false },
    { token = "$hc_q1_left", fg = "#FEFEFE", dim = false },
    { token = "$hc_q1_pace", fg = "#FEFEFE", dim = false, rules = [{ contains = "reserve", fg = "#85F789" }, { contains = "on pace", fg = "#A1E7FA" }, { contains = "deficit", fg = "#EC625C" }] },
    { token = "$hc_q1_reset", fg = "#FEFEFE", dim = false },
  ],
  [
    { token = "$hc_q2_label", fg = "#FEFEFE", dim = false },
    { token = "$hc_q2_bar", fg = "#FEFEFE", dim = false },
    { token = "$hc_q2_bar_reserve", fg = "#85F789", dim = false },
    { token = "$hc_q2_bar_pace", fg = "#A1E7FA", dim = false },
    { token = "$hc_q2_bar_deficit", fg = "#EC625C", dim = false },
    { token = "$hc_q2_left", fg = "#FEFEFE", dim = false },
    { token = "$hc_q2_pace", fg = "#FEFEFE", dim = false, rules = [{ contains = "reserve", fg = "#85F789" }, { contains = "on pace", fg = "#A1E7FA" }, { contains = "deficit", fg = "#EC625C" }] },
    { token = "$hc_q2_reset", fg = "#FEFEFE", dim = false },
  ],
  [
    { token = "$hc_q3_label", fg = "#FEFEFE", dim = false },
    { token = "$hc_q3_bar", fg = "#FEFEFE", dim = false },
    { token = "$hc_q3_bar_reserve", fg = "#85F789", dim = false },
    { token = "$hc_q3_bar_pace", fg = "#A1E7FA", dim = false },
    { token = "$hc_q3_bar_deficit", fg = "#EC625C", dim = false },
    { token = "$hc_q3_left", fg = "#FEFEFE", dim = false },
    { token = "$hc_q3_pace", fg = "#FEFEFE", dim = false, rules = [{ contains = "reserve", fg = "#85F789" }, { contains = "on pace", fg = "#A1E7FA" }, { contains = "deficit", fg = "#EC625C" }] },
    { token = "$hc_q3_reset", fg = "#FEFEFE", dim = false },
  ],
]"""
CODEX_EVENTS = (("SessionStart", "startup|resume|clear|compact"), ("PostToolUse", None), ("Stop", None), ("PostCompact", None))
# Harness -> (config dir, CodexBar provider, Herdr integration)
HARNESSES = {
    "claude": (".claude", "claude", "claude"),
    "codex": (".codex", "codex", "codex"),
    "antigravity": (".gemini/antigravity-cli", "antigravity", "antigravity-cli"),
    "opencode": (".config/opencode", "opencodego", "opencode"),
    "commandcode": (".commandcode", "commandcode", None),
    "copilot": (".copilot", "copilot", "copilot"),
    "grok": (".grok", "grok", "grok"),
    "pi": (".pi/agent", "opencodego", "pi"),
    "kilo": (".config/kilo", "opencodego", "kilo"),
}


class Conflict(Exception):
    """A setting we would replace was written by someone else."""


def command():
    """How agents and Herdr call us: the Homebrew wrapper (or dev launcher) sets this."""
    path = os.environ.get("HERDR_CODEXBAR_BIN") or shutil.which(MARKER)
    if not path:
        raise SystemExit("herdr-codexbar: cannot tell where this command is installed; run it through `herdr-codexbar`, not `python -m`")
    return path


def home_dir():
    return Path(os.environ.get("HOME") or Path.home())


def installed(home):
    return [name for name, (directory, *_) in HARNESSES.items() if (home / directory).is_dir()]


# --- Planning: each returns [(path, old text or None, new text or None)]

def load_json(path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as error:
        raise tomledit.Unsupported(f"{path} is not plain JSON ({error}); edit it by hand") from None
    if not isinstance(data, dict):
        raise tomledit.Unsupported(f"{path} is not a JSON object")
    return data


def json_change(path, mutate, drop_empty=False):
    """`drop_empty` removes the file once nothing is left in it, for files setup may have created."""
    old = path.read_text() if path.is_file() else None
    data = load_json(path)
    updated = copy.deepcopy(data)
    mutate(updated)
    if updated == data:
        return []
    keep = updated or (old and not drop_empty)
    return [(path, old, json.dumps(updated, indent=2, ensure_ascii=False) + "\n" if keep else None)]


def status_line(path, line, force, remove=False):
    def mutate(settings):
        current = settings.get("statusLine") or {}
        ours = MARKER in str(current.get("command", ""))
        if remove:
            if ours:
                del settings["statusLine"]
            return
        if current.get("command") and not ours and not force:
            raise Conflict(f"{path} already has a statusLine ({current['command']}); rerun with --force to replace it")
        settings["statusLine"] = {"type": "command", "command": line, "padding": current.get("padding", 0)}
    return json_change(path, mutate)


def grok_status_line(path, line, force, remove=False):
    """Grok Build's status line lives in `[ui.status_line]` of its TOML config."""
    old = path.read_text() if path.is_file() else ""
    current = tomllib.loads(old).get("ui", {}).get("status_line", {})
    ours = MARKER in str(current.get("command", ""))
    if remove:
        new = tomledit.remove_table(old, "ui.status_line") if ours else old
    else:
        if current.get("command") and not ours and not force:
            raise Conflict(f"{path} already has a status line ({current['command']}); rerun with --force to replace it")
        new = tomledit.set_table(old, "ui.status_line", {"type": '"command"', "command": tomledit.toml_string(line)})
    return [(path, old or None, new or None)] if new != old else []


def codex_hooks(path, line, remove=False):
    def mutate(settings):
        hooks = settings.setdefault("hooks", {})
        for event, matcher in CODEX_EVENTS:
            groups = [group for group in hooks.get(event, []) if not any(MARKER in hook.get("command", "") for hook in group.get("hooks", []))]
            if not remove:
                ours = [group for group in hooks.get(event, []) if any(MARKER in hook.get("command", "") for hook in group.get("hooks", []))]
                wanted = {**({"matcher": matcher} if matcher else {}), "hooks": [{"type": "command", "command": line, "timeout": 10}]}
                # An unchanged entry keeps Codex's trust approval; only rewrite what differs.
                groups.append(ours[0] if ours == [wanted] else wanted)
            if groups:
                hooks[event] = groups
            else:
                hooks.pop(event, None)
        if not hooks:
            settings.pop("hooks")
    return json_change(path, mutate)


def opencode(home, bin_path, remove=False):
    directory = home / ".config/opencode"
    shim = directory / MARKER / "tui.js"
    source = PACKAGE / "agents/opencode.js"
    text = f"// installed by herdr-codexbar; `herdr-codexbar uninstall` removes it\nimport {{ create }} from {json.dumps(source.as_uri())};\n\nexport default create({json.dumps(bin_path)});\n"

    def mutate(settings):
        plugins = [plugin for plugin in settings.get("plugins", []) if plugin != f"./{MARKER}"]
        settings["plugins"] = plugins if remove else [*plugins, f"./{MARKER}"]
        if remove and not plugins:
            settings.pop("plugins")
    old = shim.read_text() if shim.is_file() else None
    changes = [(shim, old, None if remove else text)] if old != (None if remove else text) else []
    return changes + json_change(directory / "cli.json", mutate)


def kilo(home, bin_path, remove=False):
    directory = home / ".config/kilo"
    shim = directory / MARKER / "tui.js"
    source = PACKAGE / "agents/kilo.js"
    text = f"// installed by herdr-codexbar; `herdr-codexbar uninstall` removes it\nimport {{ create }} from {json.dumps(source.as_uri())};\n\nexport default create({json.dumps(bin_path)});\n"
    entry = f"./{MARKER}/tui.js"

    def mutate(settings):
        plugins = [plugin for plugin in settings.get("plugin", []) if plugin != entry]
        settings["plugin"] = plugins if remove else [*plugins, entry]
        if remove and not plugins:
            settings.pop("plugin")
    old = shim.read_text() if shim.is_file() else None
    changes = [(shim, old, None if remove else text)] if old != (None if remove else text) else []
    return changes + json_change(directory / "tui.json", mutate, drop_empty=True)


def pi(home, bin_path, remove=False):
    extension = home / ".pi/agent/extensions" / f"{MARKER}.ts"
    text = (PACKAGE / "agents/pi.ts").read_text().replace("__HERDR_CODEXBAR_BIN__", json.dumps(bin_path)[1:-1])
    old = extension.read_text() if extension.is_file() else None
    new = None if remove else text
    return [(extension, old, new)] if old != new else []


def commandcode(home, bin_path, remove=False):
    mod = home / ".commandcode/mods" / f"{MARKER}.ts"
    text = (PACKAGE / "agents/commandcode.ts").read_text().replace("__HERDR_CODEXBAR_BIN__", json.dumps(bin_path)[1:-1])
    old = mod.read_text() if mod.is_file() else None
    new = None if remove else text
    return [(mod, old, new)] if old != new else []


def herdr_config_path(home):
    return home / ".config/herdr/config.toml"


def herdr_config(home, remove=False):
    """The config change, plus what uninstall needs to undo it (None when the old undo still applies)."""
    path = herdr_config_path(home)
    old = path.read_text() if path.is_file() else ""
    if remove:
        new, undo = tomledit.uninstall(old, read_undo()), None
    else:
        new, undo = tomledit.setup(old, ROWS, DEFAULTS)
        if tomledit.rows_are_ours(old):
            undo = None  # Rows are already ours; keep the undo saved by the first setup.
    return ([(path, old or None, new)] if new != old else []), undo


def plan(home, bin_path, force=False, remove=False):
    line = shlex.quote(bin_path)
    harnesses = installed(home)
    changes, undo = herdr_config(home, remove)
    if "claude" in harnesses:
        changes += status_line(home / ".claude/settings.json", f"{line} hook claude", force, remove)
    if "antigravity" in harnesses:
        changes += status_line(home / ".gemini/antigravity-cli/settings.json", f"{line} hook antigravity", force, remove)
    if "codex" in harnesses:
        changes += codex_hooks(home / ".codex/hooks.json", f"{line} hook codex", remove)
    if "copilot" in harnesses:
        changes += status_line(home / ".copilot/settings.json", f"{line} hook copilot", force, remove)
    if "grok" in harnesses:
        changes += grok_status_line(home / ".grok/config.toml", f"{line} hook grok", force, remove)
    if "opencode" in harnesses:
        changes += opencode(home, bin_path, remove)
    if "commandcode" in harnesses:
        changes += commandcode(home, bin_path, remove)
    if "kilo" in harnesses:
        changes += kilo(home, bin_path, remove)
    if "pi" in harnesses:
        changes += pi(home, bin_path, remove)
    return changes, undo


# --- Applying

def read_undo():
    try:
        return json.loads(UNDO.read_text())
    except (OSError, ValueError):
        return {}


def show(changes, home):
    for path, old, new in changes:
        name = f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)
        verb = "create" if old is None else "remove" if new is None else "update"
        print(f"{verb} {name}")
        if path.suffix in (".js", ".ts"):
            continue  # Our own plugin files; the diff would only repeat their source.
        diff = difflib.unified_diff((old or "").splitlines(True), (new or "").splitlines(True), f"{name} (now)", f"{name} (after)")
        sys.stdout.writelines(f"    {line}" if line.endswith("\n") else f"    {line}\n" for line in diff)


def write(changes, home):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, old, new in changes:
        if old is not None:
            backup = BACKUPS / stamp / path.relative_to(home) if path.is_relative_to(home) else BACKUPS / stamp / path.name
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, backup)
        if new is None:
            path.unlink(missing_ok=True)
            if path.parent.name == MARKER and not any(path.parent.iterdir()):
                path.parent.rmdir()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        temporary = path.with_name(f".{path.name}.{MARKER}")
        temporary.write_text(new)
        temporary.chmod(mode)
        temporary.replace(path)
    if any(old is not None for _, old, _ in changes):
        print(f"backups: {BACKUPS / stamp}")


def brew():
    return shutil.which("brew") if os.environ.get("HERDR_CODEXBAR_BREW") == "1" else None


def run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def setup(dry_run=False, force=False):
    home, bin_path = home_dir(), command()
    try:
        changes, undo = plan(home, bin_path, force)
    except (Conflict, tomledit.Unsupported, tomllib.TOMLDecodeError) as error:
        raise SystemExit(f"herdr-codexbar: {error}") from None
    if not changes:
        print("Everything is already set up.")
    show(changes, home)
    if dry_run:
        print("\nDry run: nothing was changed. Run `herdr-codexbar setup` to apply." if changes else "")
        return
    if undo is not None:
        codexbar.write_json(UNDO, undo)  # The rows and width to restore on uninstall.
    write(changes, home)
    if brew():
        result = run([brew(), "services", "restart", MARKER])
        print("poller: running (brew services)" if result and result.returncode == 0 else f"poller: could not start; run `brew services restart {MARKER}`")
    else:
        print(f"poller: not a Homebrew install; run `{shlex.quote(bin_path)} refresh` every few minutes yourself")
    result = run(["herdr", "server", "reload-config"])
    print("Herdr config reloaded." if result and result.returncode == 0 else "Herdr is not running; the config applies on its next start.")
    print("Restart running agents so they pick up the new hooks. Codex asks you to approve them on its first start.")


def uninstall(dry_run=False):
    home, bin_path = home_dir(), command()
    try:
        changes, _ = plan(home, bin_path, remove=True)
    except (tomledit.Unsupported, tomllib.TOMLDecodeError) as error:
        raise SystemExit(f"herdr-codexbar: {error}") from None
    show(changes, home)
    if dry_run:
        print("\nDry run: nothing was changed.")
        return
    write(changes, home)
    if brew():
        run([brew(), "services", "stop", MARKER])
    panes.clear_all()
    for path in (UNDO, codexbar.SNAPSHOT):
        path.unlink(missing_ok=True)
    run(["herdr", "server", "reload-config"])
    print(f"Removed. Backups stay in {BACKUPS}; `brew uninstall {MARKER}` removes the package.")


# --- check

def version(text):
    try:
        return tuple(int(part) for part in text.split()[-1].split(".")[:3])
    except ValueError:
        return None


def fonts(home):
    directories = [home / "Library/Fonts", Path("/Library/Fonts")]
    names = [path.name for directory in directories if directory.is_dir() for path in directory.iterdir()]
    # Fira Code 6+ and Nerd Fonts 3+ both draw the progress-bar glyphs.
    return [name for name in names if name.lower().startswith("firacode") or "nerdfont" in name.lower().replace(" ", "")]


def check():
    home = home_dir()
    problems = warnings = 0

    def report(ok, message, hint=None, required=True):
        nonlocal problems, warnings
        print(f"{'ok  ' if ok else 'FAIL' if required else 'warn'}  {message}")
        if not ok and hint:
            print(f"      {hint}")
        if not ok:
            problems += required
            warnings += not required

    herdr = shutil.which("herdr") or os.environ.get("HERDR_BIN_PATH")
    result = run([herdr, "--version"]) if herdr else None
    found = version(result.stdout) if result and result.returncode == 0 else None
    report(found is not None and found >= MIN_HERDR, f"Herdr {'.'.join(map(str, found)) if found else 'not found'}", "install Herdr 0.9.1 or newer: https://herdr.dev")

    cli = codexbar.executable()
    try:
        providers = codexbar.run_json(["config", "providers", "--json"])
        enabled = [entry["provider"] for entry in providers if entry.get("enabled") and entry["provider"] in codexbar.SUPPORTED]
        report(True, f"CodexBar CLI ({cli})")
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        enabled = []
        report(False, "CodexBar CLI not found", "install CodexBar: `brew install --cask codexbar`, open it once and sign in to your providers")
    snapshot = codexbar.read_snapshot()
    for provider in enabled:
        data = (snapshot or {}).get("providers", {}).get(provider)
        detail = f"{data['plan']}: {' '.join(window['label'] or '?' for pool in data['pools'].values() for window in pool)}" if data else "no quota yet"
        print(f"      {provider:<12} {detail}")

    harnesses = installed(home)
    report(bool(harnesses), f"agents found: {', '.join(harnesses) or 'none'}", "install a supported agent, such as Claude Code, Codex, OpenCode or Pi")
    result = run([herdr, "integration", "status"]) if herdr else None
    status = result.stdout if result else ""
    for name in harnesses:
        _, provider, integration = HARNESSES[name]
        if integration:
            report(f"{integration}: current" in status, f"Herdr integration for {name}", f"run `herdr integration install {integration}`")
        if provider not in enabled:
            report(False, f"CodexBar provider `{provider}` for {name} is off", f"run `codexbar config enable --provider {provider}` if you use it", required=False)
    if "codex" in harnesses:
        try:
            hooks_on = tomllib.loads((home / ".codex/config.toml").read_text()).get("features", {}).get("hooks") is True
        except (OSError, ValueError):
            hooks_on = False
        report(hooks_on, "Codex hooks enabled", "add `hooks = true` under [features] in ~/.codex/config.toml")

    try:
        bin_path = command()
        pending, _ = plan(home, bin_path)
        report(not pending, "setup is up to date" if not pending else f"setup would change {len(pending)} file(s)", "run `herdr-codexbar setup --dry-run` to see what, then `herdr-codexbar setup`")
    except (Conflict, tomledit.Unsupported, tomllib.TOMLDecodeError) as error:
        report(False, "setup cannot run", str(error))
    except SystemExit as error:
        report(False, "setup cannot run", str(error))
    try:
        config = tomllib.loads(herdr_config_path(home).read_text())
        overrides = sorted(set(config.get("ui", {}).get("sidebar", {}).get("agents", {}).get("rows_by_agent", {})) & set(panes.HARNESSES.values()))
        ui = config.get("ui", {})
        wide = min(ui.get("sidebar_width", MIN_SIDEBAR_WIDTH), ui.get("sidebar_max_width", 80)) >= MIN_SIDEBAR_WIDTH
        report(wide, "sidebar is wide enough for quota rows", "set sidebar_width = 70 and sidebar_max_width = 80 under [ui] in ~/.config/herdr/config.toml", required=False)
        report(not overrides, "no per-agent sidebar rows override ours", f"remove {', '.join(overrides)} from [ui.sidebar.agents.rows_by_agent] in ~/.config/herdr/config.toml", required=False)
    except (OSError, ValueError):
        pass

    report(snapshot is not None, "quota snapshot is fresh", "run `herdr-codexbar refresh` and check its error; with Homebrew, `brew services info herdr-codexbar`")
    report(bool(fonts(home)), "Fira Code or a Nerd Font is installed", "install Fira Code 6+ (`brew install --cask font-fira-code`) and use it in your terminal for the quota bars", required=False)

    print()
    if problems:
        print(f"{problems} problem(s). Stuck? {ISSUES_URL}")
    else:
        print(f"All good{f' ({warnings} warning(s))' if warnings else ''}.")
    return 1 if problems else 0
