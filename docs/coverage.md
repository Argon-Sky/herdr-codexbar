# Coverage

Which subscriptions and coding agents (harnesses) herdr-codexbar works with. A pane shows a subscription's quota when the harness can use the subscription, [CodexBar](https://github.com/steipete/CodexBar) tracks it, and herdr-codexbar can read the harness's current model and provider.

Scope: coding harnesses you run in a terminal, and flat-rate subscriptions or token plans. Pay-as-you-go API billing is not covered.

Last reviewed: 2026-09-28.

## Legend

| Mark | Meaning |
| --- | --- |
| ✅ | Works in herdr-codexbar and tested |
| ● | Documented as supported by the subscription's provider or the harness; not tested here |
| ◐ | Documented for some of the plan's models only; not tested here |
| ○ | Should work through the harness's custom provider setting; not documented by the provider |
| ? | Not verified |
| ⚠ | Technically possible, but against the provider's terms; not supported |
| — | Not possible |

## Subscriptions

Tied subscriptions work only in their vendor's own harness. Portable ones give you a key or sign-in that other harnesses can use.

| Subscription | Price / month | Kind | Quota windows |
| --- | --- | --- | --- |
| Claude Pro | $20 | tied: Claude Code | 5h, weekly |
| ChatGPT Plus | $20 | portable: sign-in with ChatGPT | 5h, weekly |
| X Premium+ (or SuperGrok) | $30 for SuperGrok | portable: sign-in with xAI | weekly |
| Google AI Pro | $20 | tied: Antigravity CLI | per model pool |
| OpenCode Go | $10 | portable: API key | 5h, weekly, monthly |
| Command Code GOAT | $10 | portable: API key | 5h, weekly, monthly |
| GitHub Copilot Pro | $10 | portable: sign-in with GitHub | monthly premium requests |

Higher tiers (Claude Max, ChatGPT Pro, SuperGrok Heavy and similar) are the same subscriptions and should work the same way.

## Harnesses

| Harness | Command | Reads from | Notes |
| --- | --- | --- | --- |
| Claude Code | `claude` | status line | The subscription follows `ANTHROPIC_BASE_URL`. |
| Codex | `codex` | hooks | Needs `hooks = true` under `[features]` and `--no-daemon`; quota appears after the first message. |
| Grok Build | `grok` | status line | |
| Antigravity CLI | `agy` | status line | Shows the pool of the model in use: Gemini, or Claude & GPT. |
| OpenCode | `opencode` | TUI plugin | |
| Command Code | `cmd` | mod | Herdr does not detect it; herdr-codexbar reports the agent itself. |
| GitHub Copilot CLI | `copilot` | status line | Copilot CLI does not report reasoning effort. |
| Pi | `pi` | extension | |
| Oh My Pi | `omp` | extension | A model switch shows at the next turn. |
| Prime Agent | `prime-agent` | extension | Herdr does not detect it; herdr-codexbar reports the agent itself. |
| Kilo CLI | `kilo` | TUI plugin | Follows the model of the session's newest message. |

Gemini CLI is not covered: since June 18, 2026, Google AI Pro and Ultra users are moved to Antigravity CLI.

## Portable subscriptions × harnesses

| Harness | ChatGPT | xAI | OpenCode Go | Command Code | Copilot |
| --- | --- | --- | --- | --- | --- |
| Claude Code | — | — | ◐ | ○ | — |
| Codex | ✅ | ? | ◐ | ○ | — |
| Grok Build | — | ✅ | — | — | — |
| OpenCode | ✅ | ✅ | ✅ | ✅ | ● |
| Command Code | — | — | — | ✅ | — |
| GitHub Copilot CLI | — | ? | ○ | ○ | ✅ |
| Pi | ✅ | ✅ | ✅ | ○ | ✅ |
| Oh My Pi | ✅ | ✅ | ✅ | ○ | ✅ |
| Prime Agent | ✅ | ✅ | ✅ | ○ | ✅ |
| Kilo CLI | ✅ | ✅ | ✅ | ○ | ? |

Antigravity CLI takes no portable subscription.

Notes:

- Claude Code accepts only Anthropic-compatible endpoints, and Codex only the OpenAI Responses API.
- OpenCode Go serves each model family on one API only. Claude Code reaches the ones on its Anthropic endpoint (MiniMax and Qwen); Codex reaches the ones on its Responses endpoint (GPT Luna, Grok and Muse Spark). The rest (GLM, Kimi, DeepSeek and others) need a harness that speaks Chat Completions, such as OpenCode, Kilo CLI or the Pi family.
- Translating proxies such as Codex Router or LiteLLM, which put other APIs behind Claude Code or Codex, are not supported: the harness then reports the proxy, not the plan.
- OpenCode Go expects clients to send a session header and lists the ones it has validated, among them Claude Code, Codex, Pi and Kilo CLI. Other harnesses may be throttled.
- X Premium+ and SuperGrok work outside Grok Build through the xAI sign-in that OpenCode, Kilo CLI and the Pi family offer. An xAI API key uses the same provider ID, so it would show the subscription's quota too.
- In OpenCode, Kilo CLI and the Pi family, a custom provider shows a subscription's quota when you name it after the CodexBar provider, for example `commandcode` for Command Code's OpenAI-compatible API.
- Plans restrict use to coding tools; scripts and automations are not allowed on most of them.

## Tied subscriptions × harnesses

| Subscription | Works in | Elsewhere |
| --- | --- | --- |
| Claude Pro | Claude Code ✅ | ⚠ Anthropic allows the subscription only in its own apps. Harnesses that run the unmodified `claude` binary are fine; ones that sign in with a Claude account are not. |
| Google AI Pro | Antigravity CLI ✅ | ⚠ Google suspends accounts that use Antigravity through third-party tools. |

## Sources

- [CodexBar providers](https://github.com/steipete/CodexBar/blob/main/docs/providers.md)
- [Herdr agents](https://herdr.dev/docs/agents/) and [integrations](https://herdr.dev/docs/integrations/)
- [Claude Code: authentication and credential use](https://code.claude.com/docs/en/legal-and-compliance)
- [OpenCode Go: use outside OpenCode](https://opencode.ai/docs/go/)
- [Command Code Provider API](https://commandcode.ai/docs/provider)
- [GitHub Copilot now supports OpenCode](https://github.blog/changelog/2026-01-16-github-copilot-now-supports-opencode/)
- [Google Antigravity FAQ](https://antigravity.google/docs/faq/)
