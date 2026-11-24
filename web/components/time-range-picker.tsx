"use client";

import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Clock } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/input";
import {
  WEEKDAYS,
  addMonths,
  compareYmd,
  inDayRange,
  keyToYmd,
  monthGrid,
  monthLabel,
  sameYmd,
  ymdKey,
  type Ymd,
} from "@/lib/calendar";
import { PRESETS, Tz, epochToLocal, formatEpoch, localToEpoch } from "@/lib/time";
import { cn } from "@/lib/utils";

function splitLocal(local: string): { day: Ymd; time: string } {
  const [date, time] = local.split("T");
  return { day: keyToYmd(date), time: time || "00:00" };
}

/** "11-11 00:00 → 11-12 00:00" — the raw window, exclusive end, compact. */
function windowLabel(start: number, end: number, tz: Tz): string {
  const from = formatEpoch(start, tz);
  const to = formatEpoch(end, tz);
  return from.slice(0, 10) === to.slice(0, 10)
    ? `${from.slice(5, 10)} ${from.slice(11)} → ${to.slice(11)}`
    : `${from.slice(5, 10)} ${from.slice(11)} → ${to.slice(5, 10)} ${to.slice(11)}`;
}

/**
 * Last9-style time window picker: a field-like trigger that opens a two-panel
 * popover — relative ranges on the left, a calendar with explicit start/end
 * times on the right.
 *
 * Why a popover instead of the preset row it replaces: the row of eleven buttons
 * plus two raw `datetime-local` inputs was both wide and imprecise. The calendar
 * makes "start of the day" one click, and separate date/time fields keep the
 * chosen minute visible instead of hidden in a native widget.
 *
 * The component is controlled: it renders `start`/`end`/`tz` and reports a new
 * window through `onChange`, so the wizard stays the source of truth.
 */
export function TimeRangePicker({
  start,
  end,
  tz,
  onChange,
}: {
  start: number;
  end: number;
  tz: Tz;
  onChange: (start: number, end: number, tz: Tz) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [dropUp, setDropUp] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const [draftStart, setDraftStart] = React.useState<Ymd | null>(null);
  const [draftEnd, setDraftEnd] = React.useState<Ymd | null>(null);
  const [startTime, setStartTime] = React.useState("00:00");
  const [endTime, setEndTime] = React.useState("00:00");
  const [draftTz, setDraftTz] = React.useState<Tz>(tz);
  const [view, setView] = React.useState<Ymd>({ year: 2026, month: 0, day: 1 });
  const [error, setError] = React.useState<string | null>(null);
  const boxRef = React.useRef<HTMLDivElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

  const seed = React.useCallback(() => {
    const s = splitLocal(epochToLocal(start, tz));
    const e = splitLocal(epochToLocal(end, tz));
    setDraftStart(s.day);
    setDraftEnd(e.day);
    setStartTime(s.time);
    setEndTime(e.time);
    setDraftTz(tz);
    setView(s.day);
    setError(null);
  }, [start, end, tz]);

  React.useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  React.useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open]);

  const openPicker = () => {
    seed();
    // The panel is ~690px tall. On a short viewport there may be no room below
    // the trigger, and a panel that runs off the bottom hides Apply. Open upward
    // when that is the roomier side; the panel also scrolls internally.
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      const below = window.innerHeight - rect.bottom;
      setDropUp(below < 460 && rect.top > below);
    }
    setOpen(true);
  };

  const applyRelative = (seconds: number) => {
    const now = Math.floor(Date.now() / 1000);
    onChange(now - seconds, now, draftTz);
    setOpen(false);
  };

  const clickDay = (day: Ymd) => {
    setError(null);
    // A complete range means the next click starts a new selection.
    if (!draftStart || (draftStart && draftEnd)) {
      setDraftStart(day);
      setDraftEnd(null);
      return;
    }
    if (compareYmd(day, draftStart) < 0) {
      setDraftEnd(draftStart);
      setDraftStart(day);
    } else {
      setDraftEnd(day);
    }
  };

  const apply = () => {
    if (!draftStart || !draftEnd) {
      setError("Pick a start and end day.");
      return;
    }
    const nextStart = localToEpoch(`${ymdKey(draftStart)}T${startTime}`, draftTz);
    const nextEnd = localToEpoch(`${ymdKey(draftEnd)}T${endTime}`, draftTz);
    if (nextEnd <= nextStart) {
      setError("End must be after start.");
      return;
    }
    onChange(nextStart, nextEnd, draftTz);
    setOpen(false);
  };

  const changeDraftTz = (zone: Tz) => {
    if (zone === draftTz) return;
    // Keep the instant, not the clock face: switching UTC -> IST must not move
    // the window by 5:30. The fields then show the same moment in the new zone.
    const shift = (day: Ymd | null, time: string) =>
      day === null
        ? null
        : splitLocal(epochToLocal(localToEpoch(`${ymdKey(day)}T${time}`, draftTz), zone));
    const s = shift(draftStart, startTime);
    const e = shift(draftEnd, endTime);
    setDraftStart(s?.day ?? null);
    setStartTime(s?.time ?? "00:00");
    setDraftEnd(e?.day ?? null);
    setEndTime(e?.time ?? "00:00");
    setDraftTz(zone);
    setError(null);
  };

  const now = Math.floor(Date.now() / 1000);
  const activePreset = PRESETS.find(
    (p) => Math.abs(end - start - p.seconds) <= 30 && Math.abs(end - now) <= 120
  );
  const weeks = monthGrid(view.year, view.month);

  return (
    <div ref={boxRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (open ? setOpen(false) : openPicker())}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cn(
          "flex h-9 w-full items-center gap-2 border border-input bg-background px-3 text-left text-sm",
          "transition-colors hover:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        <Clock className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate font-mono text-[13px] text-foreground">
          {windowLabel(start, end, tz)}
        </span>
        <span className="ml-auto shrink-0 text-[11px] font-medium text-muted-foreground">{tz}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180"
          )}
        />
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label="Pick a time range"
          tabIndex={-1}
          className={cn(
            "absolute left-0 z-50 w-[620px] max-w-[calc(100vw-2rem)] overflow-y-auto border border-border bg-surface shadow-card-hover focus:outline-none",
            "max-h-[calc(100vh-7rem)]",
            dropUp ? "bottom-full mb-1" : "top-full mt-1"
          )}
        >
          <div className="grid grid-cols-1 sm:grid-cols-[168px_1fr]">
            {/* Relative */}
            <div className="border-b border-border p-2 sm:border-b-0 sm:border-r">
              <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                Relative
              </p>
              <div className="grid grid-cols-2 gap-0.5 sm:grid-cols-1">
                {PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => applyRelative(p.seconds)}
                    className={cn(
                      "border border-transparent px-2 py-1 text-left text-xs transition-colors",
                      activePreset?.seconds === p.seconds
                        ? "bg-accent font-medium text-foreground"
                        : "text-muted-foreground hover:border-border hover:text-foreground"
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Absolute */}
            <div className="p-3">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold">{monthLabel(view.year, view.month)}</p>
                <div className="flex items-center gap-0.5">
                  <button
                    type="button"
                    aria-label="Previous month"
                    onClick={() => setView(addMonths(view, -1))}
                    className="flex h-6 w-6 items-center justify-center text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    aria-label="Next month"
                    onClick={() => setView(addMonths(view, 1))}
                    className="flex h-6 w-6 items-center justify-center text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-7 gap-y-0.5">
                {WEEKDAYS.map((label) => (
                  <div
                    key={label}
                    className="pb-1 text-center text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70"
                  >
                    {label}
                  </div>
                ))}
                {weeks.flat().map((day, i) => {
                  if (!day) return <div key={`pad-${i}`} />;
                  const isStart = draftStart ? sameYmd(day, draftStart) : false;
                  const isEnd = draftEnd ? sameYmd(day, draftEnd) : false;
                  const inRange = inDayRange(day, draftStart, draftEnd);
                  const today = sameYmd(day, splitLocal(epochToLocal(now, draftTz)).day);
                  return (
                    <button
                      key={ymdKey(day)}
                      type="button"
                      onClick={() => clickDay(day)}
                      aria-label={`${ymdKey(day)}${isStart ? " (start)" : ""}${
                        isEnd ? " (end)" : ""
                      }`}
                      className={cn(
                        "mx-auto flex h-7 w-7 items-center justify-center text-xs transition-colors",
                        isStart || isEnd
                          ? "bg-primary font-semibold text-primary-foreground"
                          : inRange
                            ? "bg-accent text-foreground"
                            : "text-muted-foreground hover:bg-accent hover:text-foreground",
                        today && !isStart && !isEnd && "ring-1 ring-inset ring-ring"
                      )}
                    >
                      {day.day}
                    </button>
                  );
                })}
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2 border-t border-border pt-3">
                <div className="space-y-1">
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
                    Start
                  </p>
                  <div className="flex items-center gap-1">
                    <CalendarDays className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <input
                      type="date"
                      value={draftStart ? ymdKey(draftStart) : ""}
                      onChange={(e) => {
                        const next = e.target.value ? keyToYmd(e.target.value) : null;
                        setDraftStart(next);
                        setError(null);
                      }}
                      className={cn(fieldClass, "h-8 min-w-0 flex-1 px-2 font-mono text-xs")}
                    />
                    <input
                      type="time"
                      value={startTime}
                      onChange={(e) => {
                        setStartTime(e.target.value);
                        setError(null);
                      }}
                      className={cn(fieldClass, "h-8 w-[86px] shrink-0 px-2 font-mono text-xs")}
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
                    End
                  </p>
                  <div className="flex items-center gap-1">
                    <CalendarDays className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <input
                      type="date"
                      value={draftEnd ? ymdKey(draftEnd) : ""}
                      onChange={(e) => {
                        const next = e.target.value ? keyToYmd(e.target.value) : null;
                        setDraftEnd(next);
                        setError(null);
                      }}
                      className={cn(fieldClass, "h-8 min-w-0 flex-1 px-2 font-mono text-xs")}
                    />
                    <input
                      type="time"
                      value={endTime}
                      onChange={(e) => {
                        setEndTime(e.target.value);
                        setError(null);
                      }}
                      className={cn(fieldClass, "h-8 w-[86px] shrink-0 px-2 font-mono text-xs")}
                    />
                  </div>
                </div>
              </div>

              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-1">
                  {(["UTC", "IST"] as Tz[]).map((zone) => (
                    <button
                      key={zone}
                      type="button"
                      onClick={() => changeDraftTz(zone)}
                      className={cn(
                        "border px-2 py-0.5 text-[11px] font-semibold transition-colors",
                        draftTz === zone
                          ? "border-transparent bg-primary text-primary-foreground"
                          : "border-border text-muted-foreground hover:text-foreground"
                      )}
                    >
                      {zone}
                    </button>
                  ))}
                  <span className="ml-1 text-[10px] text-muted-foreground">
                    times read in {draftTz}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {error && <span className="text-[11px] text-danger">{error}</span>}
                  <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
                    Cancel
                  </Button>
                  <Button type="button" size="sm" onClick={apply}>
                    Apply
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
