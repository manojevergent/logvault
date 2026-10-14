"""
ls9_fetch_to_csv.py
────────────────────────────────────────────────────────────────────────────────
Last9 Log Fetcher — True Streaming CSV Export  (with Auto Token Refresh)
────────────────────────────────────────────────────────────────────────────────
Fetches logs from the Last9 v2 API for a configurable date range and writes
only the message/body field of each log line directly to a CSV file.

Key design decisions
  • True streaming     — rows are extracted and written to disk one-by-one
                         inside the API pagination loop. No list accumulates
                         in memory at any point; `all_data` has been removed.
  • Never in memory    — each API page is parsed, written, and released
                         immediately. The CSV file handle stays open across
                         the whole run so writes are always incremental.
  • Exponential backoff— ALL error types (502/503/504, timeouts, 401 expiry,
                         and any other HTTP error) are retried up to 10 times
                         with wait = min(2^attempt, 300) seconds.
  • Token auto-refresh — 401 / "Authorization token is expired" triggers a
                         transparent token refresh counted as part of the
                         same retry budget.
  • Chunked time range — splits the full date range into N-hour windows so
                         each individual API call stays small.
  • Progress display   — prints cumulative rows downloaded after every page.

Usage
  python ls9_fetch_to_csv.py

  Recommended: supply the refresh token so access tokens are managed for you:
    set LAST9_REFRESH_TOKEN=eyJhbGci...
    set LAST9_ORG_SLUG=evergentapse1
    set LAST9_REGION=ap-southeast-1

  Or, if you already have a short-lived access token (expires in 24 h):
    set LAST9_API_TOKEN=your_access_token

  Other overrides:
    set LAST9_START_EPOCH=1744243200
    set LAST9_END_EPOCH=1745193600
    set LAST9_CHUNK_HOURS=1
    set LAST9_OUTPUT=my_output.csv
────────────────────────────────────────────────────────────────────────────────
"""

import calendar
import csv
import json
import os
import time
from datetime import datetime

import requests


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    """Current local time as a log-prefix string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _utc(epoch: int) -> str:
    """Epoch → human-readable UTC string (Windows-safe, no tz dependency)."""
    return datetime.utcfromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def safe_epoch(year: int, month: int, day: int,
               hour: int = 0, minute: int = 0, second: int = 0) -> int:
    """
    Convert a UTC calendar date/time to an epoch integer.
    Uses calendar.timegm() — correct on Windows regardless of the
    local system clock or timezone setting.
    """
    return calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Token management
# ─────────────────────────────────────────────────────────────────────────────

_OAUTH_URL = "https://app.last9.io/api/v4/oauth/access_token"

_token_state: dict = {
    "access_token":  "",
    "refresh_token": "",
    "expires_at":    0,
}


def init_tokens(api_token: str = "", refresh_token: str = "") -> str:
    """
    Initialise token state at startup.

    If a refresh_token is provided it is exchanged immediately for a fresh
    access token.  Falls back to api_token if the exchange fails or no
    refresh token is given.

    Returns the access token to use for the first API call.
    """
    _token_state["refresh_token"] = refresh_token

    if refresh_token:
        print(f"[{_ts()}] 🔑 Refresh token found — exchanging for access token...")
        new_token = _do_token_refresh(refresh_token)
        if new_token:
            return new_token
        print(f"[{_ts()}] ⚠️  Token exchange failed — falling back to LAST9_API_TOKEN")

    _token_state["access_token"] = api_token
    return api_token


def _do_token_refresh(refresh_token: str) -> str:
    """
    POST to the Last9 OAuth endpoint to exchange a refresh token for a new
    access token.  Rotates _token_state["refresh_token"] to the new value
    returned by Last9.

    Returns the new access token string, or "" on failure.
    """
    try:
        resp = requests.post(
            _OAUTH_URL,
            json={"refresh_token": refresh_token},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()

        new_access  = payload.get("access_token", "")
        new_refresh = payload.get("refresh_token", refresh_token)
        expires_at  = payload.get("expires_at", 0)

        if not new_access:
            print(f"[{_ts()}] ❌ Token exchange: response missing access_token field")
            print(f"[{_ts()}]    Response: {resp.text[:300]}")
            return ""

        _token_state["access_token"]  = new_access
        _token_state["refresh_token"] = new_refresh
        _token_state["expires_at"]    = expires_at

        expiry_str = _utc(expires_at) if expires_at else "unknown"
        print(f"[{_ts()}] ✅ Access token refreshed  (expires: {expiry_str} UTC)")
        return new_access

    except requests.exceptions.HTTPError as exc:
        print(f"[{_ts()}] ❌ Token refresh HTTP error {exc.response.status_code}: "
              f"{exc.response.text[:300]}")
    except requests.exceptions.RequestException as exc:
        print(f"[{_ts()}] ❌ Token refresh request failed: {exc}")
    except (KeyError, ValueError) as exc:
        print(f"[{_ts()}] ❌ Token refresh parse error: {exc}")

    return ""


def get_access_token() -> str:
    """Return the current in-memory access token."""
    return _token_state["access_token"]


def refresh_access_token() -> str:
    """
    Force a token refresh using the stored refresh token.
    Called automatically when the API returns an expiry error.
    Returns the new access token, or "" if no refresh token is available.
    """
    rt = _token_state.get("refresh_token", "")
    if not rt:
        print(f"[{_ts()}] ⚠️  Cannot refresh — no refresh token stored. "
              "Set LAST9_REFRESH_TOKEN env var.")
        return ""
    print(f"[{_ts()}] 🔄 Access token expired — refreshing automatically...")
    return _do_token_refresh(rt)


# ─────────────────────────────────────────────────────────────────────────────
# Message extractor
# ─────────────────────────────────────────────────────────────────────────────

def _extract_message(raw_line: str, message_keys: tuple) -> str:
    """
    Extract the human-readable message text from a raw log line.

    Strategy (in order):
      1. Parse raw_line as JSON → look for each key in message_keys.
      2. If no key matches, fall back to the raw string.
      3. If the matched value is not a string (e.g. a nested dict),
         serialise it back to compact JSON.
    """
    try:
        parsed = json.loads(raw_line)
        if isinstance(parsed, dict):
            for key in message_keys:
                if key in parsed:
                    value = parsed[key]
                    if not isinstance(value, str):
                        value = json.dumps(value, separators=(",", ":"))
                    return value
    except (json.JSONDecodeError, TypeError):
        pass

    return raw_line  # not JSON or no matching key — return as-is


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint — survive kill/restart with zero data loss or duplication
# ─────────────────────────────────────────────────────────────────────────────
#
# A checkpoint file sits next to the CSV:
#   tvnz_16th.csv          ← data (appended to on resume)
#   tvnz_16th.csv.ckpt     ← JSON with the last completed chunk boundary
#
# Schema:
#   {
#     "next_chunk_start": <epoch int>,   # first epoch NOT yet written to CSV
#     "rows_written":     <int>,         # rows in CSV so far (excl. header)
#     "started_at":       "<UTC str>",   # when the original run began
#     "updated_at":       "<UTC str>",   # when this checkpoint was last saved
#     "csv_file":         "<path>",      # sanity-check the right CSV
#     "full_start":       <epoch int>,   # original start of the whole job
#     "full_end":         <epoch int>    # original end of the whole job
#   }
#
# Safety rules:
#   • Checkpoint is written AFTER fh.flush() — disk write order is:
#       1. CSV rows flushed   2. Checkpoint updated
#     So a kill between 1 and 2 at worst re-downloads one chunk (safe, no dupes
#     because we open the CSV in append mode and the chunk boundary is exact).
#   • On a clean finish the checkpoint file is deleted.
#   • If the checkpoint references a different CSV path it is ignored.


def _ckpt_path(csv_file: str) -> str:
    return csv_file + ".ckpt"


def read_checkpoint(csv_file: str) -> dict | None:
    """
    Return the saved checkpoint dict for csv_file, or None if not found /
    invalid / mismatched.
    """
    path = _ckpt_path(csv_file)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            ckpt = json.load(f)
        if ckpt.get("csv_file") != csv_file:
            print(f"[{_ts()}] ⚠️  Checkpoint csv_file mismatch — ignoring.")
            return None
        return ckpt
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[{_ts()}] ⚠️  Could not read checkpoint ({exc}) — starting fresh.")
        return None


def write_checkpoint(csv_file: str, next_chunk_start: int,
                     rows_written: int, full_start: int, full_end: int,
                     started_at: str) -> None:
    """Atomically overwrite the checkpoint file."""
    path = _ckpt_path(csv_file)
    data = {
        "next_chunk_start": next_chunk_start,
        "rows_written":     rows_written,
        "started_at":       started_at,
        "updated_at":       _utc(int(time.time())),
        "csv_file":         csv_file,
        "full_start":       full_start,
        "full_end":         full_end,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)   # atomic on all platforms


def clear_checkpoint(csv_file: str) -> None:
    """Delete the checkpoint file after a clean finish."""
    path = _ckpt_path(csv_file)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ID file loader
# ─────────────────────────────────────────────────────────────────────────────

def load_ids_from_file(path: str) -> list:
    """
    Read a flat text file of IDs — one ID per line — and return a deduplicated
    list of non-empty strings.

    Behaviour:
      - Blank lines and lines starting with # are silently skipped.
      - Leading/trailing whitespace is stripped from every line.
      - Duplicate IDs are removed (order preserved via dict).
      - If the file does not exist, is empty, or yields no valid IDs after
        filtering, an empty list is returned and a warning is printed.
        The caller then skips ID filtering entirely.

    Usage:
        MATCH_IDS = load_ids_from_file("tracker_ids.txt")

    File format (tracker_ids.txt):
        # optional comment lines are ignored
        111111111
        222222222
        333333333
    """
    if not path:
        return []

    if not os.path.exists(path):
        print(f"[{_ts()}] WARNING  IDs file not found: '{path}' -- ID filter disabled.")
        return []

    ids = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                ids.append(line)
    except OSError as exc:
        print(f"[{_ts()}] WARNING  Could not read IDs file '{path}': {exc} -- ID filter disabled.")
        return []

    # Deduplicate while preserving insertion order
    ids = list(dict.fromkeys(ids))

    if not ids:
        print(f"[{_ts()}] WARNING  IDs file '{path}' is empty or contains only comments "
              "-- ID filter disabled.")
        return []

    print(f"[{_ts()}] OK  Loaded {len(ids):,} unique ID(s) from '{path}'")
    return ids


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline builder — with ID batching
# ─────────────────────────────────────────────────────────────────────────────

import re as _re


def build_pipelines_batched(
    required_phrases: list,
    match_ids:        list,
    id_batch_size:    int = 100,
) -> list:
    """
    Build Last9 pipeline dicts using operators confirmed by the official API
    docs (https://last9.io/docs/query-logs-api/).

    Valid operators: $eq $neq $contains $notcontains $regex $notregex
                     $gt $lt $gte $lte
    (Note: $containsWords does NOT exist in the API — earlier use was wrong.)

    Strategy
    ────────
    • Phrases  → $contains  (substring match on Body) combined with $and.
    • IDs      → $regex     (one regex matching ANY of the batch's IDs).
                 This is the key efficiency win: instead of one API call per
                 ID, a single regex "id1|id2|id3|…" matches any of them in ONE
                 call.  IDs are regex-escaped and batched (id_batch_size) so no
                 single regex grows large enough for Last9 to reject.

    Modes
    ─────
    A — Phrases only (REQUIRED_PHRASES set, IDS_FILE empty):
        One pipeline.  {"$and": [{"$contains": ["Body", "phrase"]}, ...]}

    B — IDs only (IDS_FILE set, REQUIRED_PHRASES empty):
        One pipeline per batch of id_batch_size IDs.
        {"$and": [{"$regex": ["Body", "id1|id2|id3|…"]}]}

    C — Phrases AND IDs (both set):
        One pipeline per batch; phrases AND'd with the ID regex.
        {"$and": [{"$contains": ["Body", "phrase"]},
                  {"$regex": ["Body", "id1|id2|…"]}]}

    All pipelines run per time chunk; rows stream into one CSV.
    """
    phrase_clauses = [
        {"$contains": ["Body", phrase]} for phrase in required_phrases
    ]

    if not match_ids:
        # Mode A — phrases only
        return [{"query": {"$and": phrase_clauses}, "type": "filter"}]

    pipelines = []
    for i in range(0, len(match_ids), id_batch_size):
        batch = match_ids[i : i + id_batch_size]
        # Tracker IDs are alphanumerics + hyphens. Hyphens are only special
        # inside [..] character classes, not in an alternation, so we escape
        # only genuinely dangerous metacharacters and leave hyphens literal —
        # this keeps the pattern readable and avoids over-escaping.
        def _esc(s: str) -> str:
            return _re.sub(r'([.^$*+?()\[\]{}|\\])', r'\\\1', s)
        pattern = "|".join(_esc(id_val) for id_val in batch)
        id_clause = {"$regex": ["Body", pattern]}

        and_clauses = phrase_clauses + [id_clause] if phrase_clauses else [id_clause]
        pipelines.append({"query": {"$and": and_clauses}, "type": "filter"})

    return pipelines



# ─────────────────────────────────────────────────────────────────────────────
# Core API fetch — true streaming: writes rows directly, never accumulates
# ─────────────────────────────────────────────────────────────────────────────

MAX_RETRIES         = 10
MAX_400_RETRIES     = 3        # 400s can be transient (seen recovering after 1 retry);
                               # give up after 3 rather than all 10
BASE_BACKOFF_SECS   = 1        # 2^0 on first retry
MAX_BACKOFF_SECS    = 300      # cap at 5 minutes


def fetch_logs_to_writer(
    base_url:        str,
    writer:          csv.writer,
    pipeline:        list | None = None,
    direction:       str = "backward",
    index:           str | None = None,
    region:          str | None = None,
    step:            str = "200ms",
    limit:           int = 10_000,
    start_epoch:     int | None = None,
    end_epoch:       int | None = None,
    time_range_hours: int = 1,
    request_timeout: int = 120,
    message_keys:    tuple = ("message", "Message", "Body", "body", "msg"),
    running_total:   list | None = None,   # [int] — mutable counter shared with caller
    quiet:           bool = False,         # suppress per-window header + 0-row page lines
) -> int:
    """
    Fetch all log lines for a single time window from the Last9 v2 API and
    write each row directly to `writer` as it arrives.

    This is the core of the true-streaming design:
      • No list ever accumulates in this function.
      • Each API page is parsed → rows written → response object released.
      • `running_total` (a one-element list) lets the caller share a live
        cumulative count across all chunks without any global variable.

    Retry policy (exponential backoff, up to MAX_RETRIES attempts):
      • 502 / 503 / 504   gateway errors
      • 401               token expiry  (triggers refresh then retries)
      • Timeouts          (requests.exceptions.Timeout)
      • Any other HTTP error raised by raise_for_status()

    Returns
    -------
    int : Number of rows written by this call (single time window).
    """
    if running_total is None:
        running_total = [0]

    if end_epoch is None:
        end_epoch = int(time.time())
    if start_epoch is None:
        start_epoch = end_epoch - time_range_hours * 3600

    request_body: dict = {}
    if pipeline:
        # Last9 expects: {"pipeline": [{...}]}
        # pipeline here is a single dict — wrap it in a list.
        request_body["pipeline"] = pipeline if isinstance(pipeline, list) else [pipeline]

    endpoint = f"{base_url}/logs/api/v2/query_range/json"
    rows_this_window = 0
    offset = 0

    if not quiet:
        print(f"[{_ts()}]  Range : {_utc(start_epoch)} UTC → {_utc(end_epoch)} UTC")
        if index:
            print(f"[{_ts()}]  Index : {index}")
        if region:
            print(f"[{_ts()}]  Region: {region}")

    while True:
        # ── Build request ──────────────────────────────────────────────────
        api_token = get_access_token()
        headers = {
            "X-LAST9-API-TOKEN": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        params: dict = {
            "start":     start_epoch,
            "end":       end_epoch,
            "limit":     limit,
            "direction": direction,
            "step":      step,
            "offset":    offset,
        }
        if index:
            params["index"] = index
        if region:
            params["region"] = region

        def _do_request() -> requests.Response:
            return requests.post(
                endpoint,
                headers=headers,
                params=params,
                json=request_body,
                timeout=request_timeout,
            )

        # ── Retry loop (exponential backoff on ALL error types) ────────────
        response = None
        last_exc  = None

        for attempt in range(MAX_RETRIES):
            wait_secs = min(BASE_BACKOFF_SECS * (2 ** attempt), MAX_BACKOFF_SECS)
            try:
                response  = _do_request()
                last_exc  = None

                # ── Token expiry: refresh and retry within same attempt ────
                token_expired = (
                    response.status_code == 401 or
                    (response.status_code == 200 and
                     "Authorization token is expired" in response.text)
                )
                if token_expired:
                    print(f"[{_ts()}] 🔄 Token expired (attempt {attempt + 1}/{MAX_RETRIES}) "
                          f"— refreshing...")
                    new_token = refresh_access_token()
                    if new_token:
                        headers["X-LAST9-API-TOKEN"] = f"Bearer {new_token}"
                        response = _do_request()
                    else:
                        print(f"[{_ts()}] ❌ Token refresh failed — will retry after {wait_secs}s")
                        time.sleep(wait_secs)
                        continue

                # ── 4xx handling ──────────────────────────────────────────
                # 400 "parse error: invalid JSON pipeline" is intermittent:
                # observed recovering after 1 retry, but also failing for all
                # subsequent pages in a window. Allow up to MAX_400_RETRIES
                # quick retries (5s fixed), then fast-fail the page.
                # All other 4xx (403, 404, 429 etc.) are permanent — fail fast.
                if 400 <= response.status_code < 500 and response.status_code != 401:
                    if response.status_code == 400 and attempt < MAX_400_RETRIES - 1:
                        print(f"[{_ts()}] ⚠️  HTTP 400 (attempt {attempt + 1}/{MAX_400_RETRIES}) "
                              f"— retrying in 5s...")
                        print(f"[{_ts()}]    Body: {response.text[:300]}")
                        time.sleep(5)
                        continue
                    else:
                        label = (f"400 (all {MAX_400_RETRIES} quick retries exhausted)"
                                 if response.status_code == 400
                                 else f"HTTP {response.status_code} (permanent client error)")
                        print(f"[{_ts()}] ❌ {label} — skipping this page.")
                        print(f"[{_ts()}]    Body: {response.text[:300]}")
                        response = None
                        break

                # ── 5xx / gateway errors warrant a retry ──────────────────
                if response.status_code in (500, 502, 503, 504):
                    print(f"[{_ts()}] ⚠️  HTTP {response.status_code} "
                          f"(attempt {attempt + 1}/{MAX_RETRIES}) "
                          f"— retrying in {wait_secs}s...")
                    time.sleep(wait_secs)
                    continue

                # ── Raise on any remaining HTTP error ─────────────────────
                response.raise_for_status()

                # ── Success: break out of retry loop ──────────────────────
                break

            except requests.exceptions.Timeout as exc:
                last_exc = exc
                print(f"[{_ts()}] ⚠️  Timeout after {request_timeout}s "
                      f"(attempt {attempt + 1}/{MAX_RETRIES}) "
                      f"— retrying in {wait_secs}s...")
                time.sleep(wait_secs)

            except requests.exceptions.HTTPError as exc:
                last_exc = exc
                status = exc.response.status_code if exc.response is not None else 0
                print(f"[{_ts()}] ⚠️  HTTP error {status} "
                      f"(attempt {attempt + 1}/{MAX_RETRIES}) "
                      f"— retrying in {wait_secs}s...")
                if exc.response is not None:
                    print(f"[{_ts()}]    Body: {exc.response.text[:300]}")
                time.sleep(wait_secs)

            except requests.exceptions.RequestException as exc:
                last_exc = exc
                print(f"[{_ts()}] ⚠️  Request failed: {exc} "
                      f"(attempt {attempt + 1}/{MAX_RETRIES}) "
                      f"— retrying in {wait_secs}s...")
                time.sleep(wait_secs)

        else:
            # All MAX_RETRIES exhausted
            print(f"[{_ts()}] ❌ All {MAX_RETRIES} retries exhausted for this page. "
                  f"Last error: {last_exc or 'HTTP error'}")
            print(f"[{_ts()}]    Skipping remainder of this time window.")
            break

        if response is None:
            break

        # ── Parse response (soft expiry embedded in 200 body) ─────────────
        try:
            data = response.json()
        except ValueError:
            print(f"[{_ts()}] ❌ Could not parse JSON response: {response.text[:300]}")
            break

        # Handle soft expiry error in a 200 response body
        if isinstance(data, dict) and data.get("error") == "Authorization token is expired":
            print(f"[{_ts()}] ❌ Soft token expiry in 200 body — could not recover.")
            break

        try:
            results = data["data"]["result"] or []
        except KeyError as exc:
            print(f"[{_ts()}] ❌ Unexpected response format — missing key: {exc}")
            print(f"[{_ts()}]    Response preview: {response.text[:300]}")
            break

        # ── Stream rows directly to CSV writer — zero accumulation ────────
        page_rows = 0
        for stream in results:
            for _ts_val, raw_line in stream.get("values", []):
                message_text = _extract_message(raw_line, message_keys)
                writer.writerow([message_text])
                page_rows += 1

        rows_this_window   += page_rows
        running_total[0]   += page_rows
        log_line_count      = page_rows   # same value, used for pagination check

        batch_num = offset // limit + 1
        # In quiet mode only print pages that actually returned rows — keeps
        # the log readable when most ID batches legitimately return 0.
        if not quiet or page_rows > 0:
            print(f"[{_ts()}]   Page {batch_num:>3}: {page_rows:>7,} rows  │  "
                  f"total downloaded: {running_total[0]:>10,}")
            stats = data.get("data", {}).get("stats", {}).get("summary", {})
            if stats and not quiet:
                print(f"[{_ts()}]   Stats : "
                      f"{stats.get('totalLinesProcessed', 'N/A')} lines processed  │  "
                      f"exec: {stats.get('execTime', 'N/A')}s")

        # Release the response object — nothing from it held beyond this point
        del data, results
        response = None

        # ── Pagination: stop when last page returned fewer rows than limit ─
        if log_line_count < limit:
            break

        offset += limit

    return rows_this_window


# ─────────────────────────────────────────────────────────────────────────────
# Chunked orchestrator — opens CSV once, streams all chunks into it
# ─────────────────────────────────────────────────────────────────────────────

def fetch_logs_chunked_to_csv(
    base_url:           str,
    pipelines:          list,          # list of pipeline dicts (one per ID batch)
    index:              str,
    region:             str,
    start_epoch:        int,
    end_epoch:          int,
    csv_file:           str,
    chunk_hours:        int = 1,
    message_keys:       tuple = ("message", "Message", "Body", "body", "msg"),
    inter_chunk_sleep:  float = 2.0,
) -> int:
    """
    Fetch logs in time-based chunks, across all ID batches, into one CSV file.
    Supports resume after kill/crash via checkpoint.

    ID batching
    ───────────
    When MATCH_IDS is large (hundreds–thousands), build_pipelines_batched()
    splits them into multiple pipelines of ID_BATCH_SIZE each.  For every
    time chunk this function runs ALL pipeline batches and streams all results
    into the same CSV.  The effect is identical to one giant $or query but
    without triggering Last9's pipeline size limit.

    Resume behaviour
    ────────────────
    Checkpoint is saved after every time chunk (all batches within it done).
    On restart the script skips completed chunks and appends to the CSV.
    A kill mid-chunk replays that entire chunk on resume (no duplicates because
    time windows are non-overlapping).
    """
    chunk_seconds = chunk_hours * 3600
    total_chunks  = -(-( end_epoch - start_epoch) // chunk_seconds)   # ceil div

    # ── Check for an existing checkpoint ─────────────────────────────────────
    ckpt = read_checkpoint(csv_file)

    if ckpt:
        resumed_from = ckpt["next_chunk_start"]
        rows_already = ckpt["rows_written"]
        started_at   = ckpt["started_at"]
        csv_mode     = "a"   # append — do NOT write header again

        skipped = (resumed_from - start_epoch) // chunk_seconds
        remaining = -(-( end_epoch - resumed_from) // chunk_seconds)

        print(f"\n[{_ts()}] ════════════════════════════════════════════════════════")
        print(f"[{_ts()}]  ♻️  RESUMING from checkpoint → {csv_file}")
        print(f"[{_ts()}]  Original start : {_utc(start_epoch)} UTC")
        print(f"[{_ts()}]  Resumed from   : {_utc(resumed_from)} UTC  "
              f"(skipping {skipped} completed chunk(s))")
        print(f"[{_ts()}]  Rows already   : {rows_already:,}")
        print(f"[{_ts()}]  Chunks left    : {remaining} of {total_chunks}")
        print(f"[{_ts()}] ════════════════════════════════════════════════════════\n")

        chunk_start   = resumed_from
        chunk_num     = skipped          # so "Chunk N/total" numbering continues
        running_total = [rows_already]

    else:
        started_at    = _utc(int(time.time()))
        csv_mode      = "w"   # fresh run — overwrite / create
        chunk_start   = start_epoch
        chunk_num     = 0
        running_total = [0]

        print(f"\n[{_ts()}] ════════════════════════════════════════════════════════")
        print(f"[{_ts()}]  Streaming fetch → {csv_file}")
        print(f"[{_ts()}]  Full range : {_utc(start_epoch)} UTC → {_utc(end_epoch)} UTC")
        print(f"[{_ts()}]  Chunk size : {chunk_hours}h  │  Total chunks: {total_chunks}")
        print(f"[{_ts()}] ════════════════════════════════════════════════════════\n")

    with open(csv_file, csv_mode, newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)

        if csv_mode == "w":
            writer.writerow(["message"])   # header only on fresh run

        while chunk_start < end_epoch:
            chunk_end  = min(chunk_start + chunk_seconds, end_epoch)
            chunk_num += 1

            print(f"[{_ts()}] ── Chunk {chunk_num}/{total_chunks} "
                  f"─────────────────────────────────────────")
            print(f"[{_ts()}]    {_utc(chunk_start)} UTC → {_utc(chunk_end)} UTC")

            # ── Run every ID batch for this time window ───────────────
            chunk_rows  = 0
            n_batches   = len(pipelines)
            for b_idx, pipeline in enumerate(pipelines, start=1):
                batch_rows = fetch_logs_to_writer(
                    base_url      = base_url,
                    writer        = writer,
                    pipeline      = pipeline,
                    index         = index,
                    region        = region,
                    start_epoch   = chunk_start,
                    end_epoch     = chunk_end,
                    message_keys  = message_keys,
                    running_total = running_total,
                    quiet         = (n_batches > 1),   # quiet when many batches
                )
                chunk_rows += batch_rows
                # Progress line per batch — shows hits, running total, and a
                # heartbeat every 10 batches even when they're empty.
                if batch_rows > 0:
                    print(f"[{_ts()}]   batch {b_idx:>3}/{n_batches}  "
                          f"+{batch_rows:>6,} rows  │  chunk so far: {chunk_rows:>8,}  "
                          f"│  total: {running_total[0]:>10,}")
                elif b_idx % 10 == 0 or b_idx == n_batches:
                    print(f"[{_ts()}]   batch {b_idx:>3}/{n_batches}  "
                          f"(scanning…)  │  chunk so far: {chunk_rows:>8,}  "
                          f"│  total: {running_total[0]:>10,}")
                if b_idx < n_batches:
                    time.sleep(1)   # brief pause between batches

            # ── Step 1: flush CSV rows to disk ────────────────────────────
            fh.flush()

            # ── Step 2: advance checkpoint (safe order) ───────────────────
            write_checkpoint(
                csv_file        = csv_file,
                next_chunk_start = chunk_end,
                rows_written    = running_total[0],
                full_start      = start_epoch,
                full_end        = end_epoch,
                started_at      = started_at,
            )

            print(f"[{_ts()}]  ✅ Chunk {chunk_num} done — "
                  f"{chunk_rows:,} rows  │  running total: {running_total[0]:,}  "
                  f"│  checkpoint saved")

            if chunk_start + chunk_seconds < end_epoch:
                time.sleep(inter_chunk_sleep)

            chunk_start = chunk_end

    # ── Clean finish: remove checkpoint ──────────────────────────────────────
    clear_checkpoint(csv_file)

    print(f"\n[{_ts()}] ════════════════════════════════════════════════════════")
    print(f"[{_ts()}]  ✅ All done!  {running_total[0]:,} rows → {csv_file}")
    print(f"[{_ts()}]  Checkpoint cleared.")
    print(f"[{_ts()}] ════════════════════════════════════════════════════════\n")
    return running_total[0]


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # ── Credentials & config ──────────────────────────────────────────────────
    #
    # Option A (recommended) — supply a refresh token; the script exchanges it
    #   for an access token at startup and auto-refreshes mid-run if needed:
    #     set LAST9_REFRESH_TOKEN=eyJhbGci...
    #
    # Option B — supply a short-lived access token directly (expires in 24 h).
    #   Auto-refresh will still work if LAST9_REFRESH_TOKEN is also set:
    #     set LAST9_API_TOKEN=eyJhbGci...
    #
    REFRESH_TOKEN = os.getenv("LAST9_REFRESH_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODQ1MTAyNjYzLCJuYmYiOjE3ODE5NDQyNjMsImlhdCI6MTc4MTk0NDI2MywianRpIjoiZGNiNmNlMzItNzY3NC00NzFkLWFmNzMtZTk5Y2NlNDAyZTJmIiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnRhcHNlMSIsInRva2VuX2lkIjoiNDc0NmQyMTQtMjI0Ny00OWUwLTk1ZTMtZjU0ZTU4MWQzNDE5In0.PRqkmVNfUGfBj7iiM-Diu8tawJhdYVL_yBV2wMjV6Zk")
    API_TOKEN     = os.getenv("LAST9_API_TOKEN",     "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxNzgyMjAzNDg5LCJuYmYiOjE3ODE5NDQyODksImlhdCI6MTc4MTk0NDI4OSwianRpIjoiN2EyNzFjMjEtMzgzMy00Yjk0LTg3ZmYtOWIxMjg5NTdhOTM0Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6ImFjY2Vzc190b2tlbiIsImVtYWlsIjoibWFub2pAZXZlcmdlbnQuY29tIiwib3JnYW5pemF0aW9uX3NsdWciOiJldmVyZ2VudGFwc2UxIiwidG9rZW5faWQiOiJmOWE2M2FjYy0yYjRkLTQyNzYtYjA5OS0xOTMwYjdjN2JmZDMiLCJyZWZyZXNoX3Rva2VuX2lkIjoiNDc0NmQyMTQtMjI0Ny00OWUwLTk1ZTMtZjU0ZTU4MWQzNDE5In0.voapsuTXWZY65Xl-ve--9h1vk5-SwowJqGuCqpLRzv8")

    ORG_SLUG  = os.getenv("LAST9_ORG_SLUG",   "evergentapse1")
    REGION    = os.getenv("LAST9_REGION",     "ap-southeast-1")
    BASE_URL  = f"https://app.last9.io/api/v4/organizations/{ORG_SLUG}"

    # ── Initialise tokens ─────────────────────────────────────────────────────
    active_token = init_tokens(
        api_token     = API_TOKEN,
        refresh_token = REFRESH_TOKEN,
    )

    if not active_token:
        raise SystemExit("❌  No valid access token available. "
                         "Set LAST9_REFRESH_TOKEN or LAST9_API_TOKEN and try again.")

    # ── Time range ────────────────────────────────────────────────────────────
    _DEFAULT_START = safe_epoch(2026, 6, 15, 18, 44, 0)
    _DEFAULT_END   = safe_epoch(2026, 6, 15, 21, 16, 0)

    START_EPOCH = int(os.getenv("LAST9_START_EPOCH", str(_DEFAULT_START)))
    END_EPOCH   = int(os.getenv("LAST9_END_EPOCH",   str(_DEFAULT_END)))

    # ── Chunking ──────────────────────────────────────────────────────────────
    CHUNK_HOURS   = int(os.getenv("LAST9_CHUNK_HOURS",   "1"))

    # One pipeline per ID (Last9 $or across IDs returns 0 results silently).
    # IDs per regex batch. 100 is safe; raise to reduce calls, lower if a
    # regex grows too large and Last9 rejects it (rare).
    ID_BATCH_SIZE = int(os.getenv("LAST9_ID_BATCH_SIZE", "100"))

    # ── Output file ───────────────────────────────────────────────────────────
    OUTPUT_CSV = os.getenv("LAST9_OUTPUT", "tvnz_15th_trackerids_v6.csv")

    # ─────────────────────────────────────────────────────────────────────────
    # SEARCH CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────
    #
    # Three modes — configure by setting REQUIRED_PHRASES and/or IDS_FILE:
    #
    #  Mode A — Phrases only   (set REQUIRED_PHRASES, leave IDS_FILE = "")
    #    Returns all logs where Body contains ALL listed phrases.
    #    operator: $contains (substring match)
    #
    #  Mode B — IDs only       (leave REQUIRED_PHRASES = [], set IDS_FILE)
    #    Returns all logs where Body contains ANY of the tracker/customer IDs.
    #    IDs are searched as exact substrings ($contains).
    #    Batched automatically — safe for thousands of IDs.
    #
    #  Mode C — Phrases AND IDs  (set both)
    #    Phrases must ALL match AND at least one ID must match.
    #
    # ── Required phrases (ALL must match — AND) ───────────────────────────────
    # Leave empty [] to use IDs-only mode (Mode B).
    REQUIRED_PHRASES = [
        # "GetEntitlementsRequestMessage",
        # "data comes from request",
        # add phrases here, or leave empty for ID-only search
    ]

    # ── IDs file (ANY one must match — OR) ────────────────────────────────────
    # Plain-text file, one tracker/customer ID per line.
    # Lines starting with # and blank lines are ignored.
    # Duplicates removed automatically.
    # Set to "" to disable — use phrases only (Mode A).
    #
    # Example  tracker_ids.txt:
    #   # one tracker ID per line
    #   TVNZ-1-6a306b15-253b590e7394fbdf06a58839
    #   TVNZ-1-6a306b14-61c9e8f40fd303ea25a8d09c
    #
    IDS_FILE = os.getenv("LAST9_IDS_FILE", "tracker_ids.txt")

    MATCH_IDS = load_ids_from_file(IDS_FILE) if IDS_FILE else []

    # ─────────────────────────────────────────────────────────────────────────
    # PIPELINE BUILDER  — do not edit below unless changing operator logic
    # ─────────────────────────────────────────────────────────────────────────

    if not REQUIRED_PHRASES and not MATCH_IDS:
        raise SystemExit(
            "❌  Nothing to search for.\n"
            "    Set REQUIRED_PHRASES and/or point IDS_FILE at a valid IDs file."
        )

    # Determine mode for banner
    if REQUIRED_PHRASES and MATCH_IDS:
        _mode = "C — Phrases AND IDs"
    elif MATCH_IDS:
        _mode = "B — IDs only"
    else:
        _mode = "A — Phrases only"

    PIPELINES = build_pipelines_batched(
        required_phrases = REQUIRED_PHRASES,
        match_ids        = MATCH_IDS,
        id_batch_size    = ID_BATCH_SIZE,
    )
    _n_batches = len(PIPELINES)

    # ── Summary banner ────────────────────────────────────────────────────────
    print("=" * 66)
    print("  Last9 Log Fetcher — True Streaming CSV Export")
    print("=" * 66)
    print(f"  Org      : {ORG_SLUG}")
    print(f"  Region   : {REGION}")
    print(f"  Index    : physical_index:UMServices")
    print(f"  From     : {_utc(START_EPOCH)} UTC  ({START_EPOCH})")
    print(f"  To       : {_utc(END_EPOCH)} UTC  ({END_EPOCH})")
    print(f"  Chunks   : {CHUNK_HOURS}h each")
    print(f"  Output   : {OUTPUT_CSV}")
    print(f"  Retries  : {MAX_RETRIES} attempts, exponential backoff (cap {MAX_BACKOFF_SECS}s)")
    print(f"  Mode     : {_mode}")
    print(f"  Filter   :")
    if REQUIRED_PHRASES:
        print(f"    Phrases (ALL must match — $contains):")
        for phrase in REQUIRED_PHRASES:
            print(f"      • \"{phrase}\"")
    if MATCH_IDS:
        ids_src = f"'{IDS_FILE}'"
        print(f"    IDs (ANY match via $regex)  "
              f"[{len(MATCH_IDS):,} IDs from {ids_src}  →  "
              f"{_n_batches} regex batch(es) of ≤{ID_BATCH_SIZE} per time chunk]:")
        for id_val in MATCH_IDS[:5]:
            print(f"      • {id_val}")
        if len(MATCH_IDS) > 5:
            print(f"      … and {len(MATCH_IDS) - 5:,} more")
    else:
        print(f"    IDs  : (none)")
    token_src = "refresh token (auto-managed)" if REFRESH_TOKEN else "static access token"
    print(f"  Auth     : {token_src}")

    _existing_ckpt = read_checkpoint(OUTPUT_CSV)
    if _existing_ckpt:
        print(f"  Resume   : ♻️  checkpoint found — will continue from "
              f"{_utc(_existing_ckpt['next_chunk_start'])} UTC  "
              f"({_existing_ckpt['rows_written']:,} rows already written)")
    else:
        print(f"  Resume   : no checkpoint — fresh run")
    print("=" * 66 + "\n")

    # ── Main fetch → CSV ──────────────────────────────────────────────────────
    total_rows = fetch_logs_chunked_to_csv(
        base_url    = BASE_URL,
        pipelines   = PIPELINES,
        index       = "physical_index:UMServices",
        region      = REGION,
        start_epoch = START_EPOCH,
        end_epoch   = END_EPOCH,
        csv_file    = OUTPUT_CSV,
        chunk_hours = CHUNK_HOURS,
        message_keys = ("message", "Message", "Body", "body", "msg"),
    )

    print(f"[{_ts()}] Output file : {OUTPUT_CSV}")
    print(f"[{_ts()}] Total rows  : {total_rows:,}")
