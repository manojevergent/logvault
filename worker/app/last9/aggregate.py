"""Parse & aggregate: extract named fields from each row's message via a regex,
group by some fields, and count DISTINCT values of one or more other fields.

One use case (unique SPID count per API+BU) generalizes to N: any number of
named groups can be counted independently, so the same regex can answer
"how many unique X" for several X's in a single pass over the rows.

Memory-safe at any cardinality: the distinct values live in a SQLite file (see
distinct_store.py), not in the process, and never in the job row. This never
touches a raw row after extracting its handful of named values from it.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .distinct_store import DistinctStore, group_key_to_text
from .formats import FormatMatcher, LogFormat, validate_formats
from .patterns import AggregationError, compile_pattern, normalize_pattern

__all__ = [
    "AggregationError",
    "AggregationSpec",
    "Aggregator",
    "compile_pattern",
    "excel_safe",
    "normalize_pattern",
    "validate_field_names",
]

# The job row carries only enough groups to render the UI table; the full
# breakdown goes to the summary CSV. Without a cap, a group_by on a
# high-cardinality field (customer) would write megabytes of JSON per chunk.
SNAPSHOT_GROUP_LIMIT = 200
# Group keys are a handful in practice; past this many distinct keys the cache
# stops growing (a group_by on a unique field would otherwise never hit).
_GROUP_KEY_CACHE = 4096


def excel_safe(value: str) -> str:
    """Guard a value Excel would turn into a number, leaving everything else
    alone so ordinary output stays clean for non-Excel readers.

    Excel coerces any field it can read as a number, and a float64 carries only
    ~15 significant digits, so an account id like 230702032635917346995349
    arrives as 2.30702E+23 with its tail zeroed. Formatting the column as Text
    afterwards cannot recover it — the digits are gone at parse time.

    The test is "can this be read as a number", not "is this all digits": ids
    such as 220808164446813 (15 digits) and hex forms like 230702E23 are both
    coerced, and an all-digits length check misses them. `="..."` is the one
    form Excel keeps verbatim when a .csv is opened directly.
    """
    if not value:
        return value
    # A leading =, +, - or @ makes the cell a formula, which Excel evaluates on
    # open. The text comes from application logs, so it is attacker-influenced;
    # wrapping is the same escape already used for long ids. Leading whitespace
    # is stripped first because Excel ignores it when deciding.
    if value.lstrip("\t\r\n ")[:1] in ("=", "+", "-", "@"):
        return f'="{value}"'
    try:
        float(value)
    except ValueError:
        return value  # letters or dashes present — Excel leaves it as text
    return f'="{value}"'


def validate_field_names(
    compiled: re.Pattern[str],
    group_by: list[str],
    unique_fields: list[str],
    raw_columns: Sequence[str] = (),
) -> None:
    defined = set(compiled.groupindex)
    missing = [f for f in (*group_by, *unique_fields, *raw_columns) if f not in defined]
    if missing:
        raise AggregationError(f"regex has no named group(s): {', '.join(missing)}")
    # See the matching check in api/app/aggregation.py: grouping by the field
    # being counted forces every count to 1.
    both = [f for f in group_by if f in set(unique_fields)]
    if both:
        raise AggregationError(
            f"{', '.join(both)} cannot be both grouped by and counted — every count would be 1"
        )


@dataclass
class AggregationSpec:
    regex: str = ""
    group_by: list[str] = field(default_factory=list)
    unique_fields: list[str] = field(default_factory=list)
    # False = parse only (match + write fields, no grouping/counting). True is
    # the behaviour every existing job, schedule and saved search expects.
    aggregate: bool = True
    skip_raw_output: bool = False
    # Try every enabled format in the library instead of the single `regex`.
    use_library: bool = False
    # Exact columns (and order) for the raw CSV/JSONL export. Independent of
    # group_by/unique_fields, which still drive the summary/counts files —
    # a field can appear in one, both, or neither. Empty means the old default:
    # [log_format, *group_by, *unique_fields].
    raw_columns: list[str] = field(default_factory=list)
    # Literal fallback for a raw_columns entry with no real data — either it
    # isn't a named group in the regex at all (a field this log shape never
    # carries, e.g. bu_id for a customer whose logs have no "in BU ..." text),
    # or the group matched empty. Keyed entries are exempt from the "regex has
    # no named group" check; the constant is emitted verbatim instead.
    raw_column_defaults: dict[str, str] = field(default_factory=dict)
    # False drops the leading `log_format` column from the raw export — only
    # applies to the implicit default column set (empty raw_columns); an
    # explicit raw_columns list already omits it unless named there, so this
    # never adds a column raw_columns didn't ask for.
    include_log_format: bool = True
    # False drops the trailing `message` column from the raw export — for a
    # customer whose deliverable is the parsed fields only, not the source line.
    include_message: bool = True
    # Header text for the raw export's first column.
    timestamp_column: str = "timestamp_utc"
    # Rename a parsed field's CSV header independent of what the regex calls
    # it — e.g. two specs whose regexes name the same concept `spid` and
    # `channelPartnerId` can both emit a `spAccountID` column, so extracts
    # from different log shapes come out comparable. Values are still looked
    # up by the regex's own name (self.parsed_fields); only the header
    # text (self.parsed_field_labels) changes.
    column_labels: dict[str, str] = field(default_factory=dict)
    # Wrap values Excel would coerce (long ids, timestamps) as `="..."` so a
    # spreadsheet keeps them verbatim. That literal `=` and the quotes are
    # DATA, so a warehouse loading the CSV gets `="2112091"` instead of
    # `2112091` — off by default, on via EXCEL_ESCAPE for spreadsheet users.
    excel_escape: bool = False


# Which pattern parsed a row. Always the first parsed column, so a mixed-format
# extract can be split or filtered by shape without re-deriving it.
FORMAT_COLUMN = "log_format"


def group_by_then_unique(spec: AggregationSpec) -> list[str]:
    return [*spec.group_by, *spec.unique_fields]


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


class Aggregator:
    """Streaming, resumable unique-count aggregation over row messages.

    Values accumulate in ``store``; call ``flush()`` at a checkpoint boundary.
    Resuming means reopening the same store path — there is no state to restore.
    """

    def __init__(
        self,
        spec: AggregationSpec,
        store: DistinctStore,
        matcher: FormatMatcher | None = None,
    ) -> None:
        # Either a library of formats, or the single pattern on the spec. One
        # regex is just a one-format library, so the matching path is shared.
        if matcher is None:
            matcher = FormatMatcher([LogFormat(name="pattern", regex=spec.regex)])
        self._matcher = matcher
        self._raw_column_defaults = dict(spec.raw_column_defaults)
        # A raw_columns entry with a configured default is a deliberate
        # constant, not a field the regex is expected to define.
        checked_raw_columns = [c for c in spec.raw_columns if c not in self._raw_column_defaults]
        validate_formats(
            matcher.formats,
            spec.group_by if spec.aggregate else [],
            spec.unique_fields if spec.aggregate else [],
            checked_raw_columns,
        )
        self.aggregate = spec.aggregate
        # A parse-only run keeps no grouping/counting state at all.
        self.group_by = spec.group_by if spec.aggregate else []
        self.unique_fields = spec.unique_fields if spec.aggregate else []
        self.store = store
        # Group keys repeat on almost every row; the serialized form is cached
        # per key instead of rebuilt per row. A high-cardinality group_by stops
        # growing the cache after the cap and falls back to serializing.
        self._key_texts: dict[tuple[str, ...], str] = {}
        self.include_message = spec.include_message
        self.timestamp_column = spec.timestamp_column
        self.excel_escape = spec.excel_escape
        self._raw_columns = list(spec.raw_columns)
        if self._raw_columns:
            # Caller wants exact columns in exact order — no forced log_format
            # prefix, since a single-pattern job has only one format anyway.
            # (include_log_format doesn't apply here: an explicit list already
            # omits it unless the caller named it, same as any other field.)
            self.parsed_fields: list[str] = list(self._raw_columns)
        elif not self.aggregate:
            # Parse only: every named group is a deliverable column, in
            # definition order. A single regex has no use for a log_format
            # column ("pattern"); a library run does, to say which shape matched.
            if len(self._matcher.formats) == 1:
                self.parsed_fields = list(self._matcher.formats[0].compiled.groupindex)
            else:
                fields = self._matcher.field_names_ordered()
                self.parsed_fields = [FORMAT_COLUMN, *fields] if spec.include_log_format else fields
        else:
            # Columns for the raw export. NOT every named group across the library:
            # with hundreds of formats that would be hundreds of columns, and the
            # header has to be written before the first row arrives. The fields the
            # aggregation is about are the ones worth breaking out; everything else
            # stays recoverable from the message column.
            fields = _dedupe(group_by_then_unique(spec))
            self.parsed_fields = [FORMAT_COLUMN, *fields] if spec.include_log_format else fields
        # process() needs to know whether element 0 of the implicit column set
        # really is log_format, since that's the only element it fills from
        # hit.format_name rather than hit.fields.
        self._leading_log_format = (
            not self._raw_columns
            and spec.include_log_format
            and (self.aggregate or len(self._matcher.formats) > 1)
        )
        # CSV header text, parallel to parsed_fields — log_format itself is
        # never renamed (it's synthetic, not a regex field), only the fields
        # that come from spec.column_labels.
        self.parsed_field_labels = [
            f if self._leading_log_format and i == 0 else spec.column_labels.get(f, f)
            for i, f in enumerate(self.parsed_fields)
        ]

    def process(self, message: str) -> list[str] | None:
        """Match once, count it, and return the export columns.

        One entry point because matching is the expensive part: parsing for the
        CSV and feeding the aggregate separately would run every regex twice per
        row and double every per-format tally.
        """
        hit = self._matcher.match(message)
        if hit is None:
            self.store.bump("rows_unmatched")
            return None
        self._accumulate(hit)
        if self._raw_columns:
            # A field the regex never defines, or defined but this row left
            # empty, falls back to its configured constant (e.g. "None").
            values = [
                hit.fields.get(f) or self._raw_column_defaults.get(f, "")
                for f in self.parsed_fields
            ]
        elif self._leading_log_format:
            # Element 0 is log_format, filled from hit.format_name rather than
            # hit.fields — the rest come from fields same as any other column.
            values = [hit.format_name]
            values += [hit.fields.get(f, "") for f in self.parsed_fields[1:]]
        else:
            values = [hit.fields.get(f, "") for f in self.parsed_fields]
        # Opt-in only: the `="..."` wrapper is what breaks warehouse loads.
        return [excel_safe(v) for v in values] if self.excel_escape else values

    def _accumulate(self, hit) -> None:
        if self.aggregate:
            key = tuple(hit.fields.get(f) or "" for f in self.group_by)
            key_text = self._key_texts.get(key)
            if key_text is None:
                key_text = group_key_to_text(key)
                if len(self._key_texts) < _GROUP_KEY_CACHE:
                    self._key_texts[key] = key_text
            for f in self.unique_fields:
                val = hit.fields.get(f)
                if val:
                    self.store.add_key_text(key_text, f, val)
        self.store.bump("rows_matched")

    @property
    def rows_matched(self) -> int:
        return self.store.counter("rows_matched")

    @property
    def rows_unmatched(self) -> int:
        return self.store.counter("rows_unmatched")

    def coverage(self) -> list[dict[str, object]]:
        """Rows parsed per format — a format stuck at zero is a broken regex."""
        return self._matcher.coverage()

    def feed(self, message: str) -> None:
        """Aggregate a row without needing its export columns."""
        self.process(message)

    def flush(self, chunk_index: int | None = None) -> None:
        """Commit the buffered chunk. ``chunk_index`` makes it idempotent — see
        DistinctStore.flush; occurrence counts add, so a replayed chunk must not
        be counted twice."""
        self.store.flush(chunk_index)

    def snapshot(self, limit: int = SNAPSHOT_GROUP_LIMIT) -> dict:
        """Small, display-only summary for the job row — counts, not values, and
        at most ``limit`` groups. The complete breakdown is the summary CSV."""
        groups = []
        truncated = False
        if self.aggregate:
            for key, counts in self.store.iter_groups():
                if len(groups) >= limit:
                    truncated = True
                    break
                groups.append(
                    {
                        "key": dict(zip(self.group_by, key, strict=True)),
                        "unique_counts": {f: counts.get(f, 0) for f in self.unique_fields},
                    }
                )
        return {
            "aggregate": self.aggregate,
            "group_by": self.group_by,
            "unique_fields": self.unique_fields,
            "rows_matched": self.rows_matched,
            "rows_unmatched": self.rows_unmatched,
            "total_groups": self.store.group_count() if self.aggregate else 0,
            # Which patterns actually did the work. A format stuck at zero is a
            # regex that doesn't match anything — otherwise invisible.
            "coverage": [c for c in self.coverage() if c["rows"]][:20],
            "truncated": truncated,
            "groups": groups,
        }

    def write_value_counts_csv(self, path: str) -> int:
        """One row per distinct value with how many log lines it appeared in,
        most frequent first — the pivot-table view, precomputed.

        Written per counted field, so a spec counting spid and trackerid gets a
        `<field>,count` pair of columns for each. Streams over the store.
        """
        written = 0
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            for i, fld in enumerate(self.unique_fields):
                if i:
                    w.writerow([])  # blank line between fields; Excel reads it fine
                # Group columns ride along so each row says which BU (and
                # whatever else is grouped on) the value belongs to.
                w.writerow([fld, *self.group_by, "count"])
                for key, value, n in self.store.iter_value_counts(fld):
                    if self.excel_escape:
                        w.writerow([excel_safe(value), *(excel_safe(k) for k in key), n])
                    else:
                        w.writerow([value, *key, n])
                    written += 1
        return written

    def write_summary_csv(self, path: str) -> int:
        """Write the full breakdown — one row per group, one count column per
        unique field. Streams, so group count is not bounded by memory."""
        written = 0
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([*self.group_by, *(f"unique_{f}" for f in self.unique_fields)])
            for key, counts in self.store.iter_groups():
                row = [*(excel_safe(v) for v in key)] if self.excel_escape else list(key)
                w.writerow([*row, *(counts.get(f, 0) for f in self.unique_fields)])
                written += 1
        return written
