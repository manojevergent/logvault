import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addMonths,
  compareYmd,
  daysInMonth,
  inDayRange,
  keyToYmd,
  monthGrid,
  monthLabel,
  sameYmd,
  ymdKey,
} from "./calendar.ts";

test("ymdKey round-trips through keyToYmd", () => {
  const day = { year: 2026, month: 10, day: 11 };
  assert.equal(ymdKey(day), "2026-11-11");
  assert.deepEqual(keyToYmd("2026-11-11"), day);
});

test("compareYmd orders by year, then month, then day", () => {
  const a = { year: 2026, month: 10, day: 11 };
  const b = { year: 2026, month: 10, day: 12 };
  const c = { year: 2027, month: 0, day: 1 };
  assert.ok(compareYmd(a, b) < 0);
  assert.ok(compareYmd(b, c) < 0);
  assert.equal(compareYmd(a, { ...a }), 0);
  assert.ok(sameYmd(a, { ...a }));
});

test("addMonths crosses year boundaries in both directions", () => {
  assert.deepEqual(addMonths({ year: 2026, month: 11, day: 15 }, 1), {
    year: 2027,
    month: 0,
    day: 1,
  });
  assert.deepEqual(addMonths({ year: 2026, month: 0, day: 15 }, -1), {
    year: 2025,
    month: 11,
    day: 1,
  });
});

test("daysInMonth knows leap years", () => {
  assert.equal(daysInMonth(2024, 1), 29);
  assert.equal(daysInMonth(2026, 1), 28);
  assert.equal(daysInMonth(2026, 10), 30);
});

test("monthGrid is always six Monday-first weeks", () => {
  // February 2026 starts on a Sunday, so the first row has six blanks.
  const weeks = monthGrid(2026, 1);
  assert.equal(weeks.length, 6);
  assert.ok(weeks.every((week) => week.length === 7));
  assert.equal(weeks[0][0], null);
  assert.equal(weeks[0][5], null);
  assert.deepEqual(weeks[0][6], { year: 2026, month: 1, day: 1 });
  const days = weeks.flat().filter(Boolean);
  assert.equal(days.length, 28);
});

test("inDayRange includes both endpoints and excludes the day after", () => {
  const start = { year: 2026, month: 10, day: 11 };
  const end = { year: 2026, month: 10, day: 12 };
  assert.ok(inDayRange(start, start, end));
  assert.ok(inDayRange(end, start, end));
  assert.ok(!inDayRange({ year: 2026, month: 10, day: 13 }, start, end));
  assert.ok(!inDayRange({ year: 2026, month: 10, day: 10 }, start, end));
});

test("monthLabel uses a stable English name", () => {
  assert.equal(monthLabel(2026, 10), "November 2026");
});
