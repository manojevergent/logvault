// Ten is enough to reach for a window you used recently without the list
// becoming something to scan.
const RECENT_LIMIT = 10;
const KEY = "logvault:recent_ranges";

export type SavedRange = {
  start: number;
  end: number;
  tz: "IST" | "UTC";
  label: string; // human-readable, UTC
};

export function getRecentRanges(): SavedRange[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function saveRange(start: number, end: number, tz: "IST" | "UTC"): void {
  const fmt = (e: number) => new Date(e * 1000).toISOString().slice(0, 16).replace("T", " ");
  const label = `${fmt(start)} → ${fmt(end)} UTC`;
  const prev = getRecentRanges().filter((r) => !(r.start === start && r.end === end));
  prev.unshift({ start, end, tz, label });
  localStorage.setItem(KEY, JSON.stringify(prev.slice(0, RECENT_LIMIT)));
}
