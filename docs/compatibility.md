# Compatibility

Which coding agents (harnesses) herdr-codexbar works with, which subscriptions they can bill, and what is planned. herdr-codexbar shows a subscription's quota only when all three line up: the harness can use the subscription, [CodexBar](https://github.com/steipete/CodexBar) tracks it, and herdr-codexbar knows how to read the harness's current model and provider.

Scope: coding harnesses you run in a terminal, and flat-rate subscriptions or token plans. Pay-as-you-go API billing is on the [roadmap](../README.md#roadmap), not here.

Last reviewed: 2026-09-28.

## Legend

| Mark | Meaning |
| --- | --- |
| ✅ | Works in herdr-codexbar and tested |
| ● | Documented as supported by the subscription's provider or the harness |
| ◐ | Documented for some of the plan's models only |
| ○ | Should work through the harness's custom provider setting; not documented by the provider |
| ? | Not verified yet |
| ! | The provider documents problems with this harness |
| ⚠ | Technically possible, but against the provider's terms; never supported here |
| — | Not possible |

Status: **done** works today, **now** in progress, **next** planned and testable, **roadmap** wanted but blocked (usually on a subscription or on Herdr support).

## Subscriptions

Tied subscriptions work only in their vendor's own harness. Portable ones give you a key or sign-in that other harnesses can use.

| Subscription | Price / month | Kind | CodexBar | Status |
| --- | --- | --- | --- | --- |
| Claude Pro | $20 | tied: Claude Code | ✅ 5h, weekly | done |
| ChatGPT Plus | $20 | portable: sign-in with ChatGPT | ✅ 5h, weekly | done |
| Google AI Pro | $20 | tied: Antigravity CLI | ✅ per model pool | done |
| SuperGrok (or X Premium+) | $30 | portable: sign-in with xAI | ✅ weekly | done |
| OpenCode Go | $10 | portable: API key | ✅ 5h, weekly, monthly | done |
| Command Code GOAT | $10 | portable: API key | ✅ 5h, weekly, monthly | done |
| GitHub Copilot Pro | $10 | portable: sign-in with GitHub | ✅ monthly premium requests | done |
| ClinePass | $10 | portable: API key | ● 5h, weekly, monthly | roadmap |
| Kilo Pass | $19 | portable: API key (Kilo Gateway) | ○ plan and credits, no windows | roadmap |
| GLM Coding Plan Lite (Z.ai) | $18 | portable: API key | ● 5h, weekly | roadmap |
| Kimi Code | $19 | portable: API key | ● 5h, weekly | roadmap |
| MiniMax Token Plan Plus | $22 | portable: API key | ● 5h, weekly | roadmap |
| Qwen Cloud Token Plan | $6–10 | portable: API key | ● 5h, weekly | roadmap |
| Xiaomi MiMo Token Plan Lite | $6 | portable: API key | ● monthly tokens | roadmap |
| Mistral Pro | $14.99 | tied: Mistral Vibe | ● Vibe allowance | roadmap |
| Meta Muse Code | $5–15 | tied: Muse Code | ● | roadmap |
| Factory Pro | $20 | tied: Droid | ● | roadmap |
| Kiro Pro | $20 | tied: Kiro CLI | ● monthly credits | roadmap |
| Cursor Pro | $20 | tied: Cursor CLI | ● | roadmap |
| Augment Code Standard | $20 | tied: Auggie | ● credits | roadmap |
| Devin Pro | $20 | tied: Devin CLI | ● daily, weekly | roadmap |
| Qoder Pro | $20 | tied: Qoder CLI | ● credits | roadmap |

## Harnesses

"Herdr" is how Herdr 0.9.1 tracks the harness: **lifecycle** (hooks report working and idle), **session** (Herdr tracks the session), **detected** (recognized, lightly tested) or **—** (not detected; herdr-codexbar would have to report the agent itself, as it does for Command Code). "Reads from" is how herdr-codexbar learns the current model and provider.

| Harness | Herdr | Reads from | Status | Next step |
| --- | --- | --- | --- | --- |
| Claude Code | session | status line | done | Route Anthropic-compatible endpoints (OpenCode Go, Command Code) to their quota |
| Codex | session | hooks | done | Route custom model providers to their quota |
| Antigravity CLI | session | status line | done | — |
| OpenCode | lifecycle | TUI plugin | done | — |
| Command Code | — (self-reported) | mod | done | — |
| Copilot CLI | session | status line | done | Copilot shows no reasoning effort |
| Grok Build | session | status line | done | — |
| Pi | lifecycle | extension | done | Test Command Code |
| Kilo CLI | lifecycle | TUI plugin | done | Test Copilot, Command Code, and Kilo Pass once CodexBar tracks it |
| Oh My Pi | lifecycle | extension (Pi's) | done | Test Command Code; a model switch shows at the next turn |
| Prime Agent | — (self-reported) | extension (Pi's) | done | Test Command Code |
| Cline CLI | detected | hooks | next | Test ChatGPT, OpenCode Go, Command Code |
| Mastra Code | lifecycle | hooks | next | Test ChatGPT, OpenCode Go, Command Code |
| Qwen Code | session | hooks | next | Test OpenCode Go, Command Code |
| Droid | session | hooks | next | Test custom models with OpenCode Go, Command Code |
| Crush | — | ? | roadmap | Needs Herdr detection or self-reporting |
| jcode | — | ? | roadmap | Needs Herdr detection or self-reporting |
| Letta Code | session | ? | roadmap | Find a hook with the model |
| Maki | detected | Lua plugin | roadmap | Find a hook with the model |
| Reasonix | — | hooks | roadmap | Needs Herdr detection or self-reporting |
| Kimi Code | lifecycle | hooks | roadmap | Needs Kimi Code subscription |
| Qoder CLI | session | hooks | roadmap | Needs Qoder Pro |
| Mistral Vibe | — | ? | roadmap | Needs Mistral Pro and Herdr detection |
| Amp | detected | plugins | roadmap | ChatGPT only; Amp itself bills credits |
| Kiro CLI | detected | ? | roadmap | Needs Kiro Pro |
| Cursor CLI | session | ? | roadmap | Needs Cursor Pro |
| Devin CLI | session | ? | roadmap | Needs Devin Pro |
| Muse Code | detected | ? | roadmap | Needs Muse Code |
| Auggie (Augment) | — | ? | roadmap | Needs Augment Standard and Herdr detection |

## Portable subscriptions × harnesses

| Harness | ChatGPT | Copilot | Grok | OC Go | Cmd Code | ClinePass | Kilo Pass | GLM | Kimi | MiniMax | Qwen Cloud | MiMo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Code | — | — | — | ◐ | ○ | — | — | ● | ● | ● | ● | ● |
| Codex | ✅ | — | ? | ◐ | ○ | ? | ? | ? | ? | ? | ? | ? |
| OpenCode | ✅ | ● | ✅ | ✅ | ✅ | ○ | ○ | ● | ● | ○ | ○ | ● |
| Kilo CLI | ✅ | ? | ✅ | ✅ | ○ | ○ | ● | ○ | ○ | ○ | ○ | ● |
| Pi | ✅ | ✅ | ✅ | ✅ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Oh My Pi | ✅ | ✅ | ✅ | ✅ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Prime Agent | ✅ | ✅ | ✅ | ✅ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Cline CLI | ● | — | ? | ○ | ○ | ● | ○ | ● | ○ | ○ | ○ | ● |
| Mastra Code | ● | ? | ? | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Qwen Code | — | — | ? | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ● | ○ |
| Droid | ? | — | ? | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Crush | ● | ● | ? | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| jcode | ● | ● | ? | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Letta Code | ● | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Maki | ? | — | ? | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Reasonix | — | — | ? | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Kimi Code | — | — | ? | ! | ○ | ○ | ○ | ○ | ● | ○ | ○ | ○ |
| Copilot CLI | — | ✅ | ? | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Qoder CLI | — | — | ? | ? | ? | ? | ? | ? | ? | ? | ● | ? |
| Mistral Vibe | — | — | ? | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| Amp | ● | — | — | — | — | — | — | — | — | — | — | — |
| Grok Build | — | — | ✅ | — | — | — | — | — | — | — | — | — |

Antigravity CLI, Command Code, Kiro CLI, Cursor CLI, Devin CLI, Muse Code and Auggie take no portable subscription: every cell would be —.

Notes:

- Claude Code accepts only Anthropic-compatible endpoints, so OpenAI-only plans (ClinePass, Kilo Pass) are out. Codex accepts only the OpenAI Responses API, which several plans do not document; those cells are `?`.
- OpenCode Go serves each model family on one API only. Claude Code reaches the ones on its Anthropic endpoint (MiniMax and Qwen); Codex reaches the ones on its Responses endpoint (GPT Luna, Grok and Muse Spark). The rest (GLM, Kimi, DeepSeek and others) need a harness that speaks Chat Completions.
- Translating proxies such as Codex Router or LiteLLM, which put other APIs behind Claude Code or Codex, are not supported: the harness then reports the proxy, not the plan.
- OpenCode Go expects clients to send a session header and lists the ones it has validated (Claude Code, Codex, Pi, jcode, Kilo CLI). Other harnesses may be throttled, and it flags Kimi Code as problematic.
- SuperGrok works outside Grok Build through the xAI sign-in that Pi and Kilo CLI offer. An xAI API key uses the same provider ID, so it would show the subscription's quota too.
- Plans restrict use to coding tools; scripts and automations are not allowed on most of them.

## Tied subscriptions × harnesses

| Subscription | Works in | Elsewhere |
| --- | --- | --- |
| Claude Pro | Claude Code ✅ | ⚠ Anthropic allows the subscription only in its own apps. Harnesses that run the unmodified `claude` binary are fine; ones that sign in with a Claude account are not. |
| Google AI Pro | Antigravity CLI ✅ | ⚠ Google suspends accounts that use Antigravity through third-party tools. |
| Mistral Pro | Mistral Vibe ● | — |
| Meta Muse Code | Muse Code ● | — |
| Factory Pro | Droid ● | — |
| Kiro Pro | Kiro CLI ● | — |
| Cursor Pro | Cursor CLI ● | — |
| Augment Code Standard | Auggie ● | — |
| Devin Pro | Devin CLI ● | — |
| Qoder Pro | Qoder CLI ● | — |

## Known, not planned

- **General-purpose agents**, not coding harnesses: OpenClaw, Hermes Agent, Goose.
- **Discontinued for individuals**: Gemini CLI. Since June 18, 2026, Google AI Pro and Ultra users are moved to Antigravity CLI.
- **Not a terminal harness**: OpenHands (web platform), IDE agents such as Roo Code, Trae, Windsurf and Zed.
- **Usage billing only**: Snowflake Cortex Code (Snowflake credits), Amp's own credits, and every pay-as-you-go API.
- **Higher tiers** (Claude Max, ChatGPT Pro, SuperGrok Heavy and similar) are the same subscriptions as their lowest tier here and should work the same way.

## Adding a harness

1. Check it is a coding harness you run in a terminal, and note its subscriptions.
2. Check Herdr's support (Herdr's agents docs). Without detection, herdr-codexbar has to report the agent itself.
3. Find where it exposes the current model, provider and context: a status line, hooks, or a plugin or extension API. That decides the integration.
4. Map its provider IDs to CodexBar providers, and add its row to the tables above.
5. Implement, test live with at least one subscription, and set its status to done.

## Adding a subscription

1. Check CodexBar tracks it, and which windows (5h, weekly, monthly, credits). Without CodexBar support, it waits on CodexBar.
2. Classify it: tied to one harness, or portable. For portable ones, note the endpoints (OpenAI chat, OpenAI Responses, Anthropic) and the tools the provider documents.
3. Add the provider ID mapping and plan name handling.
4. Fill its column: ● where documented, ○ where a harness takes custom providers, ⚠ where the terms forbid it.
5. Test live in at least one harness and set its status to done.

## Sources

- [CodexBar providers](https://github.com/steipete/CodexBar/blob/main/docs/providers.md)
- [Herdr agents](https://herdr.dev/docs/agents/) and [integrations](https://herdr.dev/docs/integrations/)
- [Claude Code: authentication and credential use](https://code.claude.com/docs/en/legal-and-compliance)
- [OpenCode Go: use outside OpenCode](https://opencode.ai/docs/go/)
- [Command Code Provider API](https://commandcode.ai/docs/provider)
- [GitHub Copilot now supports OpenCode](https://github.blog/changelog/2026-01-16-github-copilot-now-supports-opencode/)
- [ClinePass](https://docs.cline.bot/getting-started/clinepass)
- [Kilo Pass](https://kilo.ai/pricing/kilo-pass)
- [GLM Coding Plan](https://docs.z.ai/devpack/overview)
- [Kimi Code membership](https://www.kimi.com/en/help/kimi-code/membership-guide)
- [MiniMax Token Plan](https://platform.minimax.io/docs/token-plan/intro)
- [Qwen Cloud Token Plan](https://docs.qwencloud.com/token-plan/personal/token-plan-personal-overview)
- [Xiaomi MiMo Token Plan](https://mimo.mi.com/docs/en-US/news/latest/token-plan-release)
- [Mistral Vibe](https://mistral.ai/products/vibe/)
- [Google Antigravity FAQ](https://antigravity.google/docs/faq/)
