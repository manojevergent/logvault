import * as React from "react";

// IST is a fixed +5:30 offset (no DST), so no tz library is needed.
export const IST_OFFSET_SEC = 330 * 60;

export type Tz = "IST" | "UTC";

/** A datetime-local value ("2024-01-01T05:30") read as wall-clock in `tz` -> epoch seconds. */
export function localToEpoch(local: string, tz: Tz): number {
  const asUtc = Math.floor(Date.parse(`${local}:00Z`) / 1000);
  return tz === "IST" ? asUtc - IST_OFFSET_SEC : asUtc;
}

/** Epoch seconds -> a datetime-local value showing wall-clock in `tz`. */
export function epochToLocal(epoch: number, tz: Tz): string {
  const shifted = (epoch + (tz === "IST" ? IST_OFFSET_SEC : 0)) * 1000;
  return new Date(shifted).toISOString().slice(0, 16);
}

/** Epoch seconds -> "YYYY-MM-DD HH:MM" in `tz`, for display. */
export function formatEpoch(epoch: number, tz: Tz = "UTC"): string {
  const shifted = (epoch + (tz === "IST" ? IST_OFFSET_SEC : 0)) * 1000;
  return new Date(shifted).toISOString().slice(0, 16).replace("T", " ");
}

/**
 * A job's range shown with an INCLUSIVE end. Extraction windows are half-open
 * `[start, end)` (see worker chunking), so a full day is stored as 00:00 → 00:00
 * of the next day; printing the raw end makes a day look like it covers no time
 * at all. The last instant actually included is `end - 1`, which renders as
 * 23:59 — what the range means to a reader.
 */
export function formatRange(start: number, end: number, tz: Tz = "UTC"): string {
  return `${formatEpoch(start, tz)} → ${formatEpoch(Math.max(start, end - 1), tz)}`;
}

/**
 * The same inclusive range, short enough for a table cell: "10-28 07:24 → 08:24"
 * within one day, "10-24 00:00 → 10-27 17:44" across days.
 *
 * The full form is ~40 characters and wrapped to five lines in the jobs table,
 * which is what made every row tall. Callers keep the full `formatRange` in a
 * title attribute so nothing is lost.
 */
export function formatRangeCompact(start: number, end: number, tz: Tz = "UTC"): string {
  const from = formatEpoch(start, tz);
  const to = formatEpoch(Math.max(start, end - 1), tz);
  const fromDate = from.slice(5, 10);
  const toDate = to.slice(5, 10);
  return fromDate === toDate
    ? `${fromDate} ${from.slice(11)} → ${to.slice(11)}`
    : `${fromDate} ${from.slice(11)} → ${toDate} ${to.slice(11)}`;
}

/**
 * A span of seconds as a short human string: "45s", "12m 30s", "2h 14m",
 * "3d 4h". Jobs run for hours, so raw seconds ("8040s") are unreadable exactly
 * where the number matters most.
 */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return s % 60 ? `${m}m ${s % 60}s` : `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d}d ${h % 24}h` : `${d}d`;
}

const TZ_KEY = "logvault:tz";

/** Display timezone, remembered across pages. Defaults to UTC: the application
 *  writes its log timestamps in UTC and daily windows are aligned to UTC
 *  midnight, so UTC is the zone in which a range can be checked against the
 *  data. Starts there on the server to keep hydration stable, correcting after
 *  mount if a preference was saved. */
export function useTz(): [Tz, (t: Tz) => void] {
  const [tz, setTzState] = React.useState<Tz>("UTC");
  React.useEffect(() => {
    const saved = window.localStorage.getItem(TZ_KEY);
    if (saved === "UTC" || saved === "IST") setTzState(saved);
  }, []);
  return [
    tz,
    (t: Tz) => {
      setTzState(t);
      window.localStorage.setItem(TZ_KEY, t);
    },
  ];
}

export const PRESETS: { label: string; seconds: number }[] = [
  { label: "Last 5m", seconds: 5 * 60 },
  { label: "Last 10m", seconds: 10 * 60 },
  { label: "Last 30m", seconds: 30 * 60 },
  { label: "Last 45m", seconds: 45 * 60 },
  { label: "Last 1h", seconds: 3600 },
  { label: "Last 2h", seconds: 2 * 3600 },
  { label: "Last 3h", seconds: 3 * 3600 },
  { label: "Last 5h", seconds: 5 * 3600 },
  { label: "Last 6h", seconds: 6 * 3600 },
  { label: "Last 24h", seconds: 24 * 3600 },
  { label: "Last 7d", seconds: 7 * 24 * 3600 },
];
