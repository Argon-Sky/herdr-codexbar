// Kilo CLI TUI plugin: report the selected session's provider, model, variant
// and context usage to herdr-codexbar, which publishes them to this Herdr pane.
//
// Kilo is an OpenCode fork with the older TUI plugin API: the model in use is
// the one on the session's newest messages. `herdr-codexbar setup` installs a
// two-line entrypoint that calls create() with the path of the herdr-codexbar
// command, and lists it under "plugin" in ~/.config/kilo/tui.json.

import { execFile, spawn } from "node:child_process";

const POLL_INTERVAL_MS = 1_000;

// Mirrors Kilo's sidebar: the newest assistant message that produced output.
export function contextUsage(messages, providers) {
  if (!Array.isArray(messages)) return undefined;
  const latest = messages.findLast((message) => message.role === "assistant" && message.tokens?.output > 0);
  if (!latest) return undefined;
  const { input = 0, output = 0, reasoning = 0, cache = {} } = latest.tokens;
  const used = input + output + reasoning + (cache.read ?? 0) + (cache.write ?? 0);
  if (!Number.isFinite(used) || used <= 0) return undefined;
  const limit = providers?.find((provider) => provider.id === latest.providerID)?.models?.[latest.modelID]?.limit?.context;
  return { used, limit: typeof limit === "number" && limit > 0 ? limit : null };
}

// The newest message says which model the session uses: a user message carries
// the model it was sent with, an assistant message the model that answered.
export function currentModel(messages) {
  const latest = Array.isArray(messages) ? messages.findLast((message) => message.role === "user" || message.role === "assistant") : undefined;
  if (!latest) return undefined;
  return latest.role === "user"
    ? { providerID: latest.model?.providerID, modelID: latest.model?.modelID, variant: latest.model?.variant }
    : { providerID: latest.providerID, modelID: latest.modelID, variant: latest.variant };
}

// The provider ID picks the subscription: "opencode-go" is OpenCode Go, and a
// custom provider named after a CodexBar provider (e.g. "commandcode") uses its quota.
export function report(model, context) {
  const text = (value) => (typeof value === "string" && value ? value : null);
  return {
    harness: "kilo",
    provider_id: text(model?.providerID),
    model: text(model?.modelID),
    effort: text(model?.variant),
    context_used: context?.used ?? null,
    context_limit: context?.limit ?? null,
    context_percent: null,
  };
}

export function create(command) {
  async function tui(api) {
    if (process.env.HERDR_ENV !== "1" || !process.env.HERDR_SOCKET_PATH || !process.env.HERDR_PANE_ID) return;

    let last;
    let pending = false;
    const sync = () => {
      if (pending) return;
      try {
        const route = api.route.current;
        let session = route?.name === "session" ? api.state.session.get(route.params.sessionID) : undefined;
        // A subagent's pane shows its root session, as OpenCode's plugin does.
        for (let parent = session; parent; parent = parent.parentID ? api.state.session.get(parent.parentID) : undefined) session = parent;
        if (!session) return;
        const messages = api.state.session.messages(session.id);
        const model = currentModel(messages);
        if (!model) return;
        const payload = JSON.stringify(report(model, contextUsage(messages, api.state.provider)));
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
    api.lifecycle.onDispose(() => {
      clearInterval(poll);
      // On exit, remove this pane's rows so the next program in it does not show them; detached, as the TUI may exit before the command finishes.
      if (last !== undefined) spawn(command, ["clear", "kilo"], { detached: true, stdio: "ignore" }).unref();
    });
  }

  return { id: "herdr-codexbar", tui };
}
