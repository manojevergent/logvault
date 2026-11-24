/**
 * Calendar maths for the time-range picker.
 *
 * Everything here works on a plain wall-clock date (`Ymd`), never on an epoch.
 * The picker's calendar is drawn in the display zone, so a day is "the 11th as
 * the operator sees it", not "the 11th in UTC" — converting to an instant is the
 * caller's job (`localToEpoch`), which keeps the two concerns separate and makes
 * the grid testable without a clock.
 */

export type Ymd = { year: number; month: number; day: number }; // month is 0-11

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** Monday-first, matching the ISO week used in engineering schedules. */
export const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

const pad = (n: number) => String(n).padStart(2, "0");

/** "2026-11-11" — the key used for comparisons and as a stable list key. */
export function ymdKey({ year, month, day }: Ymd): string {
  return `${year}-${pad(month + 1)}-${pad(day)}`;
}

export function keyToYmd(key: string): Ymd {
  const [year, month, day] = key.split("-").map(Number);
  return { year, month: month - 1, day };
}

export function compareYmd(a: Ymd, b: Ymd): number {
  return a.year - b.year || a.month - b.month || a.day - b.day;
}

export function sameYmd(a: Ymd, b: Ymd): boolean {
  return compareYmd(a, b) === 0;
}

/** Move whole months, clamping to the first so month lengths never overflow. */
export function addMonths(y: Ymd, delta: number): Ymd {
  const total = y.year * 12 + y.month + delta;
  return { year: Math.floor(total / 12), month: ((total % 12) + 12) % 12, day: 1 };
}

export function daysInMonth(year: number, month: number): number {
  // Day 0 of the next month is the last day of this one.
  return new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
}

export function monthLabel(year: number, month: number): string {
  return `${MONTHS[month]} ${year}`;
}

/**
 * Six weeks of cells, Monday-first. Padding cells are `null` so the caller can
 * render blanks without inventing dates. The grid is always 42 cells: a month
 * that needs five rows would otherwise change the popover's height as the user
 * pages through months.
 */
export function monthGrid(year: number, month: number): (Ymd | null)[][] {
  const first = new Date(Date.UTC(year, month, 1));
  const lead = (first.getUTCDay() + 6) % 7; // Monday = 0
  const cells: (Ymd | null)[] = Array(lead).fill(null);
  for (let day = 1; day <= daysInMonth(year, month); day++) {
    cells.push({ year, month, day });
  }
  while (cells.length < 42) cells.push(null);
  const weeks: (Ymd | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** True when `day` falls inside the inclusive [start, end] day span. */
export function inDayRange(day: Ymd, start: Ymd | null, end: Ymd | null): boolean {
  if (!start || !end) return false;
  return compareYmd(day, start) >= 0 && compareYmd(day, end) <= 0;
}
