"""Route each agent pane to the subscription it is using and publish its sidebar tokens.

A harness (the agent CLI) reports what its pane is doing: model, effort, context
and the provider ID it is talking to. The provider ID decides which CodexBar
subscription's quota the pane shows, so one harness can switch between
subscriptions, and two panes of the same harness can show different ones.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import STATE_DIR, codexbar, render

# Harness -> Herdr agent ID shown by `herdr pane list`.
HARNESSES = {"claude": "claude", "codex": "codex", "antigravity": "agy", "opencode": "opencode", "commandcode": "cmd", "copilot": "copilot", "grok": "grok", "pi": "pi", "kilo": "kilo"}
# Herdr names Command Code panes `cmd · <model>`; the model has its own row, so show the bare agent ID.
PLAIN_NAMES = ("commandcode",)
# Provider ID reported by a harness -> CodexBar provider. OpenCode custom providers
# use the ID from the user's config, so name them after the CodexBar provider.
PROVIDERS = {
    "anthropic": "claude",
    "claude": "claude",
    "openai": "codex",
    "codex": "codex",
    "openai-codex": "codex",  # Pi's ChatGPT sign-in
    "antigravity": "antigravity",
    "opencode-go": "opencodego",
    "opencodego": "opencodego",
    "commandcode": "commandcode",
    "command-code": "commandcode",
    "github-copilot": "copilot",
    "copilot": "copilot",
    "grok": "grok",
    "xai": "grok",  # Pi and Kilo's xAI sign-in; an xAI API key shows the same quota
}
POOL_NAMES = {"gemini": "Gemini", "claude-gpt": "Claude & GPT"}
PACE_STATES = ("reserve", "pace", "deficit")
# Per quota row: the bar is published under the token of its pace state, so the
# sidebar can color it; the pace text is colored by a rule on its own words.
ROW_PARTS = ("label", "bar", *(f"bar_{state}" for state in PACE_STATES), "left", "pace", "reset")
QUOTA_TOKENS = ("hc_plan", "hc_pool", *(f"hc_q{row}_{part}" for row in (1, 2, 3) for part in ROW_PARTS))
# Context percent is published under the token of its band: <25, 25-50, 50-75, >75.
CONTEXT_BANDS = (25, 50, 75)
META_TOKENS = ("hc_model", "hc_effort", *(f"hc_context_{band}" for band in range(1, len(CONTEXT_BANDS) + 2)), "hc_tokens")
MAX_UPDATES = 16  # Herdr's limit per report-metadata call.
SOURCE = "user:herdr-codexbar"
PANE_ID = re.compile(r"w[A-Za-z0-9_-]+:p[A-Za-z0-9_-]+")
PANES_DIR = STATE_DIR / "panes"


def compact_tokens(value):
    if value >= 1_000_000:
        return f"{round(value / 1_000_000)}M"
    if value >= 1_000:
        return f"{round(value / 1_000)}k"
    return str(round(value))


def route(report):
    """(CodexBar provider, pool) for a report; (None, None) for providers without CodexBar quota."""
    provider = PROVIDERS.get(str(report.get("provider_id") or "").lower())
    if provider != "antigravity":
        return provider, None
    model = str(report.get("model") or "").lower()
    return provider, ("gemini" if "gemini" in model else "claude-gpt") if model else None


def context_band(percent):
    """1 below 25%, 2 up to 50%, 3 up to 75%, 4 above."""
    low, mid, high = CONTEXT_BANDS
    return 1 + (percent >= low) + (percent > mid) + (percent > high)


def meta_tokens(report):
    values = dict.fromkeys(META_TOKENS)
    values.update({"hc_model": report.get("model") or None, "hc_effort": report.get("effort") or None})
    used, limit, percent = report.get("context_used"), report.get("context_limit"), report.get("context_percent")
    if percent is None and used and limit:
        percent = used / limit * 100
    if percent is not None:
        values[f"hc_context_{context_band(round(percent))}"] = f"context {round(percent)}%"
    if used:
        values["hc_tokens"] = f"{compact_tokens(used)} / {compact_tokens(limit)}" if limit else compact_tokens(used)
    return values


def quota_tokens(provider, pool, snapshot, now=None):
    values = dict.fromkeys(QUOTA_TOKENS)
    if provider is None:
        return values
    if snapshot is None:
        values["hc_q1_label"] = "quota unavailable"
        return values
    data = snapshot["providers"].get(provider)
    if data is None:
        return values  # Not enabled in CodexBar.
    values["hc_plan"] = data["plan"]
    values["hc_pool"] = POOL_NAMES.get(pool)
    for row, window in enumerate(data["pools"].get(pool or "", [])[:3], 1):
        parts = render.quota_parts(window, now)
        bar = f"bar_{parts['state']}" if parts["state"] else "bar"
        for part in ("label", "left", "pace", "reset"):
            values[f"hc_q{row}_{part}"] = parts[part]
        values[f"hc_q{row}_{bar}"] = parts["bar"]
    return values


def herdr_bin(env=os.environ):
    return env.get("HERDR_BIN_PATH") or shutil.which("herdr") or str(Path.home() / ".local/bin/herdr")


def publish(entry, values, runner=subprocess.run, remove=False):
    """Set or clear tokens; `remove` also drops the display name we set."""
    # Clears first: a pane holds at most 32 tokens, and a batch of new ones could pass that before the old ones go.
    items = sorted(values.items(), key=lambda item: item[1] is not None)
    for start in range(0, len(items), MAX_UPDATES):
        args = [entry["herdr"], "pane", "report-metadata", entry["pane"], "--source", SOURCE]
        if start == 0 and remove:
            args.append("--clear-display-agent")
        elif start == 0 and entry["harness"] in PLAIN_NAMES:
            # The --agent guard drops the name, not the tokens, once another program runs in the pane.
            name = HARNESSES[entry["harness"]]
            args += ["--agent", name, "--display-agent", name]
        for key, value in items[start:start + MAX_UPDATES]:
            args += ["--token", f"{key}={value}"] if value else ["--clear-token", key]
        runner(args, check=True, capture_output=True, timeout=5, env=dict(os.environ, HERDR_SOCKET_PATH=entry["socket"]))


def registration_path(pane):
    return PANES_DIR / f"{pane.replace(':', '_')}.json"


def register(entry):
    path = registration_path(entry["pane"])
    try:
        if json.loads(path.read_text()) == entry:
            return
    except (OSError, ValueError):
        pass
    codexbar.write_json(path, entry)


def report(data, env=os.environ, runner=subprocess.run, now=None):
    """Publish everything for the calling pane from a harness report."""
    pane = env.get("HERDR_PANE_ID", "")
    if env.get("HERDR_ENV") != "1" or not env.get("HERDR_SOCKET_PATH") or not PANE_ID.fullmatch(pane):
        return
    provider, pool = route(data)
    entry = {"pane": pane, "socket": env["HERDR_SOCKET_PATH"], "herdr": herdr_bin(env), "harness": data["harness"], "provider": provider, "pool": pool}
    register(entry)
    publish(entry, {**meta_tokens(data), **quota_tokens(provider, pool, codexbar.read_snapshot(now), now)}, runner)


def live_agents(entry, runner=subprocess.run):
    """Pane ID -> agent ID for one Herdr server."""
    result = runner([entry["herdr"], "pane", "list"], check=True, capture_output=True, text=True, timeout=5,
                    env=dict(os.environ, HERDR_SOCKET_PATH=entry["socket"]))
    return {pane["pane_id"]: pane.get("agent") for pane in json.loads(result.stdout)["result"]["panes"]}


def refresh_panes(snapshot, runner=subprocess.run, now=None):
    """Update quota rows in every registered pane; forget closed panes and replaced agents."""
    failed = 0
    servers = {}
    for path in PANES_DIR.glob("*.json"):
        try:
            entry = json.loads(path.read_text())
            if entry.get("harness") not in HARNESSES or not PANE_ID.fullmatch(entry.get("pane", "")) or not entry.get("socket"):
                path.unlink(missing_ok=True)
                continue
            if entry["socket"] not in servers:
                servers[entry["socket"]] = live_agents(entry, runner)
            agents = servers[entry["socket"]]
            if entry["pane"] not in agents:
                path.unlink(missing_ok=True)  # Pane closed; pane IDs are never reused.
            elif agents[entry["pane"]] != HARNESSES[entry["harness"]]:
                path.unlink(missing_ok=True)  # Another program took over the pane: remove our rows.
                publish(entry, dict.fromkeys(QUOTA_TOKENS + META_TOKENS), runner, remove=True)
            else:
                publish(entry, quota_tokens(entry["provider"], entry["pool"], snapshot, now), runner)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            failed += 1  # An unreachable server is retried on the next refresh.
            print(f"herdr-codexbar: {path.name}: {herdr_error(error)}", file=sys.stderr)
    return failed


def herdr_error(error):
    """Herdr's own message for a failed call, not the command line, which holds the token values."""
    if not isinstance(error, subprocess.CalledProcessError):
        return str(error)
    output = error.stdout or error.stderr or b""
    output = output.decode(errors="replace") if isinstance(output, bytes) else output
    try:
        return json.loads(output)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return output.strip() or f"herdr exited with status {error.returncode}"


def clear_all(runner=subprocess.run):
    """Remove our tokens from every registered pane and forget them."""
    for path in PANES_DIR.glob("*.json"):
        try:
            publish(json.loads(path.read_text()), dict.fromkeys(QUOTA_TOKENS + META_TOKENS), runner, remove=True)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            pass  # The pane or its server is gone.
        path.unlink(missing_ok=True)
