"""One-time migration: give every saved search / schedule a uniform output column
layout (timestamp, api, spAccountID, channelPartnerID, bu_name, ...).

Each extract keeps its own regex and field names — only the *order* (sequence)
and the *CSV headers* are unified, via the aggregation config's raw_columns /
column_labels / timestamp_column. The raw message and log_format columns are
dropped so the CSV is parsed fields only.

Usage (dry run first — prints what would change, writes nothing):
    docker-compose exec api python -m app.uniform_columns_migration
    docker-compose exec api python -m app.uniform_columns_migration --apply

Library-mode searches (use_library, regex resolved against Log Formats at run
time) are SKIPPED: their field universe isn't known until a run, so ordering
them blind could name a column no format defines and fail the job. Order those
in the UI, where the field list is visible.
"""

from __future__ import annotations

import re
import sys

from app.database import SessionLocal

UNIFORM_LABELS = {
    "api": "api",
    "account_id": "spAccountID",
    "channel_partner": "channelPartnerID",
    "bu_name": "bu_name",
}

_SLOT_PATTERNS: list[tuple[str, int, re.Pattern[str]]] = [
    ("api", 1, re.compile(r"^(api|action|apiname|operation)$")),
    (
        "account_id",
        2,
        re.compile(r"(spid|spaccount|cpcustomer|customerid|accountid|cpid|trackerid)"),
    ),
    (
        "channel_partner",
        3,
        re.compile(r"(channelpartner|channelid)"),
    ),
    ("bu_name", 4, re.compile(r"^(bu|buid|buname|businessunit)$|^bu")),
]


def _norm(s: str) -> str:
    return s.lower().replace("_", "")


def suggest_layout(fields: list[str]) -> tuple[list[str], dict[str, str]]:
    """Mirror of web/components/output-columns-editor.tsx::suggestUniformLayout."""
    ranked: list[tuple[str, int, str]] = []
    for i, f in enumerate(fields):
        n = _norm(f)
        label = None
        seq = 10 + i
        for name, s, pat in _SLOT_PATTERNS:
            if pat.search(n):
                seq, label = s, UNIFORM_LABELS[name]
                break
        ranked.append((f, seq, label if label is not None else f))
    ranked.sort(key=lambda r: (r[1], fields.index(r[0])))
    raw_columns = [f for f, _, _ in ranked]
    column_labels = {f: lbl for f, _, lbl in ranked if lbl != f}
    return raw_columns, column_labels


def uniform_agg(agg: dict) -> tuple[dict, str]:
    """Return (new_agg, description). Raises ValueError if not migratable."""
    if not agg.get("enabled"):
        raise ValueError("aggregation not enabled")
    if agg.get("use_library"):
        raise ValueError("library-mode — order in the UI")
    fields: list[str] = []
    for f in [*agg.get("group_by", []), *agg.get("unique_fields", []), *agg.get("raw_columns", [])]:
        if f not in fields:
            fields.append(f)
    if not fields:
        raise ValueError("no fields to order")
    raw_columns, column_labels = suggest_layout(fields)
    new_agg = dict(agg)
    new_agg["raw_columns"] = raw_columns
    new_agg["column_labels"] = column_labels
    new_agg["timestamp_column"] = "timestamp"
    new_agg["include_log_format"] = False
    new_agg["include_message"] = False
    headers = ["timestamp", *(column_labels.get(f, f) for f in raw_columns)]
    return new_agg, " -> ".join(headers)


def main(apply: bool = False) -> int:
    from app.models import FilterTemplate, Schedule

    changed = skipped = 0
    with SessionLocal() as db:
        templates = db.query(FilterTemplate).order_by(FilterTemplate.name).all()
        for tpl in templates:
            agg = tpl.aggregation or {}
            try:
                new_agg, desc = uniform_agg(agg)
            except ValueError as exc:
                print(f"SKIP template {tpl.name!r}: {exc}")
                skipped += 1
                continue
            print(f"{'APPLY' if apply else 'WOULD'} template {tpl.name!r}: {desc}")
            if apply:
                tpl.aggregation = new_agg
            changed += 1

        schedules = db.query(Schedule).order_by(Schedule.name).all()
        for s in schedules:
            spec = dict(s.filter_spec or {})
            agg = spec.get("aggregation") or {}
            try:
                new_agg, desc = uniform_agg(agg)
            except ValueError as exc:
                print(f"SKIP schedule {s.name!r}: {exc}")
                skipped += 1
                continue
            print(f"{'APPLY' if apply else 'WOULD'} schedule {s.name!r}: {desc}")
            if apply:
                spec["aggregation"] = new_agg
                s.filter_spec = spec
            changed += 1

        if apply:
            db.commit()
    print(
        f"\n{changed} would change, {skipped} skipped."
        if not apply
        else f"\n{changed} updated, {skipped} skipped."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv[1:]))
