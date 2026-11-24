import assert from "node:assert/strict";
import { test } from "node:test";

import { ceilToHour, epochToLocal, floorToHour, localToEpoch } from "./time.ts";

test("floorToHour snaps a mid-hour start down in UTC", () => {
  const start = localToEpoch("2026-11-11T00:01", "UTC");
  assert.equal(epochToLocal(floorToHour(start, "UTC"), "UTC"), "2026-11-11T00:00");
});

test("ceilToHour snaps a mid-hour end up in UTC", () => {
  const end = localToEpoch("2026-11-11T00:01", "UTC");
  assert.equal(epochToLocal(ceilToHour(end, "UTC"), "UTC"), "2026-11-11T01:00");
});

test("snapping happens in the display zone, not raw epoch space", () => {
  // 00:01 IST is 18:31 UTC the day before. Rounding the raw epoch to a UTC
  // hour would land on 18:00Z = 23:30 IST — the wrong clock face.
  const start = localToEpoch("2026-11-11T00:01", "IST");
  assert.equal(epochToLocal(floorToHour(start, "IST"), "IST"), "2026-11-11T00:00");
  assert.equal(epochToLocal(ceilToHour(start, "IST"), "IST"), "2026-11-11T01:00");
});

test("whole hours are left alone", () => {
  const start = localToEpoch("2026-11-11T00:00", "UTC");
  const end = localToEpoch("2026-11-12T00:00", "UTC");
  assert.equal(floorToHour(start, "UTC"), start);
  assert.equal(ceilToHour(end, "UTC"), end);
});

test("a 00:01 -> 00:00 day becomes a full 00:00 -> 00:00 day", () => {
  const start = localToEpoch("2026-11-11T00:01", "UTC");
  const end = localToEpoch("2026-11-12T00:00", "UTC");
  const snapped = [floorToHour(start, "UTC"), ceilToHour(end, "UTC")];
  assert.equal(epochToLocal(snapped[0], "UTC"), "2026-11-11T00:00");
  assert.equal(epochToLocal(snapped[1], "UTC"), "2026-11-12T00:00");
  assert.equal(snapped[1] - snapped[0], 24 * 3600);
});
