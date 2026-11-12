# New Relic vs Last9 comparison

Saved, repeatable side-by-side checks between a Last9 log query and a New Relic
NRQL query over the same time window.

## What it does

- **New Relic connection** — account id, US/EU NerdGraph region, and a New
  Relic **User** API key (`NRAK-…`). The key is encrypted with
  `LAST9_ENCRYPTION_KEY`; it is never returned after save.
- **Saved comparison** — a Last9 source (index + credential), a Last9 filter
  or hand-written JSON pipeline, the NRQL query, and how a numeric NRQL result
  should be reduced (count sum, gauge average, max, min, latest).
- **Run** — both providers are queried online over the chosen half-open
  window. Results are stored as run history: total, per-bucket series, raw
  rows, effective query text, elapsed time, and errors.
- **Side-by-side UI** — parity cards, an overlay chart, raw result tables, the
  effective queries, and previous runs.

## How a run is built

The saved queries are never mutated. On each run the backend:

1. Resolves the Last9 index, credential, and region, and refreshes the Last9
   access token if needed.
2. Chooses a bucket width:
   - an explicit run override, then
   - the comparison's saved default, then
   - a fixed `TIMESERIES` in the NRQL, then
   - an automatic width that keeps the chart at roughly 60 points.
3. Rewrites **only the time window and bucket** of the NRQL:
   `SINCE <start_ms> UNTIL <end_ms> TIMESERIES <bucket> seconds`. The effective
   query is shown on the run. A `SINCE`/`UNTIL`/`TIMESERIES` already in the saved
   query is replaced.
4. Builds the Last9 queries from the saved pipeline:
   - filter/parse only → appends an `aggregate` count for the total and a
     `window_aggregate` count for the chart;
   - `aggregate` only → total only, no chart;
   - `window_aggregate` → chart, and the total is the sum of its buckets.
5. Runs New Relic and the Last9 total/series queries in parallel and normalizes
   both provider shapes into the same `{start_epoch, end_epoch, value}` points.

## NRQL contract

- Use an aggregate query, normally `SELECT count(*) FROM …`.
- The comparison supplies the selected window and a `TIMESERIES` bucket, so a
  relative `SINCE` in the saved query is ignored.
- If the query returns more than one numeric column, set **Numeric column**
  (for example `count`) on the comparison, otherwise the run fails with an
  explanatory error.
- `FACET` is supported. In count mode, facet rows are summed into each bucket.
- `COMPARE WITH` is not useful on this page; the selected window wins.

## Last9 contract

The editor builds the same `$and` filter pipeline the extraction wizard uses
(`phrases`/`message_types` as `$contains`, exact phrases as regexes, one ID
regex alternation). Advanced users can switch to **Edit pipeline JSON** and
save any valid LogJSON pipeline using `filter`, `parse`, `aggregate`, or
`window_aggregate` stages. The comparison keeps the aggregate's meaning:
`$count`/`$sum` totals add, `$avg`/`$quantile` average, and `$min`/`$max`
reduce accordingly.

## Limits

- Window length is capped by `COMPARISON_MAX_WINDOW_DAYS` (default 31).
- A bucket that would return more than 500 points is rejected; widen the bucket.
- Both queries are interactive aggregate requests, not background extraction
  jobs. Wide Last9 windows can still return its own `408`; narrow the window.
- Last9 and New Relic may have different ingest lag. A run compares what each
  provider has at query time, not an end-of-day settled count.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/newrelic/credentials` | Add a connection (admin). |
| `GET` | `/newrelic/credentials` | List connections (key masked). |
| `PUT` | `/newrelic/credentials/{id}` | Update label/account/region/key (admin). |
| `DELETE` | `/newrelic/credentials/{id}` | Delete an unused connection (admin). |
| `POST` | `/newrelic/credentials/{id}/test` | Validate key + account via NerdGraph. |
| `GET` | `/comparisons?limit=&offset=&q=` | Paginated saved comparisons + last-run summaries. |
| `POST` | `/comparisons` | Create a saved comparison. |
| `PUT` | `/comparisons/{id}` | Replace a saved comparison. |
| `DELETE` | `/comparisons/{id}` | Delete a comparison and its runs. |
| `POST` | `/comparisons/{id}/run` | Run over `{start_epoch, end_epoch}`. |
| `GET` | `/comparisons/{id}/runs` | Run history summaries. |
| `GET` | `/comparisons/{id}/runs/{run_id}` | Full stored run result. |

## Setup

1. Create a New Relic **User** API key (NerdGraph needs a user key, not an
   ingest or browser key).
2. In **Manage → New Relic**, add the account id, US/EU region, and key. Use
   **Test** to confirm access.
3. In **Compare → New comparison**, pick the Last9 source, enter the filter or
   pipeline, paste the NRQL query, and save.
4. Pick a window and run.

New Relic connections use the same `LAST9_ENCRYPTION_KEY` as Last9 refresh
tokens; changing that key makes stored keys unreadable. Re-add them if it is
rotated.
