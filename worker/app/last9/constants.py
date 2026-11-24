"""Last9 ground-truth constants (validated against the live API — see §2)."""

from __future__ import annotations

# §2.5 — THE COMPLETE list of valid operators. Nothing else exists.
# Note: `$containsWords` is intentionally absent — it does NOT exist (§2.5).
VALID_OPERATORS: frozenset[str] = frozenset(
    {
        "$eq",
        "$neq",
        "$contains",
        "$notcontains",
        "$regex",
        "$notregex",
        "$gt",
        "$lt",
        "$gte",
        "$lte",
    }
)

# §2.5 — the log message field is `Body` (capital B). Confirmed working.
BODY_FIELD = "Body"

# §2.11 — region code -> friendly label. Index targets are region-scoped.
REGIONS: dict[str, str] = {
    "ap-south-1": "India",
    "us-east-1": "Virginia",
    "ap-southeast-1": "Singapore",
    "eu-central-1": "Frankfurt",
}

# §2.13 — index format string.
INDEX_PREFIX = "physical_index"

# §2.3 — default query params.
DEFAULT_LIMIT = 10000
# Files are consumed top-down (Excel, grep, a diff), so rows must be written
# oldest-first. Backward made each chunk land newest-first: the first line of a
# day was 00:59:59 and the 00:00 rows sat further down the file, which reads as
# a missing first hour. Chunks already run start -> end, so forward also makes
# the whole file globally ascending.
DEFAULT_DIRECTION = "forward"
DEFAULT_STEP = "200ms"

# §2.6 — safe batch size: ~100 IDs per regex => ~5 KB requests.
DEFAULT_ID_BATCH_SIZE = 100

# §2.9 — default time-chunk size.
DEFAULT_CHUNK_HOURS = 1


def physical_index(name: str) -> str:
    """Build the full index string Last9 expects, e.g. ``physical_index:UMServices``.

    If ``name`` already carries a ``<prefix>:`` it is returned unchanged so callers
    can pass either a bare name or a full index string.
    """
    if ":" in name:
        return name
    return f"{INDEX_PREFIX}:{name}"
