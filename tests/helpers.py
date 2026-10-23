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
    """Records subprocess calls and answers `pane list` from a pane -> agent map; `details` adds fields such as titles to a pane."""

    def __init__(self, agents=None, socket="/tmp/herdr.sock"):
        self.calls = []
        self.agents = agents or {}
        self.sessions = {}
        self.details = {}
        self.socket = socket

    def __call__(self, args, **kwargs):
        self.calls.append(args)

        def pane(pane_id, agent):
            data = {"pane_id": pane_id, "agent": agent, **self.details.get(pane_id, {})}
            if pane_id in self.sessions:
                data["agent_session"] = {"kind": "id", "value": self.sessions[pane_id]}
            return data

        if args[1:3] == ["session", "list"]:
            output = {"sessions": [{"name": "default", "running": True, "socket_path": self.socket}, {"name": "old", "running": False, "socket_path": "/tmp/stopped.sock"}]}
        elif args[1:3] == ["pane", "get"]:
            output = {"result": {"pane": pane(args[3], self.agents.get(args[3]))}}
        else:
            output = {"result": {"panes": [pane(pane_id, agent) for pane_id, agent in self.agents.items()]}}

        class Result:
            returncode = 0
            stdout = json.dumps(output)
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
