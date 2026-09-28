"""Read quota from the CodexBar CLI into a small private snapshot.

Only windows, plan names and pace are kept: no account identifiers, emails or
raw CodexBar output are stored or logged.
"""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from numbers import Real

from . import STATE_DIR

APP_CLI = "/Applications/CodexBar.app/Contents/Helpers/CodexBarCLI"
SNAPSHOT = STATE_DIR / "usage.json"
STALE_SECONDS = 600
SLOTS = ("primary", "secondary", "tertiary")
# Providers with a supported agent; CodexBar may have others enabled.
SUPPORTED = ("claude", "codex", "antigravity", "opencodego", "commandcode", "copilot", "grok")
# Window length for providers whose CodexBar windows have none: Copilot premium requests reset monthly.
DEFAULT_MINUTES = {"copilot": 30 * 1440}
# Antigravity bills Gemini and third-party (Claude, GPT) models from separate
# pools; its standard windows only summarize them.
AGY_POOLS = {
    "antigravity-quota-summary-gemini-5h": "gemini",
    "antigravity-quota-summary-gemini-weekly": "gemini",
    "antigravity-quota-summary-3p-5h": "claude-gpt",
    "antigravity-quota-summary-3p-weekly": "claude-gpt",
}
# Brand to put before a bare tier name ("plus" -> "ChatGPT Plus"); the default is the display name.
BRANDS = {"codex": "ChatGPT"}


def executable():
    return os.environ.get("CODEXBAR_BIN") or shutil.which("codexbar") or APP_CLI


def run_json(args, runner=subprocess.run):
    # CodexBar exits non-zero when one provider fails but still prints the others.
    result = runner([executable(), *args], capture_output=True, text=True, timeout=60, check=False)
    return json.loads(result.stdout)


def number(value, low=None, high=None):
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    if (low is not None and value < low) or (high is not None and value > high):
        return None
    return float(value)


def window_label(minutes):
    if not minutes:
        return None
    minutes = int(minutes)
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def pace_delta(pace):
    """CodexBar's pace in percentage points: positive is a deficit, negative a reserve."""
    if not isinstance(pace, dict):
        return None
    if "on pace" in str(pace.get("summary") or "").lower() or str(pace.get("stage") or "").lower() in ("onpace", "ontrack"):
        return 0.0
    return number(pace.get("deltaPercent"))


def window(data, pace=None, known=True, default_minutes=None):
    if not isinstance(data, dict):
        return None
    used = number(data.get("usedPercent"), 0, 100)
    minutes = number(data.get("windowMinutes"), 1) or default_minutes
    reset = data.get("resetsAt")
    return {
        "label": window_label(minutes),
        "minutes": minutes,
        "known": bool(known) and used is not None,
        "used": used,
        "resetsAt": reset if isinstance(reset, str) else None,
        "pace": pace_delta(pace),
    }


def plan_name(provider, login_method, display_name):
    """`Claude Pro`, `Google AI Pro`, `ChatGPT Plus`, `Command Code GOAT`, `OpenCode Go`."""
    display = display_name or provider
    base = str(login_method or "").split("·")[0].strip()
    if not base:
        return display
    if " " in base:
        return base
    tier = base[:1].upper() + base[1:] if base.islower() else base
    return f"{BRANDS.get(provider, display)} {tier}"


def normalize(raw, names=None, now=None):
    if not isinstance(raw, list):
        raise TypeError("CodexBar output must be an array")
    names = names or {}
    providers = {}
    for record in raw:
        if not isinstance(record, dict) or not isinstance(record.get("provider"), str):
            continue
        provider = record["provider"]
        if provider not in SUPPORTED:
            continue
        usage = record.get("usage")
        if not isinstance(usage, dict):
            continue
        pools = {}
        if provider == "antigravity":
            for entry in usage.get("extraRateWindows") or []:
                if isinstance(entry, dict) and entry.get("id") in AGY_POOLS:
                    item = window(entry.get("window"), known=entry.get("usageKnown") is not False)
                    if item:
                        pools.setdefault(AGY_POOLS[entry["id"]], []).append(item)
        else:
            pace = record.get("pace") if isinstance(record.get("pace"), dict) else {}
            for slot in SLOTS:
                item = window(usage.get(slot), pace.get(slot), default_minutes=DEFAULT_MINUTES.get(provider))
                if item:
                    pools.setdefault("", []).append(item)
        for items in pools.values():
            items.sort(key=lambda item: item["minutes"] or float("inf"))
        providers[provider] = {
            "name": names.get(provider) or provider,
            "plan": plan_name(provider, usage.get("loginMethod"), names.get(provider)),
            "pools": pools,
        }
    return {"updatedAt": (now or datetime.now(timezone.utc)).isoformat(), "providers": providers}


def poll(runner=subprocess.run):
    raw = run_json(["usage", "--provider", "", "--json"], runner)
    try:
        names = {entry["provider"]: entry.get("displayName") for entry in run_json(["config", "providers", "--json"], runner)}
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        names = {}
    snapshot = normalize(raw, names)
    if not any(provider["pools"] for provider in snapshot["providers"].values()):
        raise ValueError("CodexBar returned no quota windows; the previous snapshot is kept")
    write_json(SNAPSHOT, snapshot)
    return snapshot


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(payload, output, separators=(",", ":"))
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_snapshot(now=None):
    """The last snapshot, or None when missing or older than ten minutes."""
    try:
        snapshot = json.loads(SNAPSHOT.read_text())
        updated = datetime.fromisoformat(snapshot["updatedAt"])
        if not isinstance(snapshot.get("providers"), dict):
            return None
        if abs(((now or datetime.now(timezone.utc)) - updated).total_seconds()) > STALE_SECONDS:
            return None
        return snapshot
    except (OSError, ValueError, KeyError, TypeError):
        return None
