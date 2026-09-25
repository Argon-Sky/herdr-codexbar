import type { ModApi } from "@commandcode/harness";

import { execFile } from "node:child_process";

// Command Code mod: report the session's model, effort and context to
// herdr-codexbar, which publishes them with Command Code quota to this Herdr
// pane. Values come from the session's own model requests, not the shared
// config, which other sessions can change. `herdr-codexbar setup` copies this
// file into ~/.commandcode/mods with the command path filled in.

type Usage = { inputTokens: number; outputTokens: number };

const COMMAND = "__HERDR_CODEXBAR_BIN__";
const SOURCE = "user:herdr-codexbar";

export function report(model?: string, effort?: string, usage?: Usage, limit?: number) {
  // inputTokens already includes cached input; the reply joins the next prompt.
  const used = usage ? usage.inputTokens + usage.outputTokens : NaN;
  return {
    harness: "commandcode",
    provider_id: "commandcode",
    model: model || null,
    effort: effort || null,
    context_used: Number.isFinite(used) && used > 0 ? used : null,
    context_limit: limit && limit > 0 ? limit : null,
    context_percent: null,
  };
}

const run = (command: string, args: string[], input?: string): Promise<string | undefined> => new Promise((resolve) => {
  try {
    const child = execFile(command, args, { timeout: 5_000 }, (error, stdout) => resolve(error ? undefined : stdout));
    child.stdin?.end(input ?? "");
  } catch {
    resolve(undefined);
  }
});

// `cmd status --json` reports the context window of the configured model only;
// re-run this CLI's own entrypoint rather than whatever `cmd` is on PATH.
async function contextWindow(model: string): Promise<number | undefined> {
  try {
    const status = JSON.parse((await run(process.execPath, [process.argv[1], "status", "--json"])) ?? "{}");
    return status.model === model && typeof status.context_window === "number" ? status.context_window : undefined;
  } catch {
    return undefined;
  }
}

export default function (cmd: ModApi): void {
  const pane = process.env.HERDR_PANE_ID ?? "";
  const headless = !process.stdin.isTTY || !process.stdout.isTTY || process.argv.some((value) => value === "-p" || value === "--print" || value === "--output-format");
  if (headless || process.env.HERDR_ENV !== "1" || !process.env.HERDR_SOCKET_PATH || !pane) return;

  const herdr = process.env.HERDR_BIN_PATH || "herdr";
  const windows = new Map<string, Promise<number | undefined>>();
  let sessionId: string | undefined;
  let reportedSession: string | undefined;
  let last: { model?: string; effort?: string; usage?: Usage } = {};

  cmd.on("run_start", (event) => {
    sessionId = event.sessionId;
  });
  cmd.on("model_request_end", (event) => {
    last = { model: event.model, effort: event.effort, usage: event.usage };
  });

  cmd.hooks({
    async onTurnEnd({ state }) {
      // Herdr has no Command Code integration; this is how it knows the pane runs `cmd`.
      if (sessionId && sessionId !== reportedSession) {
        await run(herdr, ["pane", "report-agent-session", pane, "--source", SOURCE, "--agent", "cmd", "--agent-session-id", sessionId]);
        reportedSession = sessionId;
      }
      const { model, effort, usage } = last;
      if (model && !windows.has(model)) windows.set(model, contextWindow(model));
      const limit = model ? await windows.get(model) : undefined;
      await run(COMMAND, ["report"], JSON.stringify(report(model, effort, usage, limit)));
      return state;
    },
  });
}
