# 🚀 Start Implementation - Invoice API Logs

**Status**: Ready to Execute  
**Estimated Time**: 5-6 hours total  
**Next Steps**: Follow this guide to deploy all 27 customers across 4 regions

---

## ⏱️ Right Now (5 minutes)

### 1. Start the Stack
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Verify**:
```bash
# Check all services are healthy
docker-compose -f docker-compose.yml -f docker-compose.prod.yml ps --format "table {{.Service}}\t{{.Status}}"

# Should show:
# SERVICE    STATUS
# api        Up ... (healthy)
# postgres   Up ... (healthy)
# redis      Up ... (healthy)
# web        Up ...
# worker     Up ...
```

✓ Takes ~2 minutes for services to fully start

### 2. Verify API Connectivity
```bash
curl http://localhost:8000/health
# Should return: {"status":"ok","checks":{"postgres":"ok","redis":"ok"}}
```

✓ Once you see this, API is ready

---

## 📋 Phase 1: Setup Infrastructure (25 minutes)

### Automated Setup (Recommended - 5 minutes)
```bash
cd D:\last9_web_app
python3 setup_invoice_jobs.py
```

**What this does**:
- ✓ Creates 4 regional credentials (NV, IR, SG)
- ✓ Verifies index targets
- ✓ Creates 2 test jobs (EKKL, ABSCBN)
- ✓ Prints credential IDs for next phase

**Output you should see**:
```
[SUCCESS] API is healthy
[SUCCESS] NV (us-east-1) → ID 1
[SUCCESS] IR (eu-central-1) → ID 2
[SUCCESS] SG (ap-southeast-1) → ID 3
[SUCCESS] EKKL (NV) → Job ID 10
[SUCCESS] ABSCBN (SG) → Job ID 11
```

**If any step fails**:
- Read the error message
- Check API is running: `curl http://localhost:8000/health`
- Check credentials format in `INVOICE_API_LOGS_CONFIG.json`

### Manual Setup (Alternative - 25 minutes)

If automated script fails:

1. **Open LogVault UI**: http://localhost:3001
2. **Login** with your credentials
3. **Navigate to**: Settings → Credentials
4. **Add 4 Credentials** using data from `INVOICE_API_LOGS_CONFIG.json`:

```
Name:          Last9 - North Virginia
Slug:          evergentuse1
Refresh Token: eyJ... (copy from config.json, NV section)

Name:          Last9 - Frankfurt
Slug:          evergenteuc1
Refresh Token: eyJ... (copy from config.json, IR section)

Name:          Last9 - Singapore
Slug:          evergentapse1
Refresh Token: eyJ... (copy from config.json, SG section)
```

**Note credential IDs** (you'll need them for jobs):
- NV ID: ___
- IR ID: ___
- SG ID: ___

---

## 🧪 Phase 2: Validate with Test Jobs (30 minutes)

### Create First Test Job (EKKL)

**Via UI**:
1. Navigate to: Jobs → New Job
2. Fill in:
   ```
   Credential:    Last9 - North Virginia
   Region:        us-east-1
   Index:         UMServices
   Time Range:    Last 24 hours (auto-filled)
   Label:         INVOICE_EKKL_TEST
   Customer:      EKKL
   
   Parsing Rules (add both):
   Phrase 1:  ClassName CGetOAuthAccessTokenCommand SPAccountId
   Phrase 2:  ClassName CGetCustomerServicesCommand SPAccountId
   
   IDs: Ekkl
   ```
3. Click "Create Job"

**Via API**:
```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "credential_id": 1,
    "index_target_id": 1,
    "region_code": "us-east-1",
    "start_epoch": 1700000000,
    "end_epoch": 1700086400,
    "phrases": [
      "ClassName CGetOAuthAccessTokenCommand SPAccountId",
      "ClassName CGetCustomerServicesCommand SPAccountId"
    ],
    "ids": ["Ekkl"],
    "label": "INVOICE_EKKL_TEST",
    "customer": "EKKL"
  }'
```

### Monitor Test Job

1. **Wait** 2-3 minutes for job to complete
2. **Check status**: 
   - UI: Jobs → INVOICE_EKKL_TEST → View Details
   - API: `curl http://localhost:8000/jobs/{job_id}`
3. **Expected results**:
   - Status: "completed" or "running"
   - Rows: > 0 (should have some logs)
   - Errors: None

✓ **Success**: Job completed with rows > 0

✗ **Failure**: See Troubleshooting section below

---

## 📦 Phase 3: Bulk Job Creation (2-3 hours)

### Create Jobs by Region

Use `LOGVAULT_JOB_SETUP_GUIDE.md` for exact parsing rules for each customer.

**Batch 1: North Virginia (9 customers)**
```
ANTENNA, EKKL (done), MINNO, MONGOLTV, SHAHID, VIKI
```

**Batch 2: Frankfurt (6 customers)**
```
ETV, EPL, FOOTBALL_ASSOCIATION, LIBERTY_GLOBAL
```

**Batch 3: Singapore (11 customers)**
```
ABSCBN (done), ASTRO_SOOKA, ASTRO_NJOI, LIGHTBOX, ONE31, PILIPINAS, TELEKOM_MALAYSIA
```

**Batch 4: India + Special (2 customers)**
```
AHA (India), TV_ASAHI, TVNZ
```

### Recommended Approach

**Option A: UI Batch Creation** (Slower but visible)
1. Open LogVault UI
2. Create jobs one by one from guide
3. Total: ~45 minutes per batch

**Option B: API Batch Script** (Faster)
```python
# Create a Python script using INVOICE_API_LOGS_CONFIG.json
# Iterate through customers and POST to /jobs endpoint
# See setup_invoice_jobs.py for template
```

**Option C: Mix** (Balanced)
- UI: Create 2-3 complex ones (see AND combinations)
- API: Batch create simple ones

### Critical: AND Combinations

These 8 customers need AND combinations in filter:
- [ ] ANTENNA (NV)
- [ ] EKKL (NV)
- [ ] MINNO (NV)
- [ ] VIKI (NV)
- [ ] PILIPINAS (SG)
- [ ] TELEKOM_MALAYSIA (SG)
- [ ] LIBERTY_GLOBAL (IR)
- [ ] TVNZ (Special)

**Example filter for VIKI**:
```json
{
  "pipeline": [
    {
      "query": {
        "$and": [
          {"Body": {"$contains": "getProductsPostAction -- data comes from request : "}},
          {"Body": {"$contains": "VIKI-1"}}
        ]
      },
      "type": "filter"
    }
  ]
}
```

See `LOGVAULT_JOB_SETUP_GUIDE.md` for filter pipeline examples.

---

## ⏰ Phase 4: Schedule Configuration (20 minutes)

### Set All Jobs to Run Daily at 00:00 UTC

**Via UI**:
1. Jobs → {Job Name} → Edit
2. Scroll to "Schedule" section
3. Set:
   ```
   Frequency: Daily
   Time: 00:00 UTC
   Active: Yes
   ```
4. Save

**Repeat for all 18 jobs** (takes ~20 minutes)

**Via API** (if batch schedule endpoint exists):
```bash
curl -X POST http://localhost:8000/schedules \
  -d '{
    "job_id": 10,
    "frequency": "daily",
    "time": "00:00",
    "timezone": "UTC",
    "active": true
  }'
```

### Verify Schedules

```bash
# Check next scheduled runs
curl http://localhost:8000/jobs?status=scheduled

# Should show all 18 jobs with next run = tomorrow 00:00 UTC
```

---

## ✅ Phase 5: Validation (1 hour)

### Run First Full Extraction

**Option A: Wait for scheduled time**
- Set your alarm for tomorrow 00:00 UTC
- Monitor LogVault UI for all jobs to start

**Option B: Trigger manually**
```bash
# Manually run one job to test
curl -X POST http://localhost:8000/jobs/{job_id}/run
```

### Check Results

**For each job**:
1. View job details
2. Confirm:
   - ✓ Status = "completed"
   - ✓ Rows > 0
   - ✓ No errors
3. Compare row count with Kibana (optional)

### Verify AND Combinations

For the 8 AND combination customers:
- [ ] VIKI row count < single phrase search
- [ ] EKKL returns only "Ekkl" related logs
- [ ] ANTENNA rows include correct response messages

---

## 🔄 Phase 6: Setup Alerting (15 minutes)

### Configure Email Notifications

**Note**: Email SMTP already configured from previous work ✓

1. LogVault → Settings → Notifications
2. Create alert rule:
   ```
   Trigger: Job Status = Failed
   Action: Send Email
   Recipients: ops@evergent.com
   ```

### Test Alert

1. Create a dummy job
2. Manually mark it as failed
3. Verify email arrives

---

## 🎉 Done! Next Steps

### Immediate (Today)
- [ ] Monitor first 24-hour extraction cycle
- [ ] Verify row counts with Kibana
- [ ] Fix any parsing rule issues
- [ ] Document any customizations

### This Week
- [ ] Run monthly reconciliation against ERP
- [ ] Validate all 27 customers working
- [ ] Set up BigQuery export (if needed)

### This Month
- [ ] Optimize extraction window sizes
- [ ] Archive first month's data
- [ ] Document lessons learned

### Before 2026
- [ ] Plan token regeneration (all tokens expire 2026)
- [ ] Set up automated token rotation

---

## 🆘 Troubleshooting

### Issue: "API not accessible"
```bash
# Check if API is running
docker-compose -f docker-compose.yml -f docker-compose.prod.yml ps

# Check logs
docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs api | tail -20

# Restart if needed
docker-compose -f docker-compose.yml -f docker-compose.prod.yml restart api
```

### Issue: "Credential creation failed"
- Verify tokens are pasted completely (no truncation)
- Check org_slug matches: `evergentuse1`, `evergenteuc1`, `evergentapse1`
- Retry credential creation

### Issue: "No logs found" for a job
1. Check time range includes actual API calls
2. Verify parsing phrase is in sample logs (check `logs_strings_extract.txt`)
3. For AND combos: verify BOTH phrases present together
4. Check Last9 Kibana for manual query

### Issue: "Token expired"
- Regenerate from Last9 console
- Update credential in LogVault
- Re-run job

### Issue: Different row count than Kibana
- Likely missing AND combination
- Check `INVOICE_API_LOGS_SUMMARY.csv` for "Requires AND" column
- Verify filter pipeline in job definition

---

## 📞 Support Resources

| Issue | File |
|-------|------|
| Parsing rules for customer | `INVOICE_API_LOGS_COMPLETE_MAPPING.md` |
| AND combination examples | `LOGVAULT_JOB_SETUP_GUIDE.md` |
| All customer summary | `INVOICE_API_LOGS_SUMMARY.csv` |
| Implementation checklist | `IMPLEMENTATION_CHECKLIST.md` |
| Full reference | `INVOICE_API_LOGS_README.md` |

---

## ⏱️ Timeline Summary

```
NOW:        Start Docker stack (5 min)
+5 min:     Run setup script (5 min)
+10 min:    Create test jobs (10 min)
+30 min:    Test job completes, validate (5 min)
+40 min:    Bulk create jobs (120 min)
+160 min:   Schedule all jobs (20 min)
+180 min:   Configure alerts (15 min)
+200 min:   Awaiting first scheduled run

Tomorrow:
00:00 UTC:  All 18 jobs execute
+60 min:    Validate results
+120 min:   Fix any issues

TOTAL: ~3.5 hours hands-on + 1 night waiting
```

---

## 🚀 You're Ready!

Everything is prepared. Just follow the phases above and you'll have all 27 customers extracting logs daily by tomorrow morning.

**Start with**:
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
python3 setup_invoice_jobs.py
```

**Questions?** Check `INVOICE_API_LOGS_README.md` or `IMPLEMENTATION_CHECKLIST.md`

**Good luck! 🎯**
