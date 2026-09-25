import json
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def snapshot():
    from herdr_codexbar import codexbar
    names = {entry["provider"]: entry["displayName"] for entry in fixture("codexbar-providers.json")}
    return codexbar.normalize(fixture("codexbar-usage.json"), names, NOW)


class Runner:
    """Records subprocess calls and answers `pane list` from a pane -> agent map."""

    def __init__(self, agents=None):
        self.calls = []
        self.agents = agents or {}

    def __call__(self, args, **kwargs):
        self.calls.append(args)

        class Result:
            returncode = 0
            stdout = json.dumps({"result": {"panes": [{"pane_id": pane, "agent": agent} for pane, agent in self.agents.items()]}})
        return Result()

    def tokens(self):
        """Every token update across the recorded report-metadata calls."""
        values = {}
        for args in self.calls:
            for index, arg in enumerate(args):
                if arg == "--token":
                    key, _, value = args[index + 1].partition("=")
                    values[key] = value
                elif arg == "--clear-token":
                    values[args[index + 1]] = None
        return values
