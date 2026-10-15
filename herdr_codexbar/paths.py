"""Resolve agent state locations shared by setup, diagnostics and hooks."""

import os
from pathlib import Path


def codex_home(home=None, env=os.environ):
    """Codex's active state root; launchers can isolate it with CODEX_HOME."""
    return Path(env["CODEX_HOME"]).expanduser() if env.get("CODEX_HOME") else (home or Path.home()) / ".codex"
