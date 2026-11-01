"""Read quota from the CodexBar CLI into a small private snapshot.

Only windows, plan names, pace, CodexBar's run-out estimate and usable credits with their expiry are kept: no account identifiers, emails or raw CodexBar output are stored or logged.
A provider's windows go into its pools, which the sidebar shows; CodexBar's extra windows that apply to one model only go into its models, by model name.
"""

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from numbers import Real

from . import STATE_DIR

APP_CLI = "/Applications/CodexBar.app/Contents/Helpers/CodexBarCLI"
SNAPSHOT = STATE_DIR / "usage.json"
STALE_SECONDS = 600
SLOTS = ("primary", "secondary", "tertiary")
# Providers with a supported agent; CodexBar may have others enabled.
SUPPORTED = ("claude", "codex", "antigravity", "opencodego", "commandcode", "copilot", "grok", "qwencloud")
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
# CodexBar's extra windows that are not one model's limit, by id: a renewal date (OpenCode Go's `renewal`), Claude's Daily Routines and monthly Extra usage, Antigravity's offline conversation count and the reset-only rows of its two pools, Qwen Cloud's own monthly quota, and Copilot's opt-in spend budgets, whose titles can carry a budget's name.
NOT_MODEL_WINDOWS = {"renewal", "claude-routines", "claude-extra-usage", "antigravity-offline-conversations", "antigravity-gemini", "antigravity-claude-gpt", "monthly"}
NOT_MODEL_PREFIXES = ("copilot-budget",)
# Trailing words of an extra window's title that give its length or scope rather than its model: "Opus only", "Gemini Ultra weekly", "Claude/GPT 5-hour".
NOT_MODEL = re.compile(r"only|weekly|daily|monthly|hourly|session|\d+(?:[mhdw]|-?(?:minute|hour|day|week|month)s?)", re.IGNORECASE)
# The CodexBar source that names a provider's plan when the configured one does not: Antigravity's agy report has no plan, its OAuth source has.
PLAN_SOURCES = {"antigravity": "oauth"}
# Seconds between two reads of a plan source, whether the last one worked or not; the poller runs every few minutes.
PLAN_EVERY = 3600
# The last plan read from a plan source and when it was read, nothing else.
PLANS = STATE_DIR / "plans.json"
# Brand to put before a bare tier name ("plus" -> "ChatGPT Plus"); the default is the display name.
BRANDS = {"codex": "ChatGPT"}
# CodexBar's own constants for the credit sources: ClaudeCloudCreditsSnapshot.detailRowID and the label of Claude's and Grok's limit reset rows.
CLOUD_ROW = "claude-cloud-credits"
RESET_LABEL = "Limit Reset Credits"
MONTHS = {name: number for number, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december")), 1) for name in names}


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


def runs_out_at(pace, now):
    """When CodexBar says the window runs out before its reset: its `etaSeconds` after `now`, as ISO 8601; None when it lasts or gives no usable time."""
    if not isinstance(pace, dict) or pace.get("willLastToReset") is not False or now is None:
        return None
    eta = number(pace.get("etaSeconds"), 0)
    if eta is None or not math.isfinite(eta):
        return None
    try:
        return (now + timedelta(seconds=eta)).isoformat()
    except OverflowError:
        return None


def window(data, pace=None, known=True, default_minutes=None, now=None):
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
        "runsOutAt": runs_out_at(pace, now),
    }


def plan_name(provider, login_method, display_name):
    """`Claude Pro`, `Google AI Pro`, `ChatGPT Plus`, `Command Code GOAT`, `OpenCode Go`, `Qwen Cloud Essential`."""
    display = display_name or provider
    base = str(login_method or "").split("·")[0].strip()
    if not base:
        return display
    if " " in base:
        return base
    tier = base[:1].upper() + base[1:] if base.islower() else base
    return f"{BRANDS.get(provider, display)} {tier}"


def model_name(title, window_id):
    """The model an extra window applies to: CodexBar's title without trailing length words or "only", the whole title when nothing would remain, else the window's id."""
    if isinstance(title, str) and title.strip():
        words = title.split()
        while len(words) > 1 and NOT_MODEL.fullmatch(words[-1]):
            words.pop()
        return " ".join(words)
    return window_id if isinstance(window_id, str) and window_id else None


def account(usage):
    """The account a record was read for, to compare two records in memory; never stored."""
    value = usage.get("accountEmail")
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def login(usage):
    """The record's own plan: its `loginMethod` when that names one."""
    value = usage.get("loginMethod")
    return value if isinstance(value, str) and value.split("·")[0].strip() else None


def instant(value):
    """An ISO 8601 time with a zone, as UTC; None for anything else."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def local_time(day, hour=0, minute=0):
    """That day and time on the Mac's clock, as UTC; a naive datetime takes the Mac's zone with its daylight saving on that day."""
    return datetime(day.year, day.month, day.day, hour, minute).astimezone(timezone.utc)


def reset_expiry(text, now):
    """When a limit reset row's `Expires ...` runs out, read best effort against `now`, when CodexBar wrote it; None when it cannot be read.

    The CLI writes it in en_US_POSIX on the Mac's clock (UsageFormatter.resetDescription): `6:40 PM` today, `tomorrow, 6:40 PM`, `Nov 6 at 6:40 PM` later, without a year.
    The day is today (a bare time or `today`), `tomorrow`, or the next English month and day, in either order, on or after today. The expiry is the written time on that day on the Mac's clock, or the start of that day when no time is written, except today, whose start has passed: today is unreadable without a time.
    """
    words = " ".join(text.replace(" ", " ").replace(" ", " ").split()).lower()
    words = words.removeprefix("expires ").strip()
    clock = None
    match = re.search(r"(?:^|[ ,])(?:at )?(\d{1,2}):(\d{2})(?: ?([ap])\.?m\.?)?$", words)
    if match:
        hour, minute, half = int(match[1]), int(match[2]), match[3]
        if half:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if half == "p" else 0)
        if hour > 23 or minute > 59:
            return None
        clock = (hour, minute)
        words = words[:match.start()].strip(" ,")
    today = now.astimezone().date()
    if words in ("", "today"):
        day = today
    elif words == "tomorrow":
        day = today + timedelta(days=1)
    else:
        parts = re.fullmatch(r"([a-z]+)\.? (\d{1,2})|(\d{1,2})\.? ([a-z]+)\.?", words)
        month = parts and MONTHS.get(parts[1] or parts[4])
        if not month:
            return None
        number_of_day = int(parts[2] or parts[3])
        day = None
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, number_of_day)
            except ValueError:
                continue
            if candidate >= today:
                day = candidate
                break
        if day is None:
            return None
    if clock:
        return local_time(day, *clock)
    return None if day == today else local_time(day)


def credits(usage, now):
    """The provider's credits still usable at `now`, from CodexBar's three credit sources; nothing else in the record is read.

    Codex's `codexResetCredits` counts credits `available` and not expired, CodexBar's own inventory rule; Claude's cloud credits row (`claude-cloud-credits`) is read as CodexBar's `detailStatus` reads it back, its balance in US dollars; Claude's and Grok's `Limit Reset Credits` rows give a count and only the soonest expiry. A source that is present but cannot be read gives an unreadable entry, never nothing. Unreadable entries come first, then the soonest expiry, then none.
    """
    found = []  # (expiry, entry)

    def add(kind, expiry, unreadable=False, **values):
        entry = {"kind": kind, **values, "expiresAt": expiry.isoformat() if expiry else None}
        if unreadable:
            entry["unreadable"] = True
        found.append((expiry, entry))

    if usage.get("codexResetCredits") is not None:
        block = usage["codexResetCredits"]
        items = block.get("credits") if isinstance(block, dict) else None
        if not isinstance(items, list) or not all(isinstance(item, dict) and isinstance(item.get("status"), str) for item in items):
            add("reset", None, unreadable=True)
        else:
            counts, unknown = {}, 0
            for item in items:
                if item["status"] != "available":
                    continue
                raw = item.get("expires_at")
                expiry = instant(raw)
                if raw is not None and expiry is None:
                    unknown += 1
                elif expiry is None or expiry > now:
                    counts[expiry] = counts.get(expiry, 0) + 1
            for expiry, count in counts.items():
                add("reset", expiry, count=count)
            if unknown:
                add("reset", None, unreadable=True, count=unknown)

    # CodexBar words a limit reset's expiry against the record's updatedAt, so a poll across midnight reads today and tomorrow as it meant them.
    written = instant(usage.get("updatedAt")) or now
    sections = usage.get("details")
    rows = [row for section in (sections if isinstance(sections, list) else []) if isinstance(section, dict) and isinstance(section.get("rows"), list)
            for row in section["rows"] if isinstance(row, dict)]
    for row in rows:
        secondary = row.get("secondaryValue")
        if row.get("id") == CLOUD_ROW:
            expiry = instant(secondary.split(" ")[-1]) if isinstance(secondary, str) else None
            amount = number(row.get("usageValue"))
            if row.get("value") == "Expired" or (expiry and expiry <= now) or (row.get("usageValue") is None and row.get("value") == "Unavailable"):
                continue
            if amount is None or not math.isfinite(amount) or amount < 0:
                add("cloud", None, unreadable=True)
            elif amount > 0:
                add("cloud", expiry, unreadable=secondary is not None and expiry is None, amount=amount, currency="USD")
        elif row.get("label") == RESET_LABEL:
            value = row.get("value")
            match = re.fullmatch(r"(\d+) available", value) if isinstance(value, str) else None
            if not match:
                add("reset", None, unreadable=True)
                continue
            count = int(match[1])
            expiry = reset_expiry(secondary, written) if isinstance(secondary, str) else None
            if count == 0 or (expiry and expiry <= now):
                continue
            add("reset", expiry, unreadable=secondary is not None and expiry is None, count=count)

    found.sort(key=lambda item: ("unreadable" not in item[1], item[0] is None, item[0] or now))
    return [entry for _, entry in found]


def normalize(raw, names=None, now=None, plans=None):
    """The snapshot of CodexBar's output; `plans` names a provider's plan when its record has none (`source_plans`)."""
    if not isinstance(raw, list):
        raise TypeError("CodexBar output must be an array")
    names, plans = names or {}, plans or {}
    # One instant for updatedAt and every run-out, so a reader can tell how old the estimate is.
    now = now or datetime.now(timezone.utc)
    providers = {}
    for record in raw:
        if not isinstance(record, dict) or not isinstance(record.get("provider"), str):
            continue
        provider = record["provider"]
        if provider not in SUPPORTED:
            continue
        usage = record.get("usage")
        if not isinstance(usage, dict):
            # CodexBar lists only enabled providers; one it could not read is kept as failed, without its error text.
            if record.get("error"):
                providers.setdefault(provider, {"name": names.get(provider) or provider, "plan": plan_name(provider, None, names.get(provider)), "pools": {}, "failed": True})
            continue
        pools, models = {}, {}
        extras = usage.get("extraRateWindows")
        for entry in extras if isinstance(extras, list) else []:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id") if isinstance(entry.get("id"), str) else None
            # Antigravity's summary windows make its pools; every other extra window applies to one model only, but the ones CodexBar uses for something else.
            pool = AGY_POOLS.get(entry_id) if provider == "antigravity" else None
            other = entry_id is not None and (entry_id in NOT_MODEL_WINDOWS or entry_id.startswith(NOT_MODEL_PREFIXES))
            name = None if pool or other else model_name(entry.get("title"), entry_id)
            item = window(entry.get("window"), known=entry.get("usageKnown") is not False, now=now) if pool or name else None
            if item:
                (pools.setdefault(pool, []) if pool else models.setdefault(name, [])).append(item)
        if provider != "antigravity":
            pace = record.get("pace") if isinstance(record.get("pace"), dict) else {}
            for slot in SLOTS:
                item = window(usage.get(slot), pace.get(slot), default_minutes=DEFAULT_MINUTES.get(provider), now=now)
                if item:
                    pools.setdefault("", []).append(item)
        for items in (*pools.values(), *models.values()):
            items.sort(key=lambda item: item["minutes"] or float("inf"))
        providers[provider] = {
            "name": names.get(provider) or provider,
            "plan": plan_name(provider, usage.get("loginMethod") if login(usage) else plans.get(provider), names.get(provider)),
            "pools": pools,
        }
        if models:
            providers[provider]["models"] = models
        usable = credits(usage, now)
        if usable:
            providers[provider]["credits"] = usable
    return {"updatedAt": now.isoformat(), "providers": providers}


def poll(runner=subprocess.run):
    raw = run_json(["usage", "--provider", "", "--json"], runner)
    # CodexBar counts etaSeconds from its answer, so the snapshot is dated then, not after the names below.
    now = datetime.now(timezone.utc)
    try:
        names = {entry["provider"]: entry.get("displayName") for entry in run_json(["config", "providers", "--json"], runner)}
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        names = {}
    snapshot = normalize(raw, names, now, source_plans(raw, now, runner))
    if not any(provider["pools"] for provider in snapshot["providers"].values()):
        raise ValueError("CodexBar returned no quota windows; the previous snapshot is kept")
    write_json(SNAPSHOT, snapshot)
    return snapshot


def source_plans(raw, now, runner=subprocess.run):
    """Plans for the providers in PLAN_SOURCES that CodexBar read without one, from that source, read at most once per PLAN_EVERY and kept in PLANS.

    A read that fails or names no plan keeps the last plan read, else none; one that names only another account's plan than the configured source read clears it.
    Nothing else from that answer is kept or printed: it carries the account's email and identity, which are only compared in memory.
    """
    wanted = {record["provider"]: account(record["usage"]) for record in (raw if isinstance(raw, list) else []) if isinstance(record, dict) and isinstance(record.get("provider"), str)
              and record["provider"] in PLAN_SOURCES and isinstance(record.get("usage"), dict) and not login(record["usage"])}
    if not wanted:
        return {}
    try:
        cached = json.loads(PLANS.read_text())
    except (OSError, ValueError):
        cached = {}
    kept = {}
    for provider in PLAN_SOURCES:
        entry = cached.get(provider) if isinstance(cached, dict) else None
        if isinstance(entry, dict) and instant(entry.get("checkedAt")):
            kept[provider] = {"plan": entry.get("plan") if isinstance(entry.get("plan"), str) and entry.get("plan") else None, "checkedAt": entry["checkedAt"]}
    changed = False
    for provider in wanted:
        entry = kept.get(provider, {"plan": None, "checkedAt": None})
        checked = instant(entry["checkedAt"])
        if checked is None or not 0 <= (now - checked).total_seconds() < PLAN_EVERY:
            plan = entry["plan"]
            try:
                answer = run_json(["usage", "--provider", provider, "--json", "--source", PLAN_SOURCES[provider]], runner)
                named = [record["usage"] for record in answer if isinstance(record, dict) and record.get("provider") == provider and isinstance(record.get("usage"), dict) and login(record["usage"])]
                # CodexBar's configured source can read another Google account than the one added to CodexBar; that account's plan is not this one's.
                mine = [usage for usage in named if not (wanted[provider] and account(usage)) or account(usage) == wanted[provider]]
                plan = login(mine[0]) if mine else None if named else plan
            except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                pass
            kept[provider], changed = {"plan": plan, "checkedAt": now.isoformat()}, True
    if changed:
        try:
            write_json(PLANS, kept)
        except OSError:
            pass
    return {provider: kept[provider]["plan"] for provider in wanted if kept.get(provider, {}).get("plan")}


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
