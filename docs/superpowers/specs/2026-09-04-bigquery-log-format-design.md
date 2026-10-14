# BigQuery Log Format — Design Spec
**Date:** 2026-09-04  
**Status:** Approved

---

## Problem

Extracted logs must be ingested into BigQuery with a fixed 6-column schema:

```
BU Name | Timestamp | Session Token | SP Account ID/Customer ID | API name | Channel Partner ID
```

Current output formats (CSV raw, JSONL) do not produce this shape.

---

## Scope

- New `bigquery` output format option (`fmt == "bigquery"`)
- Parses the two observed log patterns from Evergent's application logs
- Integrates into the existing streaming pipeline — no post-processing, no extra memory
- UI selector for the new format in the New Job wizard

Out of scope: customer drill-down UI, UI perf fixes, job retry (tracked separately as Tasks 2–4).

---

## Log Patterns

### Format A — ClassName/Command

**Example:**
```
AHA-1-6a9a915b-48da52e15d3f654156570481 - ClassName CGetEntitlementsCommand SPAccountId 241230090725797443495533 in BU AHA INDIA API User ahaapiuser
```

**Field extraction:**

| BQ Column | Source |
|---|---|
| BU Name | Text after `in BU ` and before ` API User` |
| Session Token | Leading `{prefix}-{n}-{hex}-{hex}` token |
| SP Account ID | Text after `SPAccountId ` |
| API name | Text after `ClassName ` |
| Channel Partner ID | `<channelPartnerID>…</channelPartnerID>` if present, else `""` |

**Hint:** `"ClassName "` appears in every Format A line.

**Detection regex (Format A):**
```
^(?P<session_token>(?P<customer>[A-Za-z0-9]+)-\d+-[0-9a-f]+-[0-9a-f]+)\s+-\s+ClassName\s+(?P<api_name>\S+)\s+SPAccountId\s+(?P<sp_account_id>\S+)\s+in\s+BU\s+(?P<bu_name>.+?)\s+API\s+User\s+\S+
```

---

### Format B — Controller/XML request

**Example:**
```
ABSCBN-1-6a9a91a4-73c12a735fa51a0567d87320 - ABSCBNController getContactPostAction -- data comes from request:<GetContactRequestMessage><channelPartnerID>ABSCBN</channelPartnerID>...</GetContactRequestMessage>
```

**Field extraction:**

| BQ Column | Source |
|---|---|
| BU Name | Session token prefix (before first `-{digit}-`) |
| Session Token | Leading `{prefix}-{n}-{hex}-{hex}` token |
| SP Account ID | `<spAccountID>…</spAccountID>` or fallback `<cpCustomerID>…</cpCustomerID>` |
| API name | Word immediately before ` -- data comes from request` |
| Channel Partner ID | `<channelPartnerID>…</channelPartnerID>`, else `"-"` |

**Hint:** `"-- data comes from request"` appears in every Format B line.

**Session token regex (shared):**
```
^(?P<session_token>(?P<customer>[A-Za-z0-9]+)-\d+-[0-9a-f]+-[0-9a-f]+)
```

**API name extraction (Format B):**
```python
re.search(r'(\w+)\s+--\s+data comes from request', message).group(1)
```

**XML field extraction (Format B):**
```python
re.search(r'<channelPartnerID>([^<]+)</channelPartnerID>', message)
re.search(r'<spAccountID>([^<]+)</spAccountID>', message)
re.search(r'<cpCustomerID>([^<]+)</cpCustomerID>', message)
```

---

## Unmatched Rows

Rows that match neither Format A nor Format B are **skipped** (not written to the BQ CSV). The count is accumulated and reported in the job completion message, e.g.:

> "Job completed — 142,300 rows written, 38 rows didn't match any BQ log pattern"

---

## New File: `worker/app/last9/bq_formatter.py`

```python
@dataclass
class BQRow:
    bu_name: str
    timestamp: str
    session_token: str
    sp_account_id: str
    api_name: str
    channel_partner_id: str

def parse_bq_row(message: str, timestamp: str) -> BQRow | None:
    """Returns None for rows that match neither known pattern."""
    if "ClassName " in message:
        return _parse_format_a(message, timestamp)
    if "-- data comes from request" in message:
        return _parse_format_b(message, timestamp)
    return None
```

Exposed via `worker/app/last9/__init__.py`.

---

## Runner Integration (`worker/app/runner.py`)

### File naming
```python
def output_path(job_id, fmt="csv", customer=None):
    ext = "jsonl" if fmt == "jsonl" else ("bq.csv" if fmt == "bigquery" else "csv")
    ...
```

### Header (written once at file open)
```python
if fmt == "bigquery":
    csv.writer(f).writerow(["bu_name", "timestamp", "session_token",
                             "sp_account_id", "api_name", "channel_partner_id"])
```

### Per-row write (in `write_row()`)
```python
elif fmt == "bigquery":
    bq = parse_bq_row(row.message, ts)
    if bq:
        csv_writer.writerow(dataclasses.astuple(bq))
    else:
        bq_unmatched += 1
```

`bq_unmatched` is a closure variable (like `written`). Included in the job completion message.

Compression, zip, checkpoint/resume, and preview all work unchanged.

---

## UI Change (`web/`)

In the New Job wizard, **Options step** — add `Output format` selector:

| Value | Label |
|---|---|
| `csv` | CSV (raw) — default |
| `jsonl` | JSONL |
| `bigquery` | BigQuery CSV |

The `output_format` field is already persisted on the `jobs` table. No schema migration needed.

---

## Test

`worker/tests/test_bq_formatter.py` — unit tests using the sample log lines from this spec:
- Format A: AHA, EKKL, Marquee
- Format B: ABSCBN, FA, VIKI
- Edge: no channelPartnerID in Format A → `""`
- Edge: no spAccountID in Format B → falls back to cpCustomerID
- Edge: unknown format → returns `None`
