import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import { execFile } from "node:child_process";

// Pi extension: report the session's provider, model, thinking level and
// context to herdr-codexbar, which publishes them with the provider's quota to
// this Herdr pane. `herdr-codexbar setup` copies this file into
// ~/.pi/agent/extensions with the command path filled in.

type Model = { id?: string; name?: string; provider?: string; reasoning?: boolean };
type Usage = { tokens: number | null; contextWindow: number; percent: number | null };

const COMMAND = "__HERDR_CODEXBAR_BIN__";

// The provider ID picks the subscription: "opencode-go" is OpenCode Go, and a
// custom provider named after a CodexBar provider (e.g. "commandcode") uses its quota.
export function report(model?: Model, thinking?: string, usage?: Usage) {
  const count = (value: unknown) => (typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null);
  return {
    harness: "pi",
    provider_id: model?.provider || null,
    model: model?.name || model?.id || null,
    effort: model?.reasoning && thinking && thinking !== "off" ? thinking : null,
    context_used: count(usage?.tokens),
    context_limit: count(usage?.contextWindow),
    context_percent: typeof usage?.percent === "number" ? usage.percent : null,
  };
}

export default function (pi: ExtensionAPI): void {
  if (process.env.HERDR_ENV !== "1" || !process.env.HERDR_SOCKET_PATH || !process.env.HERDR_PANE_ID) return;

  let last: string | undefined;
  let pending = false;
  let queued: (() => void) | undefined;
  const sync = (ctx: ExtensionContext, model?: Model) => {
    if (ctx.mode !== "tui") return;
    if (pending) {
      queued = () => sync(ctx, model); // Report the newest state once the running report ends.
      return;
    }
    try {
      const payload = JSON.stringify(report(model ?? ctx.model, pi.getThinkingLevel(), ctx.getContextUsage()));
      if (payload === last) return;
      pending = true;
      const child = execFile(COMMAND, ["report"], { timeout: 5_000 }, (error) => {
        pending = false;
        if (!error) last = payload;
        const next = queued;
        queued = undefined;
        next?.();
      });
      child.stdin?.end(payload);
    } catch {
      pending = false; // Reporting is best-effort and must never disturb Pi.
    }
  };

  pi.on("session_start", (_event, ctx) => sync(ctx));
  pi.on("model_select", (event, ctx) => sync(ctx, event.model));
  pi.on("thinking_level_select", (_event, ctx) => sync(ctx));
  pi.on("turn_end", (_event, ctx) => sync(ctx));
}
