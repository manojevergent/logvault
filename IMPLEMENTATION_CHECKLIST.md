# Implementation Checklist - Invoice API Logs Extraction

**Status**: Ready to Deploy  
**Created**: 2026-09-14  
**Target**: 27 tracked customers across 4 regions

---

## Phase 0: Prerequisites ✓

- [ ] Docker & Docker Compose running
- [ ] LogVault application started (`docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d`)
- [ ] API accessible at `http://localhost:8000`
- [ ] Admin authentication configured

**Time**: ~5 minutes

---

## Phase 1: Regional Infrastructure Setup

### Step 1.1: Create Credentials (15 min)

**Option A: Automated (Recommended)**
```bash
python3 setup_invoice_jobs.py
```

**Option B: Manual via UI**
1. Navigate to LogVault → Settings → Credentials
2. Click "Add Credential"
3. Create 4 credentials using values from `INVOICE_API_LOGS_CONFIG.json`:
   - [ ] NV (evergentuse1)
   - [ ] IR (evergenteuc1)
   - [ ] SG (evergentapse1)
   - [ ] IN (pre-configured)

**Option C: API Call**
```bash
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "label": "Last9 - North Virginia",
    "org_slug": "evergentuse1",
    "refresh_token": "eyJ..."
  }'
```

**Verification**:
- [ ] All 4 credentials created and visible in UI
- [ ] Credential IDs noted for job creation

---

### Step 1.2: Create or Verify Index Targets (10 min)

**Required**: UMServices index for each region

**Option A: Via UI**
1. Settings → Indexes
2. For each region, create index:
   - [ ] NV (us-east-1) - UMServices
   - [ ] IR (eu-central-1) - UMServices
   - [ ] SG (ap-southeast-1) - UMServices
   - [ ] IN (ap-south-1) - UMServices

**Option B: Via API** (if create endpoint available)
```bash
curl -X POST http://localhost:8000/indexes \
  -d '{"name": "UMServices", "region_code": "us-east-1"}'
```

**Verification**:
- [ ] All 4 indexes created with name "UMServices"
- [ ] Index IDs noted

---

## Phase 2: Sample Job Creation & Validation

### Step 2.1: Create Test Jobs (One Per Region)

**Recommended approach**: Create 1 simple job per region first

#### Job 1: EKKL (North Virginia)
- **Credential**: NV credential (ID from Phase 1)
- **Index**: UMServices (us-east-1)
- **Time Range**: Last 24 hours
- **Phrases**: 
  - `ClassName CGetOAuthAccessTokenCommand SPAccountId`
  - `ClassName CGetCustomerServicesCommand SPAccountId`
- **IDs**: `Ekkl`
- **Label**: `INVOICE_EKKL_TEST`

**API Call**:
```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "credential_id": 1,
    "index_target_id": 1,
    "region_code": "us-east-1",
    "start_epoch": 1705000000,
    "end_epoch": 1705086400,
    "phrases": ["ClassName CGetOAuthAccessTokenCommand SPAccountId"],
    "ids": ["Ekkl"],
    "label": "INVOICE_EKKL_TEST",
    "customer": "EKKL"
  }'
```

**Checklist**:
- [ ] Job created successfully
- [ ] Job appears in LogVault UI
- [ ] Job status is "queued" or "running"
- [ ] No errors in API logs

#### Job 2: ABSCBN (Singapore)
- **Credential**: SG credential
- **Index**: UMServices (ap-southeast-1)
- **Phrases**: `ABSCBNController getContactPostAction -- data comes from request`
- **IDs**: `ABSCBN`
- **Label**: `INVOICE_ABSCBN_TEST`

- [ ] Job created and running

#### Job 3: ETV (Frankfurt)
- **Credential**: IR credential
- **Index**: UMServices (eu-central-1)
- **Phrases**: 
  - `getContactPostAction sessionToken taken from jwt:`
  - `getEntitlementsPostAction sessionToken taken from jwt:`
- **IDs**: `ETV`
- **Label**: `INVOICE_ETV_TEST`

- [ ] Job created and running

---

### Step 2.2: Validate Connectivity

**For each test job**:
1. Wait 1-2 minutes for job to complete
2. Check Last9 API connectivity:
   ```bash
   # Check job status
   curl http://localhost:8000/jobs/{job_id}
   ```
3. Verify row counts match expected ranges
4. Check for errors in job status

**Checklist**:
- [ ] EKKL job completed without errors
- [ ] ABSCBN job completed without errors
- [ ] ETV job completed without errors
- [ ] Row counts > 0 for all jobs
- [ ] No "token expired" errors

---

## Phase 3: Bulk Customer Job Creation

### Step 3.1: Create Jobs by Region (2-3 hours total)

**North Virginia (NV) - 9 Customers**

Use `LOGVAULT_JOB_SETUP_GUIDE.md` for exact parsing rules.

Jobs to create:
- [ ] ANTENNA (5 rules, AND combinations)
- [ ] EKKL ✓ (already test job)
- [ ] MINNO (2 rules, AND)
- [ ] MONGOLTV (2 rules)
- [ ] SHAHID (1 rule - UPDATED 7/17)
- [ ] VIKI (1 rule, AND)

**Batch creation option**:
```python
python3 -c "
import json
with open('INVOICE_API_LOGS_CONFIG.json') as f:
    config = json.load(f)
    customers = config['customers']['NV']
    for name, spec in customers.items():
        if spec.get('track'):
            print(f'Create job: {name}')
            print(f'  Rules: {spec.get(\"rules\", [])}')
"
```

**Frankfurt (IR) - 6 Customers**
- [ ] ETV ✓ (already test job)
- [ ] EPL (7 rules)
- [ ] FOOTBALL_ASSOCIATION (1 rule)
- [ ] LIBERTY_GLOBAL (2 rules, AND)

**Singapore (SG) - 11 Customers**
- [ ] ABSCBN ✓ (already test job)
- [ ] ASTRO_SOOKA (3 rules)
- [ ] ASTRO_NJOI (1 rule)
- [ ] LIGHTBOX (1 rule)
- [ ] ONE31 (3 rules)
- [ ] PILIPINAS (4 rules, AND)
- [ ] TELEKOM_MALAYSIA (7 config files, AND)

**India (IN) - 1 Customer**
- [ ] AHA (1 rule, AND - UPDATED 11/24/25)

---

### Step 3.2: Batch Validation

After creating jobs in each region:

**Checklist**:
- [ ] All NV jobs created (6 total)
- [ ] All IR jobs created (4 total)
- [ ] All SG jobs created (7 total)
- [ ] All IN jobs created (1 total)
- [ ] **Total**: 18 job configurations (excluding special regions)
- [ ] No duplicate labels
- [ ] All jobs visible in UI

---

## Phase 4: AND Combination Validation

**Critical**: 8 customers require AND combinations

Customers to verify:
1. [ ] ANTENNA (NV) - verify filter pipeline accepts multiple conditions
2. [ ] EKKL (NV) - SPAccountId AND "Ekkl" 
3. [ ] MINNO (NV) - SPAccountId AND "Minno"
4. [ ] VIKI (NV) - getProductsPostAction AND "VIKI-1"
5. [ ] PILIPINAS (SG) - SPAccountId AND region variant
6. [ ] TELEKOM_MALAYSIA (SG) - AND with "TELEKOMMALAYSIA"
7. [ ] LIBERTY_GLOBAL (IR) - AND method names
8. [ ] TVNZ (Sydney) - Contact/Token AND "TVNZ-1"

**Validation method**:
```bash
# Check if job query includes both conditions
curl http://localhost:8000/jobs/{job_id} | grep -A5 "filter_spec"
```

- [ ] All 8 AND combos properly configured in filter_spec
- [ ] Test run returns logs for all 8

---

## Phase 5: Schedule Configuration

### Step 5.1: Set Up Daily Extractions

**Target**: All jobs run daily at 00:00 UTC

**Option A: UI-Based Scheduling**
1. LogVault → Jobs → {Job Name}
2. Click "Schedule" or "Create Schedule"
3. Configure:
   - Frequency: Daily
   - Time: 00:00 UTC
   - Enabled: Yes

- [ ] Schedule created for all 18 jobs
- [ ] All scheduled for 00:00 UTC
- [ ] All marked as "Active"

**Option B: Batch API (if supported)**
```bash
# For each job, create schedule
for job_id in 1 2 3 ...; do
  curl -X POST http://localhost:8000/schedules \
    -d "{\"job_id\": $job_id, \"frequency\": \"daily\", \"time\": \"00:00\"}"
done
```

**Checklist**:
- [ ] All 18 jobs have schedules
- [ ] All set to daily at 00:00 UTC
- [ ] Schedules show as "Active"

---

### Step 5.2: Verify Schedule Execution

**Test**: Check if tomorrow's scheduled jobs appear in queue

- [ ] Next scheduled run shows in UI
- [ ] Job queue shows tomorrow's EKKL at 00:00
- [ ] Cron/task scheduler confirms timezone is UTC

---

## Phase 6: Monitoring & Validation

### Step 6.1: First Full Extraction

**When**: Tomorrow at 00:00 UTC (or manually trigger test run)

**Validation checklist**:
- [ ] All 18 jobs started
- [ ] All jobs completed successfully
- [ ] No "token expired" errors
- [ ] Row counts > 0 for all jobs
- [ ] No data corruption or truncation

---

### Step 6.2: Results Verification

Compare with Last9 Kibana:
- [ ] EKKL rows match between LogVault and Kibana
- [ ] ABSCBN AND combination rows correct
- [ ] VIKI AND combination rows correct
- [ ] AND combinations produce lower counts than single phrase searches

**Kibana queries**:
```
For VIKI:
  Query 1: "getProductsPostAction -- data comes from request : " → count1
  Query 2: "getProductsPostAction -- data comes from request : " AND "VIKI-1" → count2
  Expected: count2 < count1 (more specific filter)
```

---

### Step 6.3: Configure Alerts

**Option A: Email Alerts**
1. LogVault → Settings → Notifications
2. Configure SMTP (already setup in previous work ✓)
3. Add alert rule: "Alert on job failure"

- [ ] Notification config complete
- [ ] Test email sent successfully
- [ ] Alert rules created for all jobs

**Option B: Slack Alerts** (if configured)
- [ ] Slack webhook configured
- [ ] Test message posted
- [ ] Job failure notifications enabled

---

## Phase 7: Special Regions Setup

### Step 7.1: Non-Standard Regions

**TV ASAHI (Tokyo)** - 1 customer
- [ ] Create job with any regional credential
- [ ] Phrases from COMPLETE_MAPPING.md
- [ ] Schedule daily

**TVNZ (Sydney)** - 1 customer
- [ ] Create job (7 rules + 2 AND combinations)
- [ ] Verify AND combinations work
- [ ] Schedule daily

---

## Phase 8: Documentation & Handoff

### Step 8.1: Finalize Configuration

- [ ] Document all credential IDs in secure location
- [ ] Document all job IDs and labels
- [ ] Export schedule configuration
- [ ] Record any custom modifications

### Step 8.2: Runbook Updates

- [ ] Update LOGVAULT_JOB_SETUP_GUIDE.md with actual credential IDs
- [ ] Document any region-specific tweaks
- [ ] Record token regeneration dates (2026)

### Step 8.3: Knowledge Transfer

- [ ] Brief team on job structure
- [ ] Walk through results verification
- [ ] Document troubleshooting procedures

---

## Timeline & Effort Estimate

| Phase | Steps | Effort | Status |
|-------|-------|--------|--------|
| 0 | Prerequisites | 5 min | Ready |
| 1 | Infrastructure | 25 min | Ready |
| 2 | Test Jobs | 30 min | Ready |
| 3 | Bulk Creation | 120 min | Ready |
| 4 | AND Validation | 30 min | Ready |
| 5 | Schedules | 20 min | Ready |
| 6 | Monitoring | 60 min | Ready |
| 7 | Special Regions | 15 min | Ready |
| 8 | Documentation | 30 min | Ready |
| **TOTAL** | **8 Phases** | **~5.5 hours** | **Ready** |

---

## Quick Reference Commands

```bash
# Start LogVault
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Run automated setup
python3 setup_invoice_jobs.py

# Check API health
curl http://localhost:8000/health

# List all credentials
curl http://localhost:8000/credentials

# List all jobs
curl http://localhost:8000/jobs

# Check specific job
curl http://localhost:8000/jobs/{id}

# View logs
docker-compose logs -f api
docker-compose logs -f worker
```

---

## Success Criteria

✓ **Phase Complete When**:
- All 4 regional credentials created
- UMServices index exists in all 4 regions
- 3 test jobs (EKKL, ABSCBN, ETV) completed successfully
- All 18 production jobs created with correct parsing rules
- All 8 AND combinations verified working
- All jobs scheduled for daily 00:00 UTC execution
- First scheduled run completed with > 0 rows
- No errors in job logs or API logs
- Alert/notification system configured

---

## Rollback Plan

If issues occur:

1. **Token Issues**: Regenerate from Last9 console
2. **Job Errors**: Disable schedule, verify parsing rule
3. **Connectivity Issues**: Check Last9 API status, verify region slug
4. **Data Issues**: Delete job, recreate with corrected phrase list

---

## Next Phase

Once Phase 8 complete:

- [ ] Archive current documentation
- [ ] Schedule monthly reconciliation reports
- [ ] Plan token regeneration for 2026
- [ ] Set up BigQuery export (if needed)
- [ ] Configure long-term retention policy

---

**Questions?** See `INVOICE_API_LOGS_README.md` or `LOGVAULT_JOB_SETUP_GUIDE.md`
