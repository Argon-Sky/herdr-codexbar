import assert from "node:assert/strict";
import test from "node:test";

import { report } from "../herdr_codexbar/agents/pi.ts";

test("reports provider, model, thinking level and context", () => {
  const model = { id: "deepseek-v4.1-flash", name: "DeepSeek V4.1 Flash", provider: "opencode-go", reasoning: true };
  assert.deepEqual(report("pi", model, "high", { tokens: 42_000, contextWindow: 1_000_000, percent: 4.2 }), {
    harness: "pi", provider_id: "opencode-go", model: "DeepSeek V4.1 Flash", effort: "high",
    context_used: 42_000, context_limit: 1_000_000, context_percent: 4.2,
  });
});

test("leaves out thinking for models without reasoning or when off", () => {
  assert.equal(report("omp", { id: "m", provider: "p", reasoning: false }, "high").effort, null);
  assert.equal(report("prime", { id: "m", provider: "p", reasoning: true }, "off").effort, null);
});

test("reports unknown context after a compaction as missing", () => {
  const empty = report("pi", { id: "m", provider: "p" }, undefined, { tokens: null, contextWindow: 200_000, percent: null });
  assert.equal(empty.model, "m");
  assert.equal(empty.context_used, null);
  assert.equal(empty.context_percent, null);
});
