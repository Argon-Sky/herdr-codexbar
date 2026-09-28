# herdr-codexbar

Subscription quota for your coding agents, right where you run them. herdr-codexbar puts [CodexBar](https://github.com/steipete/CodexBar)'s usage data into [Herdr](https://herdr.dev): under each agent in the sidebar, the plan it is billing, its model and context, and how much of each quota window is left.

<p align="center"><img src="docs/sidebar.png" width="600" alt="Herdr sidebar with six agents: each shows its subscription plan, model, effort and context, and a colored bar per quota window with the percent left, whether usage is in reserve, on pace or in deficit, and the time to reset."></p>

## Why this one

- **It never touches your credentials.** CodexBar already signs in to your providers and reads their quota. herdr-codexbar only asks the CodexBar CLI for the numbers, so there are no tokens, cookies or API keys to hand over.
- **Quota follows the subscription, not the agent.** Each pane shows the quota of the provider it is talking to right now. OpenCode switching from OpenCode Go to a Command Code model moves the pane to Command Code's quota.
- **Antigravity's two pools.** Gemini models and third-party models (Claude, GPT) have separate quotas in Antigravity. The pane shows the pool of the model it is using.
- **Pace, not just percent.** Every window says whether you are ahead of an even burn (■ in reserve), on pace (◪) or behind (□ in deficit), and when it resets.
- **A setup you can review and undo.** `setup --dry-run` shows the exact diff, every edited file is backed up, and `uninstall` puts things back.

## Requirements

- macOS 14 or newer.
- [Herdr](https://herdr.dev) 0.9.1 or newer: `brew install herdr`. Install Herdr's integration for each agent you use, for example `herdr integration install claude`.
- [CodexBar](https://github.com/steipete/CodexBar): `brew install --cask codexbar`. Open it once, sign in to your providers and turn on the ones you want in its settings. The CodexBar CLI (Preferences → Advanced → Install CLI) is optional: herdr-codexbar falls back to the CLI inside the app.
- [Fira Code](https://github.com/tonsky/FiraCode) 6 or newer as your terminal font, for the progress bars: `brew install --cask font-fira-code`. Any [Nerd Font](https://www.nerdfonts.com) 3 or newer works too.
- One or more supported agents:

| Agent | How it reports | Quota it shows |
| --- | --- | --- |
| [Claude Code](https://claude.com/claude-code) | status-line command | Claude |
| [Codex](https://github.com/openai/codex) | hooks (turn on `hooks = true` under `[features]` in `~/.codex/config.toml`) | ChatGPT plan |
| [OpenCode](https://opencode.ai) | TUI plugin | follows the selected model's provider |
| [Antigravity CLI](https://antigravity.google) | status-line command | Google AI plan, Gemini or Claude & GPT pool |
| [Command Code](https://commandcode.ai) | mod | Command Code plan |
| [GitHub Copilot CLI](https://github.com/features/copilot/cli) | status-line command | Copilot plan, monthly premium requests |
| [Grok Build](https://x.ai/cli) | status-line command (`[ui.status_line]` in `~/.grok/config.toml`) | Grok plan |
| [Pi](https://github.com/earendil-works/pi) | extension | follows the selected model's provider |
| [Kilo CLI](https://github.com/Kilo-Org/kilocode) | TUI plugin | follows the model of the newest message |

The [compatibility matrix](docs/compatibility.md) covers every harness and subscription we know of: what works, what each harness can bill, and what is planned.

## Install

```sh
brew install argon-sky/tap/herdr-codexbar
herdr-codexbar check            # prerequisites, and what setup would change
herdr-codexbar setup --dry-run  # the exact diff, nothing written
herdr-codexbar setup
```

`setup` wires each agent it finds, adds the sidebar rows to `~/.config/herdr/config.toml`, and starts the poller with `brew services`. Restart running agents afterwards; Codex asks you to approve its new hooks on the first start.

It changes only what it needs: comments and other settings stay as they are, and every file it edits is backed up first to `~/.cache/herdr-codexbar/backups`. If an agent already has a status line from another tool, `setup` stops and tells you; `setup --force` replaces it.

## How provider routing works

Each agent reports the provider ID it is using. herdr-codexbar maps that ID to a CodexBar provider:

| Provider ID | CodexBar quota |
| --- | --- |
| `anthropic` | Claude |
| `openai`, `openai-codex` | Codex |
| `antigravity` | Antigravity, pool by model |
| `opencode-go` | OpenCode Go |
| `commandcode` | Command Code |
| `github-copilot` | Copilot, monthly premium requests |
| `grok`, `xai` | Grok |

Other providers, such as OpenCode Zen, have no quota in CodexBar, so the pane shows its model and context only. In OpenCode, Kilo CLI and Pi, a custom provider shows a subscription's quota when you name it after the CodexBar provider, for example `commandcode` for a Command Code plan used through its OpenAI-compatible API.

## Privacy

- Everything stays on your Mac. herdr-codexbar makes no network requests; CodexBar does the fetching.
- It keeps a small snapshot in `~/.cache/herdr-codexbar` (readable only by you) with plan names, percentages and reset times. Account emails, organizations and raw CodexBar output are never stored or logged.
- It reads agent settings to wire them, and each session's own status-line or hook data (model, effort, context) to display it.

## Uninstall

```sh
herdr-codexbar uninstall   # also takes --dry-run
brew uninstall herdr-codexbar
```

`uninstall` removes the wiring, restores the sidebar rows you had before `setup`, stops the poller and clears the rows from open panes.

## Troubleshooting

Run `herdr-codexbar check` first. It shows what is missing and how to fix it. The poller's own error is in `herdr-codexbar refresh`, and `brew services info herdr-codexbar` shows whether it runs.

- **Bars show as boxes or question marks:** your terminal font is not Fira Code 6+ or a Nerd Font 3+.
- **Rows are cut off:** the sidebar needs 65 columns. `setup` sets it to 70 when you have not set it, and `check` warns when your own width is narrower.
- **An agent shows no rows:** your `[ui.sidebar.agents.rows_by_agent]` has its own layout for that agent, which Herdr uses instead of ours. `check` tells you which.

Still stuck? [Open an issue](https://github.com/Argon-Sky/herdr-codexbar/issues) with the output of `herdr-codexbar check`.

## Roadmap

Ideas, not promises. Upvote or comment on the [roadmap issues](https://github.com/Argon-Sky/herdr-codexbar/issues?q=is%3Aissue+label%3Aroadmap) to move them up.

- Linux, once CodexBar's CLI runs there.
- More agents, next up Oh My Pi, Cline CLI and Droid. The [compatibility matrix](docs/compatibility.md) lists every harness and subscription with its status.
- Session tokens and API-equivalent cost.
- Quota for API and credit billing.
- A compact layout for narrow sidebars, if people ask for it.

## Development

```sh
bin/herdr-codexbar check        # runs from the checkout
python3 -m unittest discover -s tests -t .
node --test tests/*.test.js tests/*.test.ts
```

## License

[MIT](LICENSE) © Argon Sky. Not affiliated with Herdr, CodexBar or any provider.
