import assert from "node:assert/strict";
import { test } from "node:test";

import { completionOf, gapSummary, isPartial, jobProgress } from "./completion.ts";

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

test("a completed job is 100% even when the chunk denominator is stale", () => {
  assert.equal(jobProgress({ status: "completed", completed_chunks: 13, total_chunks: 25 }), 100);
  assert.equal(jobProgress({ status: "completed", completed_chunks: 0, total_chunks: 0 }), 100);
});

test("a running job uses the live chunk ratio", () => {
  assert.equal(jobProgress({ status: "running", completed_chunks: 3, total_chunks: 10 }), 30);
  assert.equal(jobProgress({ status: "paused", completed_chunks: 9, total_chunks: 10 }), 90);
});

test("progress is 0 before the first chunk total exists", () => {
  assert.equal(jobProgress({ status: "queued", completed_chunks: 0, total_chunks: 0 }), 0);
  assert.equal(jobProgress({ status: "running", completed_chunks: 0, total_chunks: 0 }), 0);
  assert.equal(jobProgress(null), 0);
});

test("failed and canceled jobs report the chunks they completed", () => {
  assert.equal(jobProgress({ status: "failed", completed_chunks: 2, total_chunks: 10 }), 20);
  assert.equal(jobProgress({ status: "canceled", completed_chunks: 10, total_chunks: 10 }), 100);
});

test("progress clamps malformed or overrun counts", () => {
  assert.equal(jobProgress({ status: "running", completed_chunks: 12, total_chunks: 10 }), 100);
  assert.equal(jobProgress({ status: "failed", completed_chunks: -1, total_chunks: 10 }), 0);
  assert.equal(
    jobProgress({ status: "running", completed_chunks: Number.NaN, total_chunks: 10 }),
    0
  );
});
