import assert from "node:assert/strict";
import test from "node:test";

import { report } from "../herdr_codexbar/agents/commandcode.ts";

test("reports model, effort and context against a known window", () => {
  assert.deepEqual(report("gpt-6", "max", { inputTokens: 280_000, outputTokens: 2_000 }, 1_050_000), {
    harness: "commandcode", provider_id: "commandcode", model: "gpt-6", effort: "max",
    context_used: 282_000, context_limit: 1_050_000, context_percent: null,
  });
});

test("reports nothing before the first model request", () => {
  const empty = report();
  assert.equal(empty.model, null);
  assert.equal(empty.context_used, null);
  assert.equal(empty.context_limit, null);
});
