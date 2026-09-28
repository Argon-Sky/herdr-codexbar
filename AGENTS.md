# herdr-codexbar

A Herdr add-on that shows, under each agent in the sidebar, which subscription it is using and how much quota is left. Quota comes from the CodexBar CLI; model, effort and context come from each agent's own hook, status line or plugin.

## Layout

- `herdr_codexbar/cli.py`: the command line. `check`, `setup` and `uninstall` are for users; `refresh`, `hook`, `report` and `clear` are called by Herdr, the agents and the poller.
- `herdr_codexbar/install.py`: `check`, `setup` and `uninstall`. Wires each installed agent, Herdr's config and the launchd poller.
- `herdr_codexbar/harnesses.py`: turns each agent's hook or status-line payload into a report.
- `herdr_codexbar/panes.py`: routes each pane to a subscription by provider ID and publishes its sidebar tokens to Herdr.
- `herdr_codexbar/codexbar.py`: reads quota from the CodexBar CLI into a small snapshot.
- `herdr_codexbar/render.py`: text for the sidebar rows.
- `herdr_codexbar/tomledit.py`: minimal edits to Herdr's `config.toml`.
- `herdr_codexbar/agents/`: plugins that `setup` installs into OpenCode, Kilo CLI, Command Code and the Pi family.
- `tests/`: Python tests (`test_*.py`) and plugin tests (`*.test.js`, `*.test.ts`).
- `assets/`: the README logo and screenshot.

## Develop and test

```sh
bin/herdr-codexbar check        # runs from the checkout
python3 -m unittest discover -s tests -t .
node --test tests/*.test.js tests/*.test.ts
```

CI runs both suites on macOS with Python 3.11 and 3.13 and Node 24. Run both before every commit.

## Rules

- Python 3.11 or newer, standard library only. No third-party dependencies.
- Privacy: never store or log account identifiers, emails or raw CodexBar output. The snapshot keeps only windows, plan names and pace.
- Commands called by Herdr, agents or the poller stay quiet. A failing hook must never disturb the agent that runs it.
- `setup` plans every change first, so `setup --dry-run` shows the exact diff. It backs up files before changing them, never replaces settings it did not write, and `uninstall` undoes it. Any new wiring (agent settings, hooks, plugins, the poller) goes through `setup`, not through manual steps in the README.
- Don't hardcode paths from one machine. Resolve binaries and interpreters at run or install time.
- The README and CLI text are written for users. No maintainer notes, status updates or hedges about future demand.
- Keep one opinionated default. Don't add options, fallbacks or alternative layouts until someone asks for them in an issue.
- No hard wrapping in code comments, docs or commit messages. One logical line stays one line.

## Release

1. Bump `__version__` in `herdr_codexbar/__init__.py`, commit and push to `main`.
2. Tag `vX.Y.Z`, push the tag and publish a GitHub release.
3. In [Argon-Sky/homebrew-tap](https://github.com/Argon-Sky/homebrew-tap), point `Formula/herdr-codexbar.rb` at `https://github.com/Argon-Sky/herdr-codexbar/archive/refs/tags/vX.Y.Z.tar.gz` and set `sha256` to that tarball's hash (`curl -sL <url> | shasum -a 256`).
4. `brew upgrade herdr-codexbar && herdr-codexbar check` to confirm.
