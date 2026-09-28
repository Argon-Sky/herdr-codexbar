// OpenCode V2 TUI plugin: report the selected session's provider, model, effort
// and context usage to herdr-codexbar, which publishes them to this Herdr pane.
//
// It runs in the pane-local TUI process (V2 server plugins run in a shared
// service without HERDR_PANE_ID) and reads the same client data as OpenCode's
// footer. `herdr-codexbar setup` installs a two-line entrypoint that calls
// create() with the path of the herdr-codexbar command.

import { execFile, spawn } from "node:child_process";

const POLL_INTERVAL_MS = 1_000;

// Mirrors OpenCode's footer: the newest assistant message with token usage
// after the last completed compaction (and before a pending revert point).
export function contextUsage(messages, models, revertMessageID) {
  if (!Array.isArray(messages)) return undefined;
  const revertIndex = revertMessageID ? messages.findIndex((message) => message.id === revertMessageID) : -1;
  if (revertMessageID && revertIndex === -1) return undefined;
  const end = revertIndex === -1 ? messages.length : revertIndex;
  const compaction = messages.findLastIndex((message, index) => message.type === "compaction" && message.status === "completed" && index < end);
  const latest = messages.findLast((message, index) => message.type === "assistant" && message.tokens !== undefined && index > compaction && index < end);
  if (!latest) return undefined;
  const { input = 0, output = 0, reasoning = 0, cache = {} } = latest.tokens;
  const used = input + output + reasoning + (cache.read ?? 0) + (cache.write ?? 0);
  if (!Number.isFinite(used) || used <= 0) return undefined;
  const limit = models?.find((model) => model.providerID === latest.model?.providerID && model.id === latest.model?.id)?.limit?.context;
  return { used, limit: typeof limit === "number" && limit > 0 ? limit : null };
}

// The provider ID picks the subscription: "opencode-go" is OpenCode Go, and a
// custom provider named after a CodexBar provider (e.g. "commandcode") uses its quota.
export function report(session, context) {
  const text = (value) => (typeof value === "string" && value ? value : null);
  return {
    harness: "opencode",
    provider_id: text(session?.model?.providerID),
    model: text(session?.model?.id),
    effort: text(session?.model?.variant),
    context_used: context?.used ?? null,
    context_limit: context?.limit ?? null,
    context_percent: null,
  };
}

export function create(command) {
  function setup(api) {
    if (process.env.HERDR_ENV !== "1" || !process.env.HERDR_SOCKET_PATH || !process.env.HERDR_PANE_ID) return;

    let last;
    let pending = false;
    const sync = () => {
      if (pending) return;
      try {
        const route = api.ui.router.current();
        const selected = route?.type === "session" ? api.data.session.root(route.sessionID) : undefined;
        const session = selected ? api.data.session.get(selected) : undefined;
        if (!session) return;
        const context = contextUsage(
          api.data.session.message.list(selected),
          api.data.location.model.list(session.location),
          session.revert?.messageID,
        );
        const payload = JSON.stringify(report(session, context));
        if (payload === last) return;
        pending = true;
        const child = execFile(command, ["report"], { timeout: 5_000 }, (error) => {
          pending = false;
          if (!error) last = payload;
        });
        child.stdin?.end(payload);
      } catch {
        pending = false; // Reporting is best-effort and must never disturb the TUI.
      }
    };

    sync();
    const poll = setInterval(sync, POLL_INTERVAL_MS);
    poll.unref?.();
    return () => {
      clearInterval(poll);
      // On exit, remove this pane's rows so the next program in it does not show them; detached, as the TUI may exit before the command finishes.
      if (last !== undefined) spawn(command, ["clear", "opencode"], { detached: true, stdio: "ignore" }).unref();
    };
  }

  return { id: "herdr-codexbar", setup };
}
