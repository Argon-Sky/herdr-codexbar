"""Subscription quota from CodexBar in Herdr's agent sidebar."""

import os
from pathlib import Path

__version__ = "0.1.0"

ISSUES_URL = "https://github.com/Argon-Sky/herdr-codexbar/issues"
# Private runtime state: the quota snapshot and pane registrations.
STATE_DIR = Path(os.environ.get("HERDR_CODEXBAR_STATE", Path.home() / ".cache/herdr-codexbar"))
