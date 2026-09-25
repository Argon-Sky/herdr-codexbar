"""Turn each harness's hook or status-line payload into a report.

A report is a dict with `harness`, `provider_id`, `model`, `effort`, and the
context figures `context_used`, `context_limit` and `context_percent`. Values
come only from the harness itself, never from quota data.
"""

import json
import os
import tomllib
from numbers import Real
from pathlib import Path

# Codex's footer excludes this fixed prompt overhead from "Context N% used"; mirror it.
CODEX_BASELINE_TOKENS = 12_000
CHUNK = 256 * 1024


def number(value):
    return value if isinstance(value, Real) and not isinstance(value, bool) and value >= 0 else None


def claude(payload):
    """Claude Code `statusLine` JSON."""
    context = payload.get("context_window") or {}
    usage = context.get("current_usage") or {}
    parts = [number(usage.get(key)) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
    return {
        "harness": "claude",
        "provider_id": "anthropic",
        "model": (payload.get("model") or {}).get("display_name"),
        "effort": (payload.get("effort") or {}).get("level"),
        "context_used": sum(parts) if None not in parts else None,
        "context_limit": number(context.get("context_window_size")),
        "context_percent": number(context.get("used_percentage")),
    }


def nominal_window(size):
    """Antigravity reports a nominal 1M window as ~1 MiB; count within 10k of N MiB as N million."""
    mebibytes = round(size / 1_048_576)
    return mebibytes * 1_000_000 if mebibytes and abs(size - mebibytes * 1_048_576) < 10_000 else size


def antigravity(payload):
    """Antigravity CLI `statusLine` JSON."""
    context = payload.get("context_window") or {}
    model = payload.get("model") or {}
    used, size = number(context.get("total_input_tokens")), number(context.get("context_window_size"))
    percent = used / nominal_window(size) * 100 if used is not None and size else number(context.get("used_percentage"))
    return {
        "harness": "antigravity",
        "provider_id": "antigravity",
        "model": model.get("display_name") or model.get("id"),
        "effort": None,
        "context_used": used,
        "context_limit": size,
        "context_percent": percent,
    }


def codex_transcript(path):
    """Session provider, the newest turn_context, and the newest non-empty token_count info."""
    provider = turn = usage = None
    try:
        with open(path, "rb") as source:
            first = json.loads(source.readline() or b"{}")
            if first.get("type") == "session_meta":
                provider = (first.get("payload") or {}).get("model_provider")
            end = source.seek(0, os.SEEK_END)
            tail = b""
            while end > 0 and (turn is None or usage is None):
                start = max(0, end - CHUNK)
                source.seek(start)
                lines = (source.read(end - start) + tail).split(b"\n")
                # The first line may be cut mid-record; keep it for the next chunk.
                tail, lines = (lines[0], lines[1:]) if start else (b"", lines)
                for line in reversed(lines):
                    if (turn is None and b'"turn_context"' in line) or (usage is None and b'"token_count"' in line):
                        try:
                            record = json.loads(line)
                        except ValueError:
                            continue
                        payload = record.get("payload") or {}
                        if turn is None and record.get("type") == "turn_context":
                            turn = payload
                        elif usage is None and payload.get("type") == "token_count" and payload.get("info"):
                            usage = payload["info"]
                end = start
    except (OSError, TypeError, ValueError, AttributeError):
        pass
    return provider, turn or {}, usage or {}


def codex_effort(home):
    """The reasoning effort configured for Codex, used when the transcript has none."""
    try:
        with (home / ".codex/config.toml").open("rb") as source:
            return tomllib.load(source).get("model_reasoning_effort")
    except (OSError, ValueError):
        return None


def codex(payload, home=None):
    """Codex hook payload; model and context come from the session transcript it points to."""
    provider, turn, usage = codex_transcript(payload.get("transcript_path"))
    tokens = number((usage.get("last_token_usage") or {}).get("total_tokens"))
    window = number(usage.get("model_context_window"))
    percent = None
    if tokens is not None and window:
        effective = window - CODEX_BASELINE_TOKENS
        percent = 100 if effective <= 0 else min(100, max(0, tokens - CODEX_BASELINE_TOKENS) / effective * 100)
    return {
        "harness": "codex",
        "provider_id": provider or "openai",
        "model": turn.get("model") or payload.get("model"),
        "effort": turn.get("effort") or codex_effort(home or Path.home()),
        "context_used": tokens,
        "context_limit": window,
        "context_percent": percent,
    }


PARSERS = {"claude": claude, "antigravity": antigravity, "codex": codex}
