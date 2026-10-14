# Invoice API Logs - Deployment Summary
**Status**: LIVE (corrected)
**Date**: 2026-09-14
**Last Correction**: 2026-09-14 22:10 IST — fixed AND/OR filter bugs, retired invalid TVNZ-NV job, added Minno

---

## ✓ WHAT'S DEPLOYED

### Regional Infrastructure
| Region | Code | Slug | Credential ID | Status |
|--------|------|------|---------------|--------|
| North Virginia | NV | evergentuse1 | 6 | ✓ Active |
| Frankfurt/Ireland | IR | evergenteuc1 | 7 | ✓ Active |
| Singapore | SG | evergentapse1 | 8 | ✓ Active |

### Corrected Regional Customer Mapping (source of truth: `logs_strings_extract.txt`)

| Region | Customers |
|--------|-----------|
| **NV** (6) | ABSCBN, EKKL, MongolTV, Shahid, VIKI, **Minno** (added 2026-09-14) |
| **IR** (4) | ETV, EPL, Football Association, Liberty Global |
| **SG** (2) | AstroSooka, **TVNZ** (SG only — see correction below) |

> **TVNZ is SG-only.** The source file labels TVNZ "SG" both times it appears (line 1 and line 65) — there is no "TVNZ - NV" entry. **Job 63 (`INVOICE_TVNZ_NV`) was created against the wrong region and is INVALID.** It cannot be deleted or patched via the API (job already completed; PATCH → 405, cancel → 409 "already completed"), so it remains in the jobs table but **must be excluded from any NV reporting/reconciliation**. The correct TVNZ data comes from the SG jobs only (see below).

### Current Jobs (live, use these — supersede all earlier attempts)

| Job ID | Customer | Region | Status | Rows | Notes |
|--------|----------|--------|--------|------|-------|
| 64 | ABSCBN | NV | Completed | 67,575 | OK as originally deployed |
| 90 | EKKL | NV | Running | 289+ | **v2** — broadened from 1 command to 4 (OR): GetOAuthAccessTokenCommand, GetCustomerServicesCommand, GetProdAPI, CGetCustomerFrameAPI |
| 66 | MongolTV | NV | Completed | 0 | Unchanged (user asked to exclude from this pass) |
| 67 | Shahid | NV | Running | 1,058,979 | OK as originally deployed |
| 68 | VIKI | NV | Running | 896,505 | OK as originally deployed |
| 95 | **Minno** | NV | Queued | — | **New** — phrase "Minno", id "GetOAuthAccessTokenv2Command" |
| 92 | ETV | IR | Running | 43,611 | **v2** — fixed AND-bug (was ANDing 2 mutually exclusive phrases → always 0 rows); now ORs 3 actions off a shared "sessionToken taken from jwt" phrase |
| 91 | EPL | IR | Running | 50+ | **v2** — replaced guessed free-text phrases with the 4 real actions (OR): CreateUser, mergePartnerAccounts, ActivateUser, addSubscription |
| 71 | Football Association | IR | Completed | 383 | OK as originally deployed |
| 93 | Liberty Global | IR | Running | 1,772 | **v2** — fixed AND-bug + added `AddPackageAndProductCommand` (3rd action discovered in raw extract) |
| 89 | AstroSooka | SG | Running | 0 (in flight) | **v2** — added missing `getContactPostAction` (3rd action) |
| 94 | TVNZ | SG | Queued | — | **v2** — broadened to 6 known actions: searchAccountV2PostAction, getProductsPostAction, GetEntitlementsCommand, GetAccountContactsCommand, GetAccountProfileCommand, RefreshTokenCommand |

**Superseded/do-not-use for reporting**: Job 63 (TVNZ-NV, invalid region), Job 65 (EKKL v1, too narrow), Job 69 (ETV v1, AND-bug/0 rows), Job 70 (EPL v1, wrong phrases), Job 72 (LG v1, AND-bug), Job 73 (AstroSooka v1, missing action), Job 74 (TVNZ-SG v1, too narrow).

### Excluded This Pass (per explicit instruction)
- **Lightbox** — raw extract exists (channelPartnerID LIGHTBOX, actions getPaymentMethodsPostAction/registerDevicePostAction/getAccountDevicesPostAction) but not deployed; region unconfirmed.
- **MongolTV** — left as originally deployed (Job 66), not re-verified against new raw extracts.

### Daily Schedules (12 total, IDs 15-26) — ✓ FIXED 2026-09-14 22:15 IST
Old schedules (IDs 2-14, including a throwaway test) were created with empty `phrases`/`ids` — root cause of the 75-86 job failures. Deleted via `DELETE /schedules/{id}` (works — 204; note `PATCH` accepts the request but silently ignores `filter_spec`, so editing in place doesn't work, only delete+recreate does) and rebuilt with the same corrected v2 filters used in the jobs table above. All 12 confirmed with non-empty `filter_spec` on creation.

| Schedule ID | Name |
|---|---|
| 15 | INVOICE_ABSCBN_NV_DAILY |
| 16 | INVOICE_EKKL_NV_DAILY |
| 17 | INVOICE_MONGOLTV_NV_DAILY |
| 18 | INVOICE_SHAHID_NV_DAILY |
| 19 | INVOICE_VIKI_NV_DAILY |
| 20 | INVOICE_MINNO_NV_DAILY |
| 21 | INVOICE_ETV_IR_DAILY |
| 22 | INVOICE_EPL_IR_DAILY |
| 23 | INVOICE_FA_IR_DAILY |
| 24 | INVOICE_LG_IR_DAILY |
| 25 | INVOICE_ASTRO_SG_DAILY |
| 26 | INVOICE_TVNZ_SG_DAILY |

Next run: 2026-09-15 00:00 UTC — verify all 12 spawn jobs with rows > 0 (or a legitimate 0 if no matching logs) and none fail with the filter error.

---

## 📊 METRICS (as of last check)

- **Distinct customers now tracked**: 12 (11 original regions + Minno; TVNZ counted once, in SG)
- **Total rows extracted across all live jobs**: ~2,070,000+ and climbing
- **Biggest single fix impact**: ETV went from 0 → 43,611 rows; Liberty Global from 61 → 1,772 rows, both from correcting an AND-vs-OR logic bug in the original filter construction (phrases array is AND'd, ids array is OR'd — the v1 jobs put mutually-exclusive action names in the AND'd phrases field).

---

## ✅ VERIFIED WORKING

- ✓ Multi-region credentials created and tested
- ✓ Last9 API connectivity confirmed across NV/IR/SG
- ✓ Worker async jobs processing correctly
- ✓ Corrected filters (v2) confirmed pulling significantly more accurate row counts
- ✓ New customer (Minno) onboarded using raw-extract-derived filter

---

## 🔧 OUTSTANDING FOLLOW-UPS

1. ~~Rebuild schedules with corrected v2 filters~~ — **done 2026-09-14 22:15 IST**, see Schedules table above.
2. **Decide on Lightbox** — deploy once region/credential confirmed.
3. **Job 63 cleanup** — no API way to delete; must be manually excluded in any downstream reporting/BI queries by job ID.
4. **Re-verify MongolTV** against raw extracts if/when available (currently unchanged from original deployment, 0 rows).

---

## 🐛 INCIDENT — 2026-09-15: Jobs stuck permanently in "queued", never progressing

**Symptom**: Job #108 (and others) showed status `queued`, `0/?` chunks, no error message, "Waiting for events..." forever.

**Root cause (two stacked bugs)**:
1. **Stale credential reference.** Singapore credential ID 8 was replaced by a new one (ID 9, "Singapore") — an intentional change on your end. Schedules 25/26 and several jobs still pointed at the deleted ID 8.
2. **Worker bug masking the failure.** `worker/app/runner.py::_send_alert_if_scheduled()` did `job.get("created_by", "")`, which returns `None` (not the default) when the key exists but is `NULL` — `None.startswith("schedule:")` then threw `AttributeError`. That crash happened *inside* the same DB transaction that was setting the job to `failed`, so the transaction rolled back and the status update was undone. Net effect: instead of a clean "failed: missing credential/index", the job hung in `queued` forever with no error message.

**Fix applied**:
- `runner.py` line 58: `job.get("created_by") or ""` (matches the safe pattern already used elsewhere in the same file, e.g. line 468). Worker restarted 2026-09-15 07:02 UTC.
- Schedules 25/26 deleted and rebuilt as 27/28 on credential ID 9.
- Stale jobs found still `running`/`queued` on the deleted credential 8 — all canceled: **62** (old ABSCBN test), **73**, **74** (AstroSooka/TVNZ SG v1, already superseded), **89**, **94** (v2, zombied ~20h at 0/24 chunks after a worker restart), **108** (the one reported).
- Replacement jobs **109** (AstroSooka v3) and **110** (TVNZ SG v3) created on credential 9, confirmed running with no errors.
- Swept all schedules and active/queued/running jobs for remaining references to credential 8 — none left.

**Why this matters going forward**: rotating/replacing a credential does not cascade to jobs or schedules that reference the old ID — anything still pointed at a deleted credential will silently hang instead of failing loudly, until this session's code fix. Any *future* credential rotation should be followed by checking `GET /schedules` and in-flight `GET /jobs?status=running,queued` for the old credential_id.

---

## 📞 REFERENCE DOCS

- **Setup Guide**: LOGVAULT_JOB_SETUP_GUIDE.md
- **Complete Mapping**: INVOICE_API_LOGS_COMPLETE_MAPPING.md
- **Config File**: INVOICE_API_LOGS_CONFIG.json
- **Summary CSV**: INVOICE_API_LOGS_SUMMARY.csv
- **Source of truth for regional mapping**: logs_strings_extract.txt

---

**Deployment completed by**: Claude Code
**Deployment ID**: S384-2026-09-14 (v2 correction pass)
