import assert from "node:assert/strict";
import test from "node:test";

import { contextUsage, create, report } from "../herdr_codexbar/agents/opencode.js";

const models = [{ id: "glm-5", providerID: "opencode-go", limit: { context: 200_000 } }];
const model = { id: "glm-5", providerID: "opencode-go", variant: "high" };
const assistant = (id, input, cacheRead = 0) => ({
  id, type: "assistant", model, tokens: { input, output: 100, reasoning: 0, cache: { read: cacheRead, write: 0 } },
});

test("uses the newest assistant usage, like OpenCode's footer", () => {
  const messages = [assistant("m1", 1_000), { id: "m2", type: "user" }, assistant("m3", 11_700, 7_300)];
  assert.deepEqual(contextUsage(messages, models), { used: 19_100, limit: 200_000 });
});

test("ignores usage before a completed compaction and after a revert point", () => {
  const messages = [assistant("m1", 150_000), { id: "c1", type: "compaction", status: "completed" }, assistant("m2", 10_000), assistant("m3", 90_000)];
  assert.equal(contextUsage(messages.slice(0, 2), models), undefined);
  assert.equal(contextUsage(messages, models, "m3").used, 10_100);
});

test("keeps used tokens when the model limit is unknown", () => {
  assert.deepEqual(contextUsage([assistant("m1", 1_000)], []), { used: 1_100, limit: null });
});

test("reports the selected provider so quota follows the subscription", () => {
  assert.deepEqual(report({ model }, { used: 19_100, limit: 200_000 }), {
    harness: "opencode", provider_id: "opencode-go", model: "glm-5", effort: "high",
    context_used: 19_100, context_limit: 200_000, context_percent: null,
  });
  assert.equal(report({ model: { id: "x", providerID: "commandcode" } }).provider_id, "commandcode");
  assert.equal(report(undefined).model, null);
});

test("does nothing outside Herdr", () => {
  const saved = process.env.HERDR_ENV;
  delete process.env.HERDR_ENV;
  assert.equal(create("/bin/false").setup({}), undefined);
  if (saved !== undefined) process.env.HERDR_ENV = saved;
});
