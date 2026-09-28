import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import { execFile } from "node:child_process";

// Extension for Pi and its forks (Oh My Pi, Prime Agent): report the session's
// provider, model, thinking level and context to herdr-codexbar, which
// publishes them with the provider's quota to this Herdr pane.
// `herdr-codexbar setup` copies this file into each harness's extensions
// directory with the command, harness and agent filled in.

type Model = { id?: string; name?: string; provider?: string; reasoning?: boolean };
type Usage = { tokens: number | null; contextWindow: number; percent: number | null };

const COMMAND = "__HERDR_CODEXBAR_BIN__";
const HARNESS = "__HERDR_CODEXBAR_HARNESS__";
// Herdr's agent ID for harnesses Herdr does not detect, which this extension then reports; empty otherwise.
const AGENT = "__HERDR_CODEXBAR_AGENT__";
const SOURCE = "user:herdr-codexbar";

// The provider ID picks the subscription: "opencode-go" is OpenCode Go, and a
// custom provider named after a CodexBar provider (e.g. "commandcode") uses its quota.
export function report(harness: string, model?: Model, thinking?: string, usage?: Usage) {
  const count = (value: unknown) => (typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null);
  return {
    harness,
    provider_id: model?.provider || null,
    model: model?.name || model?.id || null,
    effort: model?.reasoning && thinking && thinking !== "off" ? thinking : null,
    context_used: count(usage?.tokens),
    context_limit: count(usage?.contextWindow),
    context_percent: typeof usage?.percent === "number" ? usage.percent : null,
  };
}

const run = (command: string, args: string[], input?: string): Promise<boolean> => new Promise((resolve) => {
  try {
    const child = execFile(command, args, { timeout: 5_000 }, (error) => resolve(!error));
    child.stdin?.end(input ?? "");
  } catch {
    resolve(false);
  }
});

export default function (pi: ExtensionAPI): void {
  const pane = process.env.HERDR_PANE_ID ?? "";
  if (process.env.HERDR_ENV !== "1" || !process.env.HERDR_SOCKET_PATH || !pane) return;

  const herdr = process.env.HERDR_BIN_PATH || "herdr";
  let last: string | undefined;
  let reportedSession: string | undefined;
  let pending = false;
  let queued: (() => void) | undefined;
  const sync = async (ctx: ExtensionContext, model?: Model) => {
    if (!ctx.hasUI) return; // Print and JSON runs have no pane of their own.
    if (pending) {
      queued = () => sync(ctx, model); // Report the newest state once the running report ends.
      return;
    }
    pending = true;
    try {
      const session = AGENT ? ctx.sessionManager.getSessionId() : undefined;
      if (session && session !== reportedSession) {
        await run(herdr, ["pane", "report-agent-session", pane, "--source", SOURCE, "--agent", AGENT, "--agent-session-id", session]);
        reportedSession = session;
      }
      const payload = JSON.stringify(report(HARNESS, model ?? ctx.model, pi.getThinkingLevel(), ctx.getContextUsage()));
      if (payload !== last && (await run(COMMAND, ["report"], payload))) last = payload;
    } catch {
      // Reporting is best-effort and must never disturb the agent.
    } finally {
      pending = false;
      const next = queued;
      queued = undefined;
      next?.();
    }
  };

  pi.on("session_start", (_event, ctx) => void sync(ctx));
  pi.on("session_switch", (_event, ctx) => void sync(ctx)); // Oh My Pi
  pi.on("model_select", (event, ctx) => void sync(ctx, event.model)); // Pi and Prime Agent; Oh My Pi reports at the next turn.
  pi.on("thinking_level_select", (_event, ctx) => void sync(ctx));
  pi.on("turn_start", (_event, ctx) => void sync(ctx));
  pi.on("turn_end", (_event, ctx) => void sync(ctx));
  // On quit, remove this pane's rows so the next program in it does not show them. Pi replaces a session with a reason other than "quit" and reports the new one; Oh My Pi gives no reason.
  pi.on("session_shutdown", async (event) => {
    if ((event?.reason && event.reason !== "quit") || last === undefined) return;
    last = undefined;
    await run(COMMAND, ["clear", HARNESS]);
    if (reportedSession) {
      await run(herdr, ["pane", "release-agent", pane, "--source", SOURCE, "--agent", AGENT]);
      reportedSession = undefined;
    }
  });
}
