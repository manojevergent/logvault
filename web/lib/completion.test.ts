import assert from "node:assert/strict";
import { test } from "node:test";

import { completionOf, gapSummary, isPartial } from "./completion.ts";

test("complete job shows no partial marker", () => {
  const c = completionOf({ completion_state: "complete", gap_count: 0, gap_reason: null });
  assert.equal(c.isPartial, false);
  assert.equal(c.isComplete, true);
  assert.equal(c.label, null);
  assert.equal(gapSummary({ completion_state: "complete", gap_count: 0 }), "");
});

test("partial job is flagged with its gap count", () => {
  const job = { completion_state: "partial", gap_count: 3, gap_reason: "3 ID batches skipped" };
  const c = completionOf(job);
  assert.equal(c.isPartial, true);
  assert.equal(c.label, "partial");
  assert.equal(c.gapCount, 3);
  assert.match(gapSummary(job), /3 batch\(es\) incomplete/);
});

test("partial without a reason still reports the gap", () => {
  const c = completionOf({ completion_state: "partial", gap_count: 2, gap_reason: null });
  assert.equal(c.isPartial, true);
  assert.match(c.detail ?? "", /2 batch\(es\)/);
});

test("legacy API response without new fields stays neutral", () => {
  const c = completionOf({ status: "completed" } as never);
  assert.equal(c.state, "unknown");
  assert.equal(c.isPartial, false);
  assert.equal(c.label, null);
  assert.equal(c.detail, null);
});

test("legacy row with a gap count but no state is treated as partial", () => {
  const c = completionOf({ gap_count: 1 });
  assert.equal(c.isPartial, true);
  assert.equal(c.gapCount, 1);
});

test("failed job is not partial", () => {
  const c = completionOf({ completion_state: "unknown", gap_count: 0 });
  assert.equal(c.isPartial, false);
});

test("canceled job is not partial", () => {
  const c = completionOf({ completion_state: "unknown", gap_count: 0 });
  assert.equal(isPartial({ ...c } as never), false);
});

test("malformed values never throw", () => {
  assert.equal(completionOf(null).isPartial, false);
  assert.equal(completionOf(undefined).label, null);
  assert.equal(completionOf({ gap_count: -5 as number }).gapCount, 0);
  assert.equal(completionOf({ gap_count: Number.NaN as number }).gapCount, 0);
  assert.equal(completionOf({ completion_state: "bogus" }).state, "unknown");
});
