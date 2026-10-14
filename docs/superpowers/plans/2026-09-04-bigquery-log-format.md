# BigQuery Log Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `bigquery` output format that parses Evergent application logs into a fixed 6-column CSV ready for BigQuery ingestion: `bu_name | timestamp | session_token | sp_account_id | api_name | channel_partner_id`.

**Architecture:** A new `bq_formatter.py` module detects the two known log patterns (Format A: ClassName/command; Format B: Controller/XML request) via cheap string hints before regex, extracts the 6 fields, and returns a `BQRow` dataclass. `runner.py` uses it as a new `fmt == "bigquery"` branch — streaming directly to a `.bq.csv` file with no post-processing. The frontend wizard gets a third option in the Output format selector.

**Tech Stack:** Python 3.11, `re` (stdlib), `dataclasses` (stdlib), React/TypeScript (Next.js App Router)

## Global Constraints

- Never accumulate rows in memory — write each row as it arrives
- All new Python code: Black-formatted, type hints required
- Test file mirrors the module path: `worker/tests/test_bq_formatter.py`
- `bq.csv` extension distinguishes BigQuery output from raw CSV
- Unmatched rows are skipped (not written) and counted
- Existing `csv`, `jsonl` paths in `runner.py` must not change

---

### Task 1: Parser module `bq_formatter.py`

**Files:**
- Create: `worker/app/last9/bq_formatter.py`
- Create: `worker/tests/test_bq_formatter.py`
- Modify: `worker/app/last9/__init__.py`

**Interfaces:**
- Produces: `parse_bq_row(message: str, timestamp: str) -> BQRow | None`
- Produces: `BQRow(bu_name, timestamp, session_token, sp_account_id, api_name, channel_partner_id)` — all `str`

---

- [ ] **Step 1: Write the failing tests**

Create `worker/tests/test_bq_formatter.py`:

```python
"""Tests for BQ log line parser."""
from app.last9.bq_formatter import BQRow, parse_bq_row


# ── Format A samples ──────────────────────────────────────────────────────────

AHA_LINE = (
    "AHA-1-6a9a915b-48da52e15d3f654156570481 - ClassName CGetEntitlementsCommand"
    " SPAccountId 241230090725797443495533 in BU AHA INDIA API User ahaapiuser"
)

EKKL_LINE = (
    "Pinnacle-1-6a9a930a-0fcc40f21336225559bf1464 - ClassName CGetOAuthAccessTokenCommand"
    " SPAccountId 260904093229112484608283 in BU Ekkl API User EkklWebApiUser"
)

MARQUEE_LINE = (
    "Marquee-1-6a9a951e-3ee450ed0670d98a40ba113d - ClassName GetOAuthAccessTokenCommand"
    " SPAccountId 250404142056048402406598 in BU Marquee API User MKClientapiuser"
)

# ── Format B samples ──────────────────────────────────────────────────────────

ABSCBN_LINE = (
    "ABSCBN-1-6a9a91a4-73c12a735fa51a0567d87320 - ABSCBNController getContactPostAction"
    " -- data comes from request:<GetContactRequestMessage>"
    "<cpCustomerID>f670dbde-bff7-4bca-8d27-30ce9f62b0f0</cpCustomerID>"
    "<channelPartnerID>ABSCBN</channelPartnerID>"
    "<apiUser>abscbnapiuser</apiUser></GetContactRequestMessage>"
)

FA_LINE = (
    "FA-1-6a9a6c2b-7a210ff006c02c3f6c3262a9 - In FAController addSubscriptionPostAction"
    " -- data comes from request :<AddSubscriptionRequestMessage>"
    "<spAccountID>78493126</spAccountID>"
    "<channelPartnerID>FA</channelPartnerID>"
    "</AddSubscriptionRequestMessage>"
)

VIKI_LINE = (
    "VIKI-1-6a9a96fb-4e40d57f4074e74c4615a705 - getProductsPostAction"
    " -- data comes from request : <GetProductsRequestMessage>"
    "<spAccountID>129169649u</spAccountID>"
    "<channelPartnerID>VIKI</channelPartnerID>"
    "</GetProductsRequestMessage>"
)

TS = "2026-09-04T10:00:00Z"


# ── Format A tests ────────────────────────────────────────────────────────────

def test_format_a_aha():
    row = parse_bq_row(AHA_LINE, TS)
    assert row is not None
    assert row.bu_name == "AHA INDIA"
    assert row.session_token == "AHA-1-6a9a915b-48da52e15d3f654156570481"
    assert row.sp_account_id == "241230090725797443495533"
    assert row.api_name == "CGetEntitlementsCommand"
    assert row.channel_partner_id == ""
    assert row.timestamp == TS


def test_format_a_ekkl():
    row = parse_bq_row(EKKL_LINE, TS)
    assert row is not None
    assert row.bu_name == "Ekkl"
    assert row.session_token == "Pinnacle-1-6a9a930a-0fcc40f21336225559bf1464"
    assert row.sp_account_id == "260904093229112484608283"
    assert row.api_name == "CGetOAuthAccessTokenCommand"
    assert row.channel_partner_id == ""


def test_format_a_marquee():
    row = parse_bq_row(MARQUEE_LINE, TS)
    assert row is not None
    assert row.bu_name == "Marquee"
    assert row.session_token == "Marquee-1-6a9a951e-3ee450ed0670d98a40ba113d"
    assert row.sp_account_id == "250404142056048402406598"
    assert row.api_name == "GetOAuthAccessTokenCommand"


def test_format_a_with_channel_partner_in_xml():
    line = AHA_LINE.rstrip() + " <channelPartnerID>AHACHAN</channelPartnerID>"
    row = parse_bq_row(line, TS)
    assert row is not None
    assert row.channel_partner_id == "AHACHAN"


# ── Format B tests ────────────────────────────────────────────────────────────

def test_format_b_abscbn():
    row = parse_bq_row(ABSCBN_LINE, TS)
    assert row is not None
    assert row.bu_name == "ABSCBN"
    assert row.session_token == "ABSCBN-1-6a9a91a4-73c12a735fa51a0567d87320"
    assert row.sp_account_id == "f670dbde-bff7-4bca-8d27-30ce9f62b0f0"
    assert row.api_name == "getContactPostAction"
    assert row.channel_partner_id == "ABSCBN"


def test_format_b_fa():
    row = parse_bq_row(FA_LINE, TS)
    assert row is not None
    assert row.bu_name == "FA"
    assert row.sp_account_id == "78493126"
    assert row.api_name == "addSubscriptionPostAction"
    assert row.channel_partner_id == "FA"


def test_format_b_viki():
    row = parse_bq_row(VIKI_LINE, TS)
    assert row is not None
    assert row.bu_name == "VIKI"
    assert row.sp_account_id == "129169649u"
    assert row.api_name == "getProductsPostAction"
    assert row.channel_partner_id == "VIKI"


def test_format_b_missing_channel_partner_id():
    line = FA_LINE.replace("<channelPartnerID>FA</channelPartnerID>", "")
    row = parse_bq_row(line, TS)
    assert row is not None
    assert row.channel_partner_id == "-"


def test_format_b_sp_account_id_fallback_to_cp_customer_id():
    # When spAccountID absent, fall back to cpCustomerID
    line = ABSCBN_LINE  # ABSCBN has cpCustomerID, not spAccountID
    row = parse_bq_row(line, TS)
    assert row is not None
    assert row.sp_account_id == "f670dbde-bff7-4bca-8d27-30ce9f62b0f0"


# ── Unknown format ────────────────────────────────────────────────────────────

def test_unknown_format_returns_none():
    assert parse_bq_row("some random log line with no structure", TS) is None


def test_empty_returns_none():
    assert parse_bq_row("", TS) is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd worker
pytest tests/test_bq_formatter.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.last9.bq_formatter'`

- [ ] **Step 3: Implement `bq_formatter.py`**

Create `worker/app/last9/bq_formatter.py`:

```python
"""Parse Evergent application log lines into the BigQuery 6-column schema.

Two known formats:
  A – ClassName/command:  {token} - ClassName {api} SPAccountId {id} in BU {bu} API User {user}
  B – Controller/XML:     {token} - [In] [Controller] {action} -- data comes from request: <xml>

Detection is by cheap ``in`` hint before any regex runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Format A ──────────────────────────────────────────────────────────────────

_FORMAT_A_HINT = "ClassName "
_FORMAT_A_RE = re.compile(
    r"^(?P<session_token>(?P<customer>[A-Za-z0-9]+)-\d+-[0-9a-f]+-[0-9a-f]+)"
    r"\s+-\s+ClassName\s+(?P<api_name>\S+)"
    r"\s+SPAccountId\s+(?P<sp_account_id>\S+)"
    r"\s+in\s+BU\s+(?P<bu_name>.+?)\s+API\s+User\s+\S+"
)

# ── Format B ──────────────────────────────────────────────────────────────────

_FORMAT_B_HINT = "-- data comes from request"
_TOKEN_RE = re.compile(
    r"^(?P<session_token>(?P<customer>[A-Za-z0-9]+)-\d+-[0-9a-f]+-[0-9a-f]+)"
)
_ACTION_RE = re.compile(r"(\w+)\s+--\s+data comes from request")
_CHANNEL_PARTNER_RE = re.compile(r"<channelPartnerID>([^<]+)</channelPartnerID>")
_SP_ACCOUNT_RE = re.compile(r"<spAccountID>([^<]+)</spAccountID>")
_CP_CUSTOMER_RE = re.compile(r"<cpCustomerID>([^<]+)</cpCustomerID>")

# Also used by Format A when XML happens to be present
_CHANNEL_PARTNER_RE_XML = _CHANNEL_PARTNER_RE


@dataclass
class BQRow:
    bu_name: str
    timestamp: str
    session_token: str
    sp_account_id: str
    api_name: str
    channel_partner_id: str


def parse_bq_row(message: str, timestamp: str) -> BQRow | None:
    """Return a BQRow or None if the message matches neither known pattern."""
    if not message:
        return None
    if _FORMAT_A_HINT in message:
        return _parse_format_a(message, timestamp)
    if _FORMAT_B_HINT in message:
        return _parse_format_b(message, timestamp)
    return None


def _parse_format_a(message: str, timestamp: str) -> BQRow | None:
    m = _FORMAT_A_RE.match(message)
    if m is None:
        return None
    cp_m = _CHANNEL_PARTNER_RE_XML.search(message)
    return BQRow(
        bu_name=m.group("bu_name"),
        timestamp=timestamp,
        session_token=m.group("session_token"),
        sp_account_id=m.group("sp_account_id"),
        api_name=m.group("api_name"),
        channel_partner_id=cp_m.group(1) if cp_m else "",
    )


def _parse_format_b(message: str, timestamp: str) -> BQRow | None:
    token_m = _TOKEN_RE.match(message)
    action_m = _ACTION_RE.search(message)
    if token_m is None or action_m is None:
        return None

    cp_m = _CHANNEL_PARTNER_RE.search(message)
    sp_m = _SP_ACCOUNT_RE.search(message)
    cpc_m = _CP_CUSTOMER_RE.search(message)

    sp_account_id = (sp_m or cpc_m)
    return BQRow(
        bu_name=token_m.group("customer"),
        timestamp=timestamp,
        session_token=token_m.group("session_token"),
        sp_account_id=sp_account_id.group(1) if sp_account_id else "",
        api_name=action_m.group(1),
        channel_partner_id=cp_m.group(1) if cp_m else "-",
    )


__all__ = ["BQRow", "parse_bq_row"]
```

- [ ] **Step 4: Run tests to confirm they pass**

```
cd worker
pytest tests/test_bq_formatter.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 5: Export from `worker/app/last9/__init__.py`**

Add to the imports block (after the `from .formats import ...` line):

```python
from .bq_formatter import BQRow, parse_bq_row
```

Add to `__all__` (keep alphabetical):

```python
    "BQRow",
    ...
    "parse_bq_row",
```

- [ ] **Step 6: Verify import works**

```
cd worker
python -c "from app.last9 import BQRow, parse_bq_row; print('ok')"
```

Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add worker/app/last9/bq_formatter.py worker/app/last9/__init__.py worker/tests/test_bq_formatter.py
git commit -m "feat: add BQ log formatter — parse_bq_row for 6-column BigQuery output"
```

---

### Task 2: Runner integration

**Files:**
- Modify: `worker/app/runner.py`

**Interfaces:**
- Consumes: `parse_bq_row(message: str, timestamp: str) -> BQRow | None` from Task 1
- Consumes: `BQRow` — access via `dataclasses.astuple(bq)` for csv row writing

---

- [ ] **Step 1: Add `dataclasses` import and `parse_bq_row` import**

In `worker/app/runner.py`, the existing imports block already has `import dataclasses`? Check first:

```bash
grep -n "^import dataclasses\|from app.last9 import" worker/app/runner.py | head -20
```

Add `import dataclasses` at the top (stdlib imports section) if absent.

Update the `from app.last9 import (` block to include `BQRow` and `parse_bq_row`:

```python
from app.last9 import (
    AggregationError,
    AggregationSpec,
    Aggregator,
    BQRow,          # ← add
    Checkpoint,
    DistinctStore,
    ExtractionSpec,
    FormatMatcher,
    Last9Client,
    Last9Error,
    LogFormat,
    TokenManager,
    TokenSet,
    count_chunks,
    format_log_timestamp,
    iter_extraction,
    parse_bq_row,   # ← add
    store_path,
)
```

- [ ] **Step 2: Update `output_path()` for `.bq.csv` extension**

Current `output_path` (line ~102–104):
```python
def output_path(job_id: int, fmt: str = "csv", customer: str | None = None) -> str:
    ext = "jsonl" if fmt == "jsonl" else "csv"
    return os.path.join(customer_dir(customer), f"job_{job_id}.{ext}")
```

Replace with:
```python
def output_path(job_id: int, fmt: str = "csv", customer: str | None = None) -> str:
    if fmt == "jsonl":
        ext = "jsonl"
    elif fmt == "bigquery":
        ext = "bq.csv"
    else:
        ext = "csv"
    return os.path.join(customer_dir(customer), f"job_{job_id}.{ext}")
```

- [ ] **Step 3: Update file-open header writing**

Find the block that writes the CSV header (~line 295–306):
```python
            if fmt == "csv":
                header = ["timestamp_utc"]
                if aggregator is not None:
                    header += aggregator.parsed_fields
                header.append("message")
                csv.writer(f).writerow(header)
```

Add a sibling branch for `bigquery`:
```python
            if fmt == "csv":
                header = ["timestamp_utc"]
                if aggregator is not None:
                    header += aggregator.parsed_fields
                header.append("message")
                csv.writer(f).writerow(header)
            elif fmt == "bigquery":
                csv.writer(f).writerow(
                    ["bu_name", "timestamp", "session_token",
                     "sp_account_id", "api_name", "channel_partner_id"]
                )
```

- [ ] **Step 4: Add `bq_unmatched` counter and BigQuery write branch in `write_row()`**

Add `bq_unmatched = 0` immediately before the `def write_row(row) -> None:` definition (alongside `written = 0` and `preview_sample`).

Inside `write_row()`, find the `else:` branch (the CSV writer block):
```python
            else:
                cols = [ts]
                if aggregator is not None:
                    cols += parsed or [""] * len(aggregator.parsed_fields)
                cols.append(row.message)
                csv_writer.writerow(cols)
```

Add a new branch **before** the `else:`:
```python
            elif fmt == "bigquery":
                bq = parse_bq_row(row.message, ts)
                if bq is not None:
                    csv_writer.writerow(dataclasses.astuple(bq))
                else:
                    nonlocal bq_unmatched
                    bq_unmatched += 1
```

Because `bq_unmatched` is a closure variable (like `_chunk_hours`), declare it as `bq_unmatched = 0` before `write_row` and reference via `nonlocal`.

Full updated `write_row` shape:
```python
    bq_unmatched = 0

    def write_row(row) -> None:
        nonlocal bq_unmatched
        ts = format_log_timestamp(row.timestamp, "UTC")
        parsed = aggregator.process(row.message) if aggregator is not None else None
        if f is not None:
            if fmt == "jsonl":
                record = {"timestamp": ts, "message": row.message}
                if aggregator is not None:
                    record.update(dict(zip(aggregator.parsed_fields, parsed or [], strict=False)))
                f.write(json.dumps(record) + "\n")
            elif fmt == "bigquery":
                bq = parse_bq_row(row.message, ts)
                if bq is not None:
                    csv_writer.writerow(dataclasses.astuple(bq))
                else:
                    bq_unmatched += 1
            else:
                cols = [ts]
                if aggregator is not None:
                    cols += parsed or [""] * len(aggregator.parsed_fields)
                cols.append(row.message)
                csv_writer.writerow(cols)
        if len(preview_sample) < PREVIEW_CAP:
            preview_sample.append({"timestamp": ts, "message": row.message})
```

- [ ] **Step 5: Include `bq_unmatched` in completion message**

Find the job completion message block (~line 465):
```python
        msg = "Preview ready" if is_preview else "Job completed"
```

After building `msg`, add:
```python
        if fmt == "bigquery" and bq_unmatched > 0:
            msg += f" — {bq_unmatched} row(s) didn't match any BQ log pattern"
```

- [ ] **Step 6: Smoke test the runner change compiles**

```bash
cd worker
python -c "import app.runner; print('ok')"
```

Expected: `ok` (no ImportError or SyntaxError)

- [ ] **Step 7: Commit**

```bash
git add worker/app/runner.py
git commit -m "feat: wire bigquery output format into runner — streams to job_{id}.bq.csv"
```

---

### Task 3: Frontend — Output format selector

**Files:**
- Modify: `web/app/jobs/new/page.tsx` (lines 162, 250, 843–851)

**Interfaces:**
- Consumes: existing `output_format` field on the `createJob` payload (no API change needed)

---

- [ ] **Step 1: Update the format state type (line 162)**

Current:
```typescript
const [format, setFormat] = React.useState<"csv" | "jsonl">("csv");
```

Replace with:
```typescript
const [format, setFormat] = React.useState<"csv" | "jsonl" | "bigquery">("csv");
```

- [ ] **Step 2: Update the clone handler (line 250)**

Current:
```typescript
    setFormat(cloneJob.output_format === "jsonl" ? "jsonl" : "csv");
```

Replace with:
```typescript
    setFormat(
      cloneJob.output_format === "jsonl"
        ? "jsonl"
        : cloneJob.output_format === "bigquery"
        ? "bigquery"
        : "csv"
    );
```

- [ ] **Step 3: Add `bigquery` option to the Output format `<select>` (lines 843–851)**

Current:
```tsx
          <Field label="Output format">
            <select
              className={fieldClass}
              value={format}
              onChange={(e) => setFormat(e.target.value as "csv" | "jsonl")}
            >
              <option value="csv">CSV</option>
              <option value="jsonl">JSONL (one JSON object per line)</option>
            </select>
          </Field>
```

Replace with:
```tsx
          <Field label="Output format">
            <select
              className={fieldClass}
              value={format}
              onChange={(e) => setFormat(e.target.value as "csv" | "jsonl" | "bigquery")}
            >
              <option value="csv">CSV</option>
              <option value="jsonl">JSONL (one JSON object per line)</option>
              <option value="bigquery">BigQuery CSV (6-column)</option>
            </select>
          </Field>
```

- [ ] **Step 4: Run TypeScript check**

```bash
cd web
npm run typecheck
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add web/app/jobs/new/page.tsx
git commit -m "feat: add BigQuery CSV option to output format selector"
```

---

## Self-Review

**Spec coverage:**
- ✅ Format A parsing (bu_name, session_token, sp_account_id, api_name, channel_partner_id from XML or "")
- ✅ Format B parsing (bu_name from token prefix, channel_partner_id from XML or "-", sp_account_id with cpCustomerID fallback)
- ✅ Unmatched rows skipped + counted + reported in completion message
- ✅ `.bq.csv` file extension
- ✅ 6-column header
- ✅ No memory accumulation (streams row by row)
- ✅ Frontend option + clone handler
- ✅ Unit tests for all sample lines from spec

**Placeholder scan:** None found.

**Type consistency:**
- `parse_bq_row` defined in Task 1 and consumed in Task 2 ✓
- `BQRow` fields order used in `dataclasses.astuple()` matches header order: `bu_name, timestamp, session_token, sp_account_id, api_name, channel_partner_id` ✓
- `bq_unmatched` declared before `write_row` and accessed via `nonlocal` ✓
