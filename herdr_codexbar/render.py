"""Text for the Herdr tab bar and the sidebar quota rows."""

from datetime import datetime, timezone

BAR_CELLS = 12
# Fira Code 6+ progress-bar glyphs: left cap, middle and right cap, empty then filled.
EMPTY = ("", "", "")
FILLED = ("", "", "")
PACE_WIDTH = 16  # "□ 99% in deficit"
# Herdr trims whitespace around token values; the blank Braille pattern survives and pads columns.
BLANK = "\u2800"
# Short tab-bar names, in tab-bar order.
SHORT_NAMES = {"claude": "CC", "codex": "GPT", "antigravity": "Agy", "opencodego": "OC", "commandcode": "CMD"}
POOL_PREFIXES = {"gemini": "", "claude-gpt": "3p "}


def parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def time_left(reset, now=None):
    reset_at = parse_time(reset)
    if reset_at is None:
        return None
    seconds = int((reset_at - (now or datetime.now(timezone.utc))).total_seconds())
    if seconds < 0:
        return None
    if seconds < 60:
        return "<1m"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {rest // 60}m"
    return f"{rest // 60}m"


def percent_left(window):
    return round(max(0.0, min(100.0, 100 - window["used"])))


def progress_bar(left):
    filled = BAR_CELLS if left >= 100 else left * BAR_CELLS // 100  # full only at 100%
    cells = []
    for index in range(BAR_CELLS):
        glyphs = FILLED if index < filled else EMPTY
        cells.append(glyphs[0] if index == 0 else glyphs[2] if index == BAR_CELLS - 1 else glyphs[1])
    return "".join(cells)


def started(window):
    return window["resetsAt"] is not None


def pace_delta(window, now=None):
    """Percentage points ahead of an even burn: CodexBar's own pace, else derived from the schedule."""
    if not window["known"] or not started(window):
        return None
    if window["pace"] is not None:
        return window["pace"]
    reset_at = parse_time(window["resetsAt"])
    if not window["minutes"] or reset_at is None:
        return None
    duration = window["minutes"] * 60
    elapsed = duration - (reset_at - (now or datetime.now(timezone.utc))).total_seconds()
    if not 0 <= elapsed <= duration:
        return None
    return window["used"] - elapsed / duration * 100


def pace_state(delta):
    """`reserve`, `pace` or `deficit`; None without a pace."""
    if delta is None:
        return None
    amount = round(abs(delta))
    return "pace" if amount == 0 else "reserve" if delta < 0 else "deficit"


def pace_text(delta):
    state = pace_state(delta)
    if state is None:
        return ""
    amount = round(abs(delta))
    return {"pace": "◪ on pace", "reserve": f"■ {amount}% in reserve", "deficit": f"□ {amount}% in deficit"}[state]


def quota_parts(window, now=None):
    """The columns of one quota row, each padded to a fixed width: label, bar, left, pace, reset.

    Herdr colors each token as a whole and separates tokens with ` · `, so every
    column is its own token. `state` says which color the bar and pace take.
    """
    label = (window["label"] or "").rjust(3, BLANK)
    if not window["known"]:
        return {"label": label, "bar": None, "state": None, "left": "unknown", "pace": None, "reset": None}
    left = percent_left(window)
    delta = pace_delta(window, now)
    # An unused rolling window has not started its countdown yet; show its length instead.
    reset = (time_left(window["resetsAt"], now) or "") if started(window) else window["label"] or ""
    return {
        "label": label,
        "bar": progress_bar(left),
        "state": pace_state(delta),
        "left": f"{left}% left".rjust(9, BLANK),
        "pace": pace_text(delta).ljust(PACE_WIDTH, BLANK),
        "reset": f"↻ {reset:>7}" if reset else None,
    }


def tab_bar(snapshot):
    """`CC 98/100 · GPT 100/0 · Agy 100/100 3p 100/99 · OC 100/18/44`: percent left per window."""
    if not snapshot:
        return "[quota unavailable]"
    providers = snapshot["providers"]
    parts = []
    for name in (name for name in SHORT_NAMES if name in providers):
        pools = providers[name]["pools"]
        groups = [f"{POOL_PREFIXES.get(pool, '')}{'/'.join(str(percent_left(item)) if item['known'] else '-' for item in items)}"
                  for pool, items in pools.items()]
        parts.append(f"{SHORT_NAMES[name]} {' '.join(groups) or '?'}")
    return " · ".join(parts) or "[quota unavailable]"
