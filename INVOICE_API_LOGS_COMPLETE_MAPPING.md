# Invoice API Logs - Complete Regional Mapping & Parsing Rules

**Superseded 2026-09-15**: the original version of this doc listed 27 "tracked" customers derived from Excel guesses. That list was wrong. The corrected source of truth is `logs_strings_extract.txt` (customer-labeled real Last9 log samples), cross-checked against 20 raw production CSV extracts the user shared, plus this doc's own pre-existing rules where they added detail neither other source had. **13 customers are actually tracked and deployed.**

## Regional Configuration

| Region | Region Code | Last9 Slug | Credential ID | Physical Index | Index Target ID |
|--------|-------------|-----------|---------------|----------------|-----------------|
| North Virginia | **NV** | `evergentuse1` | 6 | `UMServices` (us-east-1) | 3 |
| Frankfurt / Ireland | **IR** | `evergenteuc1` | 7 | `UMServices` (eu-central-1) | 3 |
| Singapore | **SG** | `evergentapse1` | **9** (rotated from 8 on 2026-09-14) | `UMServices` (ap-southeast-1) | 3 |
| Mumbai / India | **IN** | (pre-configured) | 1 | `UMServices` (ap-south-1) | 2 |

> Refresh tokens omitted from this doc — see `last9_credentials` table / LogVault Settings → Credentials.

---

## Customer Parsing Rules (Final, Reconciled 2026-09-15)

Each entry shows: **AND-phrase(s)** (must all appear in Body) + **OR-ids** (any one match, via regex alternation) — matching how LogVault's filter builder works: `(phrase1 AND phrase2 ...) AND (id1 OR id2 ...)`. Source tags: **[txt]** = verified sample in `logs_strings_extract.txt`, **[csv]** = confirmed via raw production CSV extract, **[doc]** = carried over from this doc's original research, not independently re-verified this pass.

### North Virginia (NV) — credential 6, region `us-east-1`

| # | Customer | Job | Phrases (AND) | IDs (OR) | Notes |
|---|----------|-----|----------------|----------|-------|
| 1 | **ABSCBN** | 64 | `ABSCBNController getContactPostAction -- data comes from request` | `ABSCBN` | Single action, confirmed **[txt][csv]** |
| 2 | **EKKL** | 90 | `Ekkl` | `GetOAuthAccessTokenCommand`, `GetCustomerServicesCommand`, `GetProdAPI`, `CGetCustomerFrameAPI` | 4 actions — 3 of 4 only known from raw CSV **[csv]**, not in original doc |
| 3 | **MongolTV** | 66 | `updateCartDetailsPostAction -- data comes from request` | `MongolTV` | ⚠️ **Known gap, not yet fixed** (excluded from this pass per explicit instruction): doc **[doc]** also lists a `removeSubscriptionPostAction` rule not currently deployed |
| 4 | **Shahid** | 67 | `ShahidController getActiveSubscriptionPostAction -- data comes from request` | `Shahid` | Single action **[txt][csv]**. An older `getOAuthAccessTokenv2PostAction` string is documented as deprecated (superseded July 17 2026) |
| 5 | **VIKI** | 68 | `getProductsPostAction -- data comes from request`, `VIKI-1` (AND) | `VIKI` | AND-combination required for accurate count **[txt][doc][csv]** |
| 6 | **Minno** | 117 | `Minno` | `GetOAuthAccessTokenv2Command` **[csv]**, `GetCustomerServicesCommand` **[doc]** | New customer, added 2026-09-14/15 |

### Frankfurt / Ireland (IR) — credential 7, region `eu-central-1`

| # | Customer | Job | Phrases (AND) | IDs (OR) | Notes |
|---|----------|-----|----------------|----------|-------|
| 1 | **ETV** | 92 | `sessionToken taken from jwt` | `getContactPostAction`, `getEntitlementsPostAction` **[txt]**, `addSubscriptionPostAction` **[csv]** | 3 actions |
| 2 | **EPL** | **114 (v3)** | `EPL` | `CreateUser`, `createUser`, `addSubscription`, `removeSubscription`, `activateUserPostAction`, `mergePartnerAccountsPostAction`, `anonymizeAccount` | Was scoped to `EPLController` which many real EPL log lines don't contain — rows jumped 154→15,340 fixing this. `removeSubscription`/`anonymizeAccount` only in original doc **[doc]**, not in the 4 CSV screenshots shared |
| 3 | **Football Association** | 71 | `In FAController addSubscriptionPostAction -- data comes from request` | `FA` | Single action, confirmed **[txt][doc][csv]** |
| 4 | **Liberty Global** | 93 | `LibertyGlobalController` | `getPkgsAndProdsWithPromosV2`, `getActiveSubscriptionPostAction` **[txt][doc]**, `AddPackageAndProductCommand` **[csv]** | 3rd action only visible in raw CSV, absent from txt/doc |

### Singapore (SG) — credential **9**, region `ap-southeast-1`

| # | Customer | Job | Phrases (AND) | IDs (OR) | Notes |
|---|----------|-----|----------------|----------|-------|
| 1 | **AstroSooka** | **115 (v4)** | `ASTRO` | `getActiveSubscriptionsPostAction` **[txt]**, `searchAccountV2PostAction` **[doc]**, `refreshTokenPostAction` **[txt]**, `getContactPostAction` **[csv]** | 4 actions, `searchAccountV2PostAction` was missing from all prior deploys |
| 2 | **TVNZ** | **116 (v4)** | `TVNZ` | `searchAccountV2PostAction`, `getProductsPostAction`, `GetEntitlementsCommand`, `GetAccountContactsCommand`, `GetAccountProfileCommand` **[csv]**, `RefreshTokenCommand`, `GetContactTermsConditionsCommand` **[doc]** | 7 actions total — matches doc's original claim of "7 separate patterns" exactly. **TVNZ is SG-only** — an earlier NV job (63) was created in error and is documented as invalid, excluded from reporting |

### Not Yet Deployed (excluded per explicit instruction, 2026-09-14)

| Customer | Region (best guess) | Known actions | Status |
|----------|---------------------|----------------|--------|
| **Lightbox** | SG | `getPaymentMethodsPostAction`, `registerDevicePostAction`, `getAccountDevicesPostAction` **[csv]** — richer than the doc's original single generic `channelPartnerID=LIGHTBOX` rule | Region/credential not confirmed; not deployed |

---

## Download File Naming

Already implemented and live (`api/app/routers/jobs.py::download_filename`, tests in `api/tests/test_download_names.py`) — **not new work from this pass**, verified working 2026-09-15:

```
<search-name>_<date>[_<time-range>][_summary|_counts].<ext>.zip
```

Example (live, job 64): `INVOICE_ABSCBN_NV_2026-09-13_1514-2026-09-14_1514.csv.zip`

Falls back to `logvault_job_<id>_<date>.csv.zip` when a job has no saved-search label. Unsafe filename characters (`/ \ : * ? " < >  |`) are stripped.

---

## Job & Schedule IDs (current, 2026-09-15)

| Customer | Live job | Schedule |
|----------|----------|----------|
| ABSCBN | 64 | 15 |
| EKKL | 90 | 16 |
| MongolTV | 66 | 17 |
| Shahid | 67 | 18 |
| VIKI | 68 | 19 |
| ETV | 92 | 21 |
| Football Association | 71 | 23 |
| Liberty Global | 93 | 24 |
| EPL | 114 | 29 |
| AstroSooka | 115 | 30 |
| TVNZ (SG) | 116 | 31 |
| Minno | 117 | 32 |

(Verified directly against `GET /schedules` on 2026-09-15; schedule ID 1 is the pre-existing `Daily_aha_GetEntitlements` for India, unrelated to this batch.)

**Invalid, excluded from reporting**: Job 63 (`INVOICE_TVNZ_NV`) — TVNZ has no NV presence; source file labels it SG both times it appears.

---

## Implementation Notes

### AND-combination customers
- **VIKI**: `getProductsPostAction -- data comes from request` AND `VIKI-1`
- All others use a single AND-anchor phrase (customer name / class name) combined with an OR'd action-name list — not literal multi-phrase AND chains.

### Schedule
- Daily, 00:00 UTC, 24-hour lookback windows, `UMServices` index per region.

### Regional credential note
Singapore credential was rotated from ID 8 to ID 9 by the user on 2026-09-14. Any doc, script, or schedule referencing 8 is stale.
