"""Pure anomaly rules for scheduled extractions.

Kept free of Celery and the database so the thresholds can be tested directly:

1. Row-count drop — compare the run's ``rows_written`` with the previous
   completed run of the same schedule. A 20% threshold means 8,000 vs 10,000
   alerts (a 20.0% drop), while 8,001 does not.
2. Unmatched rows — use the parse/aggregation snapshot's ``rows_unmatched``.
   A threshold of 100 alerts at 100 unmatched rows, not at 99.

Both alerts are opt-in per schedule. A missing baseline (first run) never
produces a row-drop alert. A previous run that wrote zero rows is skipped as a
baseline and the comparison looks further back, so a zero-row run neither alerts
nor hides the next real drop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnomalyEvaluation:
    reasons: list[str]
    current_rows: int
    previous_rows: int | None
    drop_pct: float | None
    rows_unmatched: int
    parsed_rows: int
    unmatched_pct: float | None


def evaluate_anomaly(
    *,
    current_rows: int,
    previous_rows: int | None,
    rows_matched: int | None,
    rows_unmatched: int | None,
    alert_on_row_drop: bool,
    row_drop_threshold_pct: int,
    alert_on_unmatched: bool,
    unmatched_threshold: int,
) -> AnomalyEvaluation:
    """Return the anomaly reasons and the numbers used to reach them."""
    current = max(0, int(current_rows))
    previous = None if previous_rows is None else max(0, int(previous_rows))
    matched = max(0, int(rows_matched or 0))
    unmatched = max(0, int(rows_unmatched or 0))
    parsed = matched + unmatched

    reasons: list[str] = []
    drop_pct: float | None = None
    if previous is not None and previous > 0:
        drop_pct = (previous - current) / previous * 100
        threshold = max(1, min(100, int(row_drop_threshold_pct)))
        if alert_on_row_drop and drop_pct >= threshold:
            reasons.append(
                f"Rows written dropped {drop_pct:.1f}% versus the previous completed run "
                f"({current:,} vs {previous:,}; threshold {threshold}%)"
            )

    unmatched_pct = (unmatched / parsed * 100) if parsed else None
    threshold = max(1, int(unmatched_threshold))
    if alert_on_unmatched and unmatched >= threshold:
        share = f" ({unmatched_pct:.2f}% of parsed rows)" if unmatched_pct is not None else ""
        reasons.append(
            f"{unmatched:,} unmatched row(s) at or above the {threshold:,}-row threshold{share}"
        )

    return AnomalyEvaluation(
        reasons=reasons,
        current_rows=current,
        previous_rows=previous,
        drop_pct=drop_pct,
        rows_unmatched=unmatched,
        parsed_rows=parsed,
        unmatched_pct=unmatched_pct,
    )
