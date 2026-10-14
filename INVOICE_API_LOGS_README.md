# Invoice API Logs - Complete Regional Mapping & Setup Guide

## 📋 Overview

This directory contains comprehensive documentation for extracting Invoice API logs from Last9 across **4 major regions** for **27 tracked customers**. All customers are organized by region with their corresponding Last9 credentials, parsing rules, and scheduling recommendations.

---

## 📁 Files Included

### 1. **INVOICE_API_LOGS_COMPLETE_MAPPING.md**
   **Purpose**: Comprehensive reference guide with detailed explanations
   
   **Contains**:
   - Regional configuration table (NV, IR, SG, IN)
   - All 27 tracked customers organized by region
   - Detailed parsing rules with sample logs
   - Updated rules (July 2026 changes marked)
   - AND combination requirements
   - Kibana links where available
   - Implementation notes

   **Best For**: Understanding the complete picture, manual setup, troubleshooting

---

### 2. **INVOICE_API_LOGS_CONFIG.json**
   **Purpose**: Machine-readable configuration for programmatic integration
   
   **Contains**:
   - Structured JSON with all regions and refresh tokens
   - Customer configurations nested by region
   - Parsing rules as arrays
   - Boolean flags for AND combinations
   - Config file definitions for multi-part extractions (e.g., Telekom Malaysia)
   - Extraction schedule defaults

   **Best For**: Automated job creation, API integrations, infrastructure-as-code

---

### 3. **INVOICE_API_LOGS_SUMMARY.csv**
   **Purpose**: Quick reference spreadsheet
   
   **Contains**:
   - One row per customer
   - Columns: Customer, Region, Region Code, Track (Y/N), Primary Rule, AND Required, Schedule, Last Updated, Notes
   - Sortable by region or tracking status
   - 41 rows total (27 tracked + 14 not tracked)

   **Best For**: Team communication, status tracking, stakeholder reports

---

### 4. **LOGVAULT_JOB_SETUP_GUIDE.md**
   **Purpose**: Implementation guide with concrete examples
   
   **Contains**:
   - Quick reference credential matrix
   - Setup instructions for each region
   - Sample job configurations (JSON)
   - AND combination filter examples
   - Scheduling strategy recommendations
   - Troubleshooting guide
   - Recent update log

   **Best For**: Setting up LogVault jobs, API integration, deployment

---

## 🌍 Regional Structure

### North America (us-east-1) - **NV**
- **Slug**: `evergentuse1`
- **Tracked Customers**: 9
- **Notable**: VIKI requires AND combination

### Europe (eu-central-1) - **IR**  
- **Slug**: `evergenteuc1`
- **Tracked Customers**: 6
- **Notable**: EPL has 7 parsing rules

### Asia Pacific (ap-southeast-1) - **SG**
- **Slug**: `evergentapse1`
- **Tracked Customers**: 11
- **Notable**: Telekom Malaysia has 7 config files; One31 has Kibana links

### India (ap-south-1) - **IN**
- **Slug**: Pre-configured
- **Tracked Customers**: 1
- **Notable**: AHA requires AND combination; November 2025 update

---

## 🎯 Quick Start

### Step 1: Check the Summary
```bash
# Get quick overview of all customers
open INVOICE_API_LOGS_SUMMARY.csv
```

### Step 2: Review Setup Guide  
```bash
# Understand how to create LogVault jobs
open LOGVAULT_JOB_SETUP_GUIDE.md
```

### Step 3: Use Configuration
```bash
# For API integration or IaC
cat INVOICE_API_LOGS_CONFIG.json | jq '.regions.SG.customers'
```

### Step 4: Deep Dive (if needed)
```bash
# Full reference with Kibana links, samples
open INVOICE_API_LOGS_COMPLETE_MAPPING.md
```

---

## 📊 Statistics

| Metric | Count |
|--------|-------|
| Total Customers | 41 |
| Tracked | 27 |
| Not Tracked | 14 |
| Regions | 4 (+2 special) |
| Parsing Rules | 50+ |
| AND Combinations Required | 8 customers |
| Config Files (Telekom Malaysia) | 7 |

---

## 🔐 Credential Reference

| Region | Org Slug | Token Starts With |
|--------|----------|------------------|
| **NV** | evergentuse1 | eyJhbGciOi... (d458577...) |
| **IR** | evergenteuc1 | eyJhbGciOi... (0097e40...) |
| **SG** | evergentapse1 | eyJhbGciOi... (39993c3...) |
| **IN** | pre-configured | (pre-configured) |

All refresh tokens are valid until 2026. Regenerate from Last9 if needed.

---

## 🆕 Recent Updates

### November 24, 2025
- **AHA (IN)**: Old parsing strings no longer working. New rule implemented.

### July 15, 2026  
- **ABSCBN (SG)**: Parsing rule updated by Dev Team. New string preferred.

### July 17, 2026
- **SHAHID (NV)**: Parsing rule updated by Dev Team. New string preferred.

---

## 📋 Customer Checklist by Region

### ✅ North America (NV)
- [ ] ANTENNA (5 rules)
- [ ] EKKL (2 rules, AND)
- [ ] MINNO (2 rules, AND)
- [ ] MONGOLTV (2 rules)
- [ ] SHAHID (1 rule - UPDATED)
- [ ] VIKI (1 rule, AND)

### ✅ Europe (IR)
- [ ] ETV (2 rules)
- [ ] EPL (7 rules)
- [ ] FOOTBALL_ASSOCIATION (1 rule)
- [ ] LIBERTY_GLOBAL (2 rules, AND)

### ✅ Asia Pacific (SG)
- [ ] ABSCBN (1 rule - UPDATED)
- [ ] ASTRO_SOOKA (3 rules)
- [ ] ASTRO_NJOI (1 rule)
- [ ] LIGHTBOX (1 rule)
- [ ] ONE31 (3 rules)
- [ ] PILIPINAS (4 rules, AND)
- [ ] TELEKOM_MALAYSIA (7 config files, AND)

### ✅ India (IN)
- [ ] AHA (1 rule, AND - UPDATED)

### ✅ Special Regions
- [ ] TV_ASAHI (Tokyo - 3 rules, AND)
- [ ] TVNZ (Sydney - 7 rules, 2x AND)

---

## 🔍 AND Combination Rules

The following **8 customers require AND combinations** to filter logs accurately:

```
1. ANTENNA (response messages)
2. EKKL (SPAccountId AND Ekkl)
3. MINNO (SPAccountId AND Minno)
4. VIKI (getProductsPostAction AND VIKI-1)
5. PILIPINAS (SPAccountId AND region)
6. TELEKOM_MALAYSIA (Multiple AND with TELEKOMMALAYSIA)
7. LIBERTY_GLOBAL (LibertyGlobalController AND method)
8. TVNZ (Contact/Token AND TVNZ-1)
```

See **LOGVAULT_JOB_SETUP_GUIDE.md** for filter pipeline examples.

---

## 📅 Scheduling Recommendations

**Frequency**: Daily (24-hour rolling windows)  
**Timezone**: UTC  
**Time**: 00:00 UTC (midnight)  
**Retention**: 30+ days  
**Batch Mode**: Per-customer extraction

---

## 🚀 Implementation Paths

### Path A: Manual Setup in LogVault UI
1. Create 4 regional credentials
2. Manually add jobs for each customer
3. Use parsing rules from INVOICE_API_LOGS_COMPLETE_MAPPING.md

**Time**: ~2 hours | **Files**: LOGVAULT_JOB_SETUP_GUIDE.md

### Path B: API-Driven Setup
1. Parse INVOICE_API_LOGS_CONFIG.json
2. Create credentials via API
3. Create jobs programmatically
4. Setup schedules with cron

**Time**: ~30 min | **Files**: INVOICE_API_LOGS_CONFIG.json

### Path C: Terraform/IaC
1. Use JSON config as data source
2. Write Terraform modules for LogVault resources
3. Deploy infrastructure-as-code

**Time**: ~1 hour | **Files**: INVOICE_API_LOGS_CONFIG.json

---

## 🛠️ Common Tasks

### "I need to extract logs for SHAHID"
→ See **LOGVAULT_JOB_SETUP_GUIDE.md**, "North Virginia" section, find SHAHID example

### "What's the AND combination for VIKI?"
→ See **INVOICE_API_LOGS_COMPLETE_MAPPING.md**, "VIKI" subsection, or search in JSON config

### "How do I track all Telekom Malaysia operations?"
→ See **LOGVAULT_JOB_SETUP_GUIDE.md**, sample job showing 7 config files

### "Which customers were updated recently?"
→ See **INVOICE_API_LOGS_SUMMARY.csv**, sort by "Last Updated" column

### "What's the correct credential for Singapore?"
→ See **Regional Structure** table above, or **LOGVAULT_JOB_SETUP_GUIDE.md** quick reference

---

## ⚠️ Important Notes

1. **All refresh tokens expire in 2026** - Plan regeneration early
2. **AND combinations are critical** - 8 customers will give wrong counts without them
3. **Index name is always "UMServices"** across all regions
4. **Some rules were updated in 2026** - Check "Last Updated" column
5. **Kibana links are provided** for One31 for manual verification

---

## 🔗 File Dependencies

```
INVOICE_API_LOGS_README.md (you are here)
├── INVOICE_API_LOGS_COMPLETE_MAPPING.md (detailed reference)
├── INVOICE_API_LOGS_CONFIG.json (programmatic config)
├── INVOICE_API_LOGS_SUMMARY.csv (quick lookup)
└── LOGVAULT_JOB_SETUP_GUIDE.md (implementation)
```

All files are self-contained and can be used independently.

---

## 📞 Support & Troubleshooting

### Issue: Token Expired
**Solution**: Regenerate from Last9 console for your org slug (evergentuse1, evergenteuc1, evergentapse1)

### Issue: AND Combination Not Working
**Solution**: See "AND Combination Filter Examples" in LOGVAULT_JOB_SETUP_GUIDE.md

### Issue: No Logs Found for Customer
**Solution**: 
1. Verify date range includes actual API activity
2. Confirm correct region/credential
3. Check if rule was recently updated
4. Review Last9 Kibana logs

### Issue: Different Log Counts Than Expected
**Solution**: Likely missing an AND combination rule - cross-reference with INVOICE_API_LOGS_SUMMARY.csv

---

## 📝 Version History

| Date | File(s) | Changes |
|------|---------|---------|
| 2026-09-14 | All | Initial release with 4 regions, 41 customers, 27 tracked |
| 2026-07-17 | SHAHID | Parsing rule updated by Dev Team |
| 2026-07-15 | ABSCBN | Parsing rule updated by Dev Team |
| 2025-11-24 | AHA | Old strings deactivated, new rules required |

---

## 🎓 Learning Path

1. **New to LogVault?** → Start with LOGVAULT_JOB_SETUP_GUIDE.md, "Quick Reference" section
2. **Building API integration?** → Use INVOICE_API_LOGS_CONFIG.json directly
3. **Need complete details?** → Read INVOICE_API_LOGS_COMPLETE_MAPPING.md in full
4. **Stakeholder reporting?** → Share INVOICE_API_LOGS_SUMMARY.csv

---

## ✨ Next Steps

1. Create credentials for each region (NV, IR, SG, IN)
2. Create 1-2 test jobs per region to verify connectivity
3. Review AND combination rules for your customers
4. Set up daily schedules for recurring extractions
5. Configure failure alerts and reconciliation reports
6. Plan credential regeneration for 2026 (tokens expire then)

