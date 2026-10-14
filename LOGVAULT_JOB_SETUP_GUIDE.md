# LogVault Job Setup Guide - Invoice API Logs Extraction

## Quick Reference: Last9 Regional Credentials

```
Region Code | Slug | Organization | Last9 Endpoint | Physical Index
NV          | evergentuse1 | Evergent US (East) | app.last9.io | UMServices (us-east-1)
IR          | evergenteuc1 | Evergent EU (Central) | app.last9.io | UMServices (eu-central-1)
SG          | evergentapse1 | Evergent APAC | app.last9.io | UMServices (ap-southeast-1)
IN          | (pre-configured) | Evergent India | app.last9.io | UMServices (ap-south-1)
```

---

## Setup Instructions by Region

### 🇺🇸 North Virginia (us-east-1) - **evergentuse1**

Create a new credential in LogVault:
- **Name**: `Last9 - North Virginia`
- **Slug**: `evergentuse1`
- **Refresh Token**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2NTY5LCJuYmYiOjE3ODkzNzgxNjksImlhdCI6MTc4OTM3ODE2OSwianRpIjoiZDQ1ODU3NzktN2UxNy00OTI5LWJmZjYtZTUwZDg1ZGU0Zjg1Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnR1c2UxIiwidG9rZW5faWQiOiIwNTdlNjhmNy03MmFmLTRiNDgtYWUyNS05MzIyMmRiNTI4NDcifQ.tG-Qy7lEhKw5RvSy2NwL0HJdbn5Qx2rgWIZ2zrkhBQs`

#### Customers to Track (NV):
```
1. ANTENNA (5 rules)
2. EKKL (2 rules)
3. MINNO (2 rules)
4. MONGOLTV (2 rules)
5. SHAHID (1 rule - updated Jul 17)
6. VIKI (1 rule with AND combination)
```

#### Sample Job: EKKL
```
POST /jobs
{
  "credential_id": <NV_CREDENTIAL_ID>,
  "index_target_id": <UMServices_INDEX_ID>,
  "region_code": "us-east-1",
  "start_epoch": 1700000000,
  "end_epoch": 1700086400,
  "phrases": [
    "ClassName CGetOAuthAccessTokenCommand SPAccountId",
    "ClassName CGetCustomerServicesCommand SPAccountId"
  ],
  "ids": ["Ekkl"],
  "label": "INVOICE_EKKL",
  "customer": "EKKL",
  "schedule_id": null
}
```

---

### 🇪🇺 Frankfurt / Ireland (eu-central-1) - **evergenteuc1**

Create a new credential in LogVault:
- **Name**: `Last9 - Frankfurt`
- **Slug**: `evergenteuc1`
- **Refresh Token**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2NzY4LCJuYmYiOjE3ODkzNzgzNjgsImlhdCI6MTc4OTM3ODM2OCwianRpIjoiMDA5ZTQwNzItZDJhMy00ZDNmLWIxMzQtMDQ1OTUzNzgyNjA5Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnRldWMxIiwidG9rZW5faWQiOiI2YTM3ZmNlMy1hODNiLTRjNDQtOGQ2Yi0xMjBjMjYyZmIyNjYifQ.Zya5QWm9f_S939YAEm_YYC0mnt0oiLVjqv0hptTOKlA`

#### Customers to Track (IR):
```
1. ETV (2 rules)
2. EPL (7 rules)
3. FOOTBALL_ASSOCIATION (1 rule)
4. LIBERTY_GLOBAL (2 rules with AND)
```

#### Sample Job: EPL
```
POST /jobs
{
  "credential_id": <IR_CREDENTIAL_ID>,
  "index_target_id": <UMServices_INDEX_ID>,
  "region_code": "eu-central-1",
  "start_epoch": 1700000000,
  "end_epoch": 1700086400,
  "phrases": [
    "eplCpAccountID from access token in createUser API:",
    "EPLController eplCpAccountID from access token addSubscription API:",
    "eplCpCustomerID from access token in removeSubscription API:",
    "EPLController activateUserPostAction -- data comes from request:",
    "EPLController mergePartnerAccountsPostAction -- data comes from request:",
    "eplCpCustomerID from access token in anonymizeAccount API:",
    "eplCpCustomerID from access token in CreateUser API:"
  ],
  "ids": ["EPL"],
  "label": "INVOICE_EPL",
  "customer": "EPL",
  "schedule_id": null
}
```

---

### 🇸🇬 Singapore (ap-southeast-1) - **evergentapse1**

Create a new credential in LogVault:
- **Name**: `Last9 - Singapore`
- **Slug**: `evergentapse1`
- **Refresh Token**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2ODk5LCJuYmYiOjE3ODkzNzg0OTksImlhdCI6MTc4OTM3ODQ5OSwianRpIjoiMzk5M2MzMjYtODA3MS00ZWI4LWE1NzUtYjc4M2ZlNmNlZjA4Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnRhcHNlMSIsInRva2VuX2lkIjoiMjE4ZGJjYzAtM2NhYy00YWMzLTkwY2YtNjhiOWJhMmY5MDI2In0.C6bk5Cq_ljp-5ZppxrEGt6psv8cBWSXW8PhSnwJtSRA`

#### Customers to Track (SG):
```
1. ABSCBN (1 rule - updated Jul 15)
2. ASTRO_SOOKA (3 rules)
3. ASTRO_NJOI (1 rule)
4. LIGHTBOX (1 rule)
5. ONE31 (3 rules)
6. PILIPINAS (4 rules with AND)
7. TELEKOM_MALAYSIA (7 config files)
```

#### Sample Job: TELEKOM_MALAYSIA (Most Complex)
```
POST /jobs
{
  "credential_id": <SG_CREDENTIAL_ID>,
  "index_target_id": <UMServices_INDEX_ID>,
  "region_code": "ap-southeast-1",
  "start_epoch": 1700000000,
  "end_epoch": 1700086400,
  "phrases": [
    "In TelekomMalaysiaController addOrUpdateSubscriptionPostAction -- data comes from request :",
    "TelekomMalaysiaController getAccountProfilePostAction -- data comes from request:",
    "TelekomMalaysiaController getOAuthAccessTokenv2PostAction -- data comes from request:",
    "TelekomMalaysiaController getUserDetailsPostAction -- data comes from request:",
    "In TelekomMalaysiaController modifyUserPostAction -- data comes from request:",
    "TelekomMalaysiaController searchAccountV2PostAction -- data comes from request:",
    "eventCode in trackingparams is WELCOME_EMAIL"
  ],
  "ids": ["TELEKOMMALAYSIA"],
  "label": "INVOICE_TELEKOM_MALAYSIA",
  "customer": "TELEKOM_MALAYSIA",
  "schedule_id": null
}
```

---

### 🇮🇳 India (ap-south-1) - **Pre-Configured**

#### Customers to Track (IN):
```
1. AHA (1 rule with AND - requires "AND" combination)
```

#### Sample Job: AHA
```
POST /jobs
{
  "credential_id": <IN_CREDENTIAL_ID>,
  "index_target_id": <UMServices_INDEX_ID>,
  "region_code": "ap-south-1",
  "start_epoch": 1700000000,
  "end_epoch": 1700086400,
  "phrases": [
    "ClassName CGetEntitlementsCommand SPAccountId"
  ],
  "ids": ["AHA"],
  "label": "INVOICE_AHA",
  "customer": "AHA",
  "schedule_id": null
}
```

---

## Special Regions (Non-Standard Mappings)

### 🇯🇵 Tokyo - TV ASAHI

Use any regional credential (data is source-agnostic for TV ASAHI)

#### Sample Job:
```
POST /jobs
{
  "credential_id": <ANY_CREDENTIAL_ID>,
  "index_target_id": <UMServices_INDEX_ID>,
  "region_code": "ap-south-1",
  "start_epoch": 1700000000,
  "end_epoch": 1700086400,
  "phrases": [
    "createBeaconPostAction --- data comes from request:",
    "searchAccountV2PostAction -- data comes from request :",
    "refreshTokenPost"
  ],
  "ids": ["TVASAHI"],
  "label": "INVOICE_TVASAHI",
  "customer": "TV_ASAHI",
  "schedule_id": null
}
```

### 🇦🇺 Sydney - TVNZ

#### Sample Job (with AND combinations):
```
POST /jobs
{
  "credential_id": <ANY_CREDENTIAL_ID>,
  "index_target_id": <UMServices_INDEX_ID>,
  "region_code": "ap-south-1",
  "start_epoch": 1700000000,
  "end_epoch": 1700086400,
  "phrases": [
    "TVNZController searchAccountV2PostAction -- data comes from request:",
    "TVNZController getProductsPostAction -- data comes from request :",
    "ClassName CGetEntitlementsCommand SPAccountId",
    "ClassName CGetAccountProfileCommand SPAccountId",
    "ClassName CGetContactTermsConditionsCommand SPAccountId",
    "ClassName CGetAccountContactsCommand SPAccountId",
    "ClassName CRefreshTokenCommand SPAccountId"
  ],
  "ids": ["TVNZ-1"],
  "label": "INVOICE_TVNZ",
  "customer": "TVNZ",
  "schedule_id": null,
  "note": "Several rules require AND combination with TVNZ-1"
}
```

---

## Scheduling Strategy

### Recommended Schedule Configuration
```
Frequency: Daily
Timezone: UTC
Time: 00:00 UTC (midnight)
Retention: 30 days rolling window
Batch: Group by customer per 24-hour extraction window
```

### Creating Recurring Schedules

```bash
# Example: Create daily schedule for EKKL
POST /schedules
{
  "name": "Daily Invoice Extract - EKKL",
  "customer": "EKKL",
  "region": "NV",
  "frequency": "daily",
  "start_time": "00:00",
  "timezone": "UTC",
  "active": true,
  "jobs": [{
    "credential_id": <NV_CREDENTIAL_ID>,
    "index_target_id": <UMServices_INDEX_ID>,
    "region_code": "us-east-1",
    "duration_hours": 24,
    "phrases": ["ClassName CGetOAuthAccessTokenCommand SPAccountId", "ClassName CGetCustomerServicesCommand SPAccountId"],
    "ids": ["Ekkl"],
    "label": "INVOICE_EKKL_DAILY",
    "customer": "EKKL"
  }]
}
```

---

## Important Notes

### ⚠️ AND Combination Queries
These customers **require AND combinations** for accurate log count:

| Customer | Rule | Combination Required |
|----------|------|----------------------|
| ANTENNA | EVBrightcoveController | Multiple AND with response text |
| EKKL | SPAccountId | AND with "Ekkl" |
| MINNO | SPAccountId | AND with "Minno" |
| VIKI | getProductsPostAction | AND with "VIKI-1" |
| PILIPINAS | SPAccountId | AND with region variant |
| TELEKOM_MALAYSIA | Multiple rules | AND with "TELEKOMMALAYSIA" |
| LIBERTY_GLOBAL | LibertyGlobalController | AND with method names |
| TVNZ | Contact/RefreshToken | AND with "TVNZ-1" |

**Example Filter Pipeline for VIKI:**
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

### 📅 Recent Updates
- **July 15, 2026**: ABSCBN parsing rule updated
- **July 17, 2026**: SHAHID parsing rule updated
- **November 24, 2025**: AHA old strings disabled (new strings now required)

---

## Troubleshooting

### Issue: "No logs found" for a customer
1. Verify the correct region/credential is selected
2. Check if the log string date range includes actual API calls
3. For AND combination rules, ensure BOTH phrases are present in the same log entry
4. Verify the Last9 index contains data for that customer

### Issue: Token expired
1. The refresh tokens provided expire in 2026 - regenerate from Last9 if needed
2. Ensure the credential is updated in LogVault before extraction

### Issue: Inconsistent row counts
1. Check if AND combinations are being respected
2. Verify no filters are being accidentally applied at the UI level
3. Review Last9 Kibana logs for the exact query being executed

---

## Next Steps

1. Create credentials for each region in LogVault
2. Create one test job per region to verify connectivity
3. Set up daily schedules for tracked customers
4. Configure email alerts for job failures
5. Set up BigQuery export if required for downstream analytics
6. Schedule monthly reconciliation reports against ERP data
