"use client";

import * as React from "react";
import { formatEpoch, type Tz } from "@/lib/time";

export type ChartPoint = { start_epoch: number; value: number };
export type ChartSeries = { label: string; color: string; points: ChartPoint[] };

const W = 900;
const H = 260;
const PAD = { left: 56, right: 18, top: 18, bottom: 30 };

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

function fmt(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 10_000) return `${(value / 1_000).toFixed(1)}k`;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}

/**
 * A small dependency-free comparison chart. Both series use the same time and
 * value axes, which is the point of the page: Last9 and New Relic should line
 * up bucket-for-bucket.
 */
export function ComparisonChart({
  series,
  start,
  end,
  tz,
}: {
  series: ChartSeries[];
  start: number;
  end: number;
  tz: Tz;
}) {
  const svgRef = React.useRef<SVGSVGElement>(null);
  const frameRef = React.useRef<number | null>(null);
  const pendingRef = React.useRef<{ clientX: number } | null>(null);
  const [hover, setHover] = React.useState<{
    px: number;
    time: number;
    values: { label: string; color: string; value: number }[];
  } | null>(null);

  // Ordering, axis scale and both path strings are derived only from the data.
  // Recomputing them per mousemove re-serialized up to 500 points x 2 series on
  // every pixel of movement; now they are built once per dataset.
  const model = React.useMemo(() => {
    const visible = series.filter((s) => s.points.length > 0);
    const ordered = visible.map((s) => ({
      ...s,
      points: [...s.points].sort((a, b) => a.start_epoch - b.start_epoch),
    }));
    const allValues = ordered.flatMap((s) => s.points.map((p) => p.value));
    const maxValue = niceMax(Math.max(0, ...allValues));
    const span = Math.max(1, end - start);
    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;
    const x = (time: number) => PAD.left + ((time - start) / span) * plotW;
    const y = (value: number) => PAD.top + plotH - (value / maxValue) * plotH;

    const paths = ordered.map((s) => {
      const line = s.points
        .map(
          (point, index) =>
            `${index === 0 ? "M" : "L"} ${x(point.start_epoch).toFixed(2)} ${y(point.value).toFixed(
              2
            )}`
        )
        .join(" ");
      const last = s.points[s.points.length - 1];
      const first = s.points[0];
      const area = `${line} L ${x(last.start_epoch).toFixed(2)} ${y(0).toFixed(
        2
      )} L ${x(first.start_epoch).toFixed(2)} ${y(0).toFixed(2)} Z`;
      return { ...s, line, area };
    });

    return { visible, ordered, paths, maxValue, span, plotW, plotH, x, y };
  }, [series, start, end]);

  const { visible, ordered, paths, maxValue, span, plotW, plotH, x, y } = model;

  /** Nearest point by start time; points are sorted, so binary search. */
  function nearest(points: ChartPoint[], time: number): ChartPoint {
    let lo = 0;
    let hi = points.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (points[mid].start_epoch <= time) lo = mid;
      else hi = mid;
    }
    return Math.abs(points[lo].start_epoch - time) <= Math.abs(points[hi].start_epoch - time)
      ? points[lo]
      : points[hi];
  }

  const applyHover = React.useCallback(
    (clientX: number) => {
      if (!svgRef.current || ordered.length === 0) return;
      const rect = svgRef.current.getBoundingClientRect();
      const px = ((clientX - rect.left) / rect.width) * W;
      const clamped = Math.min(PAD.left + plotW, Math.max(PAD.left, px));
      const time = start + ((clamped - PAD.left) / plotW) * span;
      setHover({
        px: clamped,
        time,
        values: ordered.map((s) => ({
          label: s.label,
          color: s.color,
          value: nearest(s.points, time).value,
        })),
      });
    },
    [ordered, plotW, span, start]
  );

  // Coalesce mousemove to one update per animation frame — a pointer reports far
  // more often than the browser paints, and each update re-renders the SVG.
  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    pendingRef.current = { clientX: e.clientX };
    if (frameRef.current !== null) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      const pending = pendingRef.current;
      if (pending) applyHover(pending.clientX);
    });
  }

  function onLeave() {
    pendingRef.current = null;
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    setHover(null);
  }

  React.useEffect(
    () => () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    },
    []
  );

  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const xTicks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="relative">
      <div className="mb-3 flex flex-wrap items-center gap-4">
        {series.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-xs">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: s.color }}
              aria-hidden
            />
            <span className="font-medium">{s.label}</span>
            <span className="font-mono text-muted-foreground">{s.points.length} buckets</span>
          </div>
        ))}
      </div>

      {visible.length === 0 ? (
        <div className="flex h-52 items-center justify-center border border-dashed border-border text-xs text-muted-foreground">
          No time-series points returned for this window.
        </div>
      ) : (
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full touch-none select-none"
          role="img"
          aria-label="Last9 versus New Relic time series"
          onMouseMove={onMove}
          onMouseLeave={onLeave}
        >
          {/* horizontal grid + value axis */}
          {yTicks.map((tick) => {
            const value = maxValue * tick;
            return (
              <g key={tick}>
                <line
                  x1={PAD.left}
                  x2={W - PAD.right}
                  y1={y(value)}
                  y2={y(value)}
                  stroke="hsl(var(--border))"
                  strokeWidth={1}
                  strokeDasharray={tick === 0 ? undefined : "3 5"}
                />
                <text
                  x={PAD.left - 9}
                  y={y(value) + 3.5}
                  textAnchor="end"
                  className="fill-muted-foreground"
                  fontSize={10}
                  fontFamily="var(--font-mono)"
                >
                  {fmt(value)}
                </text>
              </g>
            );
          })}

          {/* x axis labels */}
          {xTicks.map((tick) => {
            const time = start + span * tick;
            return (
              <text
                key={tick}
                x={x(time)}
                y={H - 9}
                textAnchor={tick === 0 ? "start" : tick === 1 ? "end" : "middle"}
                className="fill-muted-foreground"
                fontSize={10}
                fontFamily="var(--font-mono)"
              >
                {formatEpoch(Math.round(time), tz)}
              </text>
            );
          })}

          {paths.map((s) => {
            const points = s.points;
            return (
              <g key={s.label}>
                <path d={s.area} fill={s.color} opacity={0.08} />
                <path
                  d={s.line}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={2.25}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                />
                {points.length <= 2 &&
                  points.map((point) => (
                    <circle
                      key={point.start_epoch}
                      cx={x(point.start_epoch)}
                      cy={y(point.value)}
                      r={3.5}
                      fill={s.color}
                    />
                  ))}
              </g>
            );
          })}

          {hover && (
            <g>
              <line
                x1={hover.px}
                x2={hover.px}
                y1={PAD.top}
                y2={H - PAD.bottom}
                stroke="hsl(var(--foreground))"
                strokeWidth={1}
                strokeDasharray="2 3"
                opacity={0.35}
              />
              {ordered.map((s) => {
                const point = nearest(s.points, hover.time);
                return (
                  <circle
                    key={s.label}
                    cx={x(point.start_epoch)}
                    cy={y(point.value)}
                    r={4}
                    fill={s.color}
                    stroke="hsl(var(--card))"
                    strokeWidth={2}
                  />
                );
              })}
            </g>
          )}
        </svg>
      )}

      {hover && (
        <div
          className="pointer-events-none absolute top-8 z-10 min-w-[150px] border border-border bg-card px-2.5 py-2 text-xs shadow-card"
          style={{
            left: `${(hover.px / W) * 100}%`,
            transform:
              hover.px > W * 0.7
                ? "translateX(-100%)"
                : hover.px < W * 0.3
                  ? "translateX(0)"
                  : "translateX(-50%)",
          }}
        >
          <p className="mb-1 font-mono text-[10px] text-muted-foreground">
            {formatEpoch(Math.round(hover.time), tz)}
          </p>
          {hover.values.map((value) => (
            <div key={value.label} className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: value.color }} />
                {value.label}
              </span>
              <span className="font-mono font-medium">{fmt(value.value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
