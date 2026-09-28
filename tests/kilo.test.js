import assert from "node:assert/strict";
import test from "node:test";

import { contextUsage, currentModel, report } from "../herdr_codexbar/agents/kilo.js";

const providers = [{ id: "opencode-go", models: { "glm-5.3": { limit: { context: 200_000 } } } }];
const user = (providerID, modelID, variant) => ({ role: "user", model: { providerID, modelID, variant } });
const assistant = (output) => ({ role: "assistant", providerID: "opencode-go", modelID: "glm-5.3", variant: "high",
  tokens: { input: 1_000, output, reasoning: 0, cache: { read: 30_000, write: 500 } } });

test("reports the answering model and its context", () => {
  const messages = [user("opencode-go", "glm-5.3", "high"), assistant(200)];
  assert.deepEqual(report(currentModel(messages), contextUsage(messages, providers)), {
    harness: "kilo", provider_id: "opencode-go", model: "glm-5.3", effort: "high",
    context_used: 31_700, context_limit: 200_000, context_percent: null,
  });
});

test("a new prompt with another model switches the provider at once", () => {
  const messages = [user("opencode-go", "glm-5.3"), assistant(200), user("commandcode", "gpt-6-luna")];
  assert.deepEqual(currentModel(messages), { providerID: "commandcode", modelID: "gpt-6-luna", variant: undefined });
  assert.equal(contextUsage(messages, providers).used, 31_700);
});

test("no messages, no report", () => {
  assert.equal(currentModel([]), undefined);
  assert.equal(contextUsage([assistant(0)], providers), undefined);
});
