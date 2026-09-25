"""herdr-codexbar command line.

User commands: check, setup, uninstall. The rest are called by Herdr, the
agents and the poller, and are kept quiet: a failing hook must never disturb
the agent that runs it.
"""

import argparse
import json
import subprocess
import sys

from . import ISSUES_URL, __version__, codexbar, harnesses, install, panes, render

REPORT_KEYS = ("provider_id", "model", "effort", "context_used", "context_limit", "context_percent")


def read_stdin():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def hook(harness):
    """Status-line and hook entrypoint; always silent, always exits 0."""
    try:
        panes.report(harnesses.PARSERS[harness](read_stdin()))
    except Exception:  # noqa: BLE001 - never break the agent's status line or hook.
        pass
    return 0


def report():
    """Entrypoint for the OpenCode and Command Code plugins, which send a finished report."""
    data = read_stdin()
    if data.get("harness") not in panes.HARNESSES:
        return 2
    try:
        panes.report({"harness": data["harness"], **{key: data.get(key) for key in REPORT_KEYS}})
    except Exception:  # noqa: BLE001
        return 1
    return 0


def refresh():
    """Poll CodexBar and update every registered pane; run by the Homebrew service."""
    status = 0
    try:
        snapshot = codexbar.poll()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(f"herdr-codexbar: CodexBar poll failed: {error}", file=sys.stderr)
        snapshot, status = codexbar.read_snapshot(), 1
    if panes.refresh_panes(snapshot):
        status = 1
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(prog="herdr-codexbar", description="Subscription quota from CodexBar in Herdr's tab bar and agent sidebar.", epilog=f"Problems? {ISSUES_URL}")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser("check", help="check prerequisites and whether setup is current")
    setup = commands.add_parser("setup", help="wire your agents and Herdr, and start the poller")
    setup.add_argument("--dry-run", action="store_true", help="show the changes without writing them")
    setup.add_argument("--force", action="store_true", help="replace status lines set by other tools")
    uninstall = commands.add_parser("uninstall", help="undo setup")
    uninstall.add_argument("--dry-run", action="store_true", help="show the changes without writing them")
    commands.add_parser("refresh", help="poll CodexBar now and update agent panes")
    commands.add_parser("bar", help="print the tab-bar text")
    hook_parser = commands.add_parser("hook", help="agent status-line or hook entrypoint (reads JSON on stdin)")
    hook_parser.add_argument("harness", choices=sorted(harnesses.PARSERS))
    commands.add_parser("report", help="plugin entrypoint (reads a report as JSON on stdin)")
    args = parser.parse_args(argv)

    if args.command == "check":
        status = install.check()
    elif args.command == "setup":
        install.setup(args.dry_run, args.force)
        status = 0
    elif args.command == "uninstall":
        install.uninstall(args.dry_run)
        status = 0
    elif args.command == "refresh":
        status = refresh()
    elif args.command == "bar":
        print(render.tab_bar(codexbar.read_snapshot()))
        status = 0
    elif args.command == "hook":
        status = hook(args.harness)
    else:
        status = report()
    sys.exit(status)
