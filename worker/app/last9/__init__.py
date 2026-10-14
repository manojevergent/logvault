"""Last9 core library.

Framework-agnostic (pure Python + httpx) implementation of the validated Last9
API behaviour from CLAUDE_CODE_PROMPT.md §2: token management, the filter
pipeline builder with regex batching, streaming pagination, time chunking,
checkpoint/resume, and the retry policy. The Celery worker (Phase 4) and the API
"test connection" (Phase 3) both build on this.
"""

from __future__ import annotations

from .aggregate import AggregationError, AggregationSpec, Aggregator, normalize_pattern
from .batching import batch_ids, dedupe_preserve_order
from .bq_formatter import BQRow, parse_bq_row
from .checkpoint import Checkpoint
from .chunking import count_chunks, make_chunks
from .client import Last9Client, LogRow
from .constants import (
    BODY_FIELD,
    DEFAULT_CHUNK_HOURS,
    DEFAULT_ID_BATCH_SIZE,
    DEFAULT_LIMIT,
    REGIONS,
    VALID_OPERATORS,
    physical_index,
)
from .distinct_store import DistinctStore, store_path
from .errors import (
    AuthExpiredError,
    FatalClientError,
    Last9Error,
    PipelineError,
    RetryableError,
    TransientBadRequestError,
)
from .escaping import esc
from .extract import (
    ExtractionPlan,
    ExtractionSpec,
    iter_extraction,
    plan_extraction,
)
from .formats import FormatMatcher, LogFormat, validate_formats
from .pipeline import (
    build_filter_pipeline,
    build_filter_query,
    build_id_regex,
    build_pipeline,
)
from .timeutil import (
    describe_range,
    format_log_timestamp,
    local_to_epoch,
    previous_calendar_day_window,
    to_epoch,
)
from .tokens import TokenManager, TokenSet

__all__ = [
    "AggregationError",
    "AggregationSpec",
    "Aggregator",
    "AuthExpiredError",
    "BQRow",
    "BODY_FIELD",
    "BQRow",
    "Checkpoint",
    "DEFAULT_CHUNK_HOURS",
    "DEFAULT_ID_BATCH_SIZE",
    "DEFAULT_LIMIT",
    "DistinctStore",
    "FormatMatcher",
    "LogFormat",
    "ExtractionPlan",
    "ExtractionSpec",
    "FatalClientError",
    "Last9Client",
    "Last9Error",
    "LogRow",
    "PipelineError",
    "REGIONS",
    "RetryableError",
    "TokenManager",
    "TokenSet",
    "TransientBadRequestError",
    "VALID_OPERATORS",
    "batch_ids",
    "build_filter_pipeline",
    "build_filter_query",
    "build_id_regex",
    "build_pipeline",
    "count_chunks",
    "dedupe_preserve_order",
    "describe_range",
    "esc",
    "format_log_timestamp",
    "iter_extraction",
    "local_to_epoch",
    "make_chunks",
    "normalize_pattern",
    "parse_bq_row",
    "physical_index",
    "parse_bq_row",
    "plan_extraction",
    "previous_calendar_day_window",
    "store_path",
    "to_epoch",
    "validate_formats",
]
