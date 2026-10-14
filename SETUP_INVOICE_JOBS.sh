#!/bin/bash

# Invoice API Logs - Automated Setup Script
# Creates regional credentials and jobs for all tracked customers

set -e

API_BASE="${LOGVAULT_API_BASE:-http://localhost:8000}"
ADMIN_TOKEN="${LOGVAULT_ADMIN_TOKEN:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Invoice API Logs Setup - Automated Deployment    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}"
echo

# Verify API is accessible
check_api() {
    echo -n "Checking API connectivity... "
    if curl -s -o /dev/null -w "%{http_code}" "$API_BASE/health" | grep -q "200"; then
        echo -e "${GREEN}✓${NC}"
        return 0
    else
        echo -e "${RED}✗${NC}"
        echo "API not accessible at $API_BASE"
        echo "Start LogVault with: docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
        exit 1
    fi
}

# Create regional credentials
create_credentials() {
    echo
    echo -e "${YELLOW}Step 1: Creating Regional Credentials${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # North Virginia
    echo -n "  • NV (us-east-1)... "
    NV_RESPONSE=$(curl -s -X POST "$API_BASE/credentials" \
        -H "Content-Type: application/json" \
        -d '{
            "label": "Last9 - North Virginia",
            "org_slug": "evergentuse1",
            "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2NTY5LCJuYmYiOjE3ODkzNzgxNjksImlhdCI6MTc4OTM3ODE2OSwianRpIjoiZDQ1ODU3NzktN2UxNy00OTI5LWJmZjYtZTUwZDg1ZGU0Zjg1Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnR1c2UxIiwidG9rZW5faWQiOiIwNTdlNjhmNy03MmFmLTRiNDgtYWUyNS05MzIyMmRiNTI4NDcifQ.tG-Qy7lEhKw5RvSy2NwL0HJdbn5Qx2rgWIZ2zrkhBQs"
        }')
    NV_ID=$(echo $NV_RESPONSE | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
    if [ -n "$NV_ID" ]; then
        echo -e "${GREEN}✓ (ID: $NV_ID)${NC}"
    else
        echo -e "${RED}✗${NC}"
        echo "  Response: $NV_RESPONSE"
    fi

    # Frankfurt / Ireland
    echo -n "  • IR (eu-central-1)... "
    IR_RESPONSE=$(curl -s -X POST "$API_BASE/credentials" \
        -H "Content-Type: application/json" \
        -d '{
            "label": "Last9 - Frankfurt",
            "org_slug": "evergenteuc1",
            "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2NzY4LCJuYmYiOjE3ODkzNzgzNjgsImlhdCI6MTc4OTM3ODM2OCwianRpIjoiMDA5ZTQwNzItZDJhMy00ZDNmLWIxMzQtMDQ1OTUzNzgyNjA5Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnRldWMxIiwidG9rZW5faWQiOiI2YTM3ZmNlMy1hODNiLTRjNDQtOGQ2Yi0xMjBjMjYyZmIyNjYifQ.Zya5QWm9f_S939YAEm_YYC0mnt0oiLVjqv0hptTOKlA"
        }')
    IR_ID=$(echo $IR_RESPONSE | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
    if [ -n "$IR_ID" ]; then
        echo -e "${GREEN}✓ (ID: $IR_ID)${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    # Singapore
    echo -n "  • SG (ap-southeast-1)... "
    SG_RESPONSE=$(curl -s -X POST "$API_BASE/credentials" \
        -H "Content-Type: application/json" \
        -d '{
            "label": "Last9 - Singapore",
            "org_slug": "evergentapse1",
            "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJsYXN0OS5pbyIsImF1ZCI6WyJhcHAubGFzdDkuaW8iXSwiZXhwIjoxODUyNTM2ODk5LCJuYmYiOjE3ODkzNzg0OTksImlhdCI6MTc4OTM3ODQ5OSwianRpIjoiMzk5M2MzMjYtODA3MS00ZWI4LWE1NTUtYjc4M2ZlNmNlZjA4Iiwic2NvcGVzIjpbInJlYWQiXSwia2luZCI6InJlZnJlc2hfdG9rZW4iLCJlbWFpbCI6Im1hbm9qQGV2ZXJnZW50LmNvbSIsIm9yZ2FuaXphdGlvbl9zbHVnIjoiZXZlcmdlbnRhcHNlMSIsInRva2VuX2lkIjoiMjE4ZGJjYzAtM2NhYy00YWMzLTkwY2YtNjhiOWJhMmY5MDI2In0.C6bk5Cq_ljp-5ZppxrEGt6psv8cBWSXW8PhSnwJtSRA"
        }')
    SG_ID=$(echo $SG_RESPONSE | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
    if [ -n "$SG_ID" ]; then
        echo -e "${GREEN}✓ (ID: $SG_ID)${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    echo
    echo "Credential IDs saved for job creation:"
    echo "  NV_ID=$NV_ID"
    echo "  IR_ID=$IR_ID"
    echo "  SG_ID=$SG_ID"
}

# Create sample jobs (one per region as test)
create_sample_jobs() {
    echo
    echo -e "${YELLOW}Step 2: Creating Sample Jobs (Test Jobs)${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Get index target ID (assuming UMServices exists)
    echo -n "  Getting UMServices index ID... "
    INDEX_RESPONSE=$(curl -s "$API_BASE/indexes?region=us-east-1")
    INDEX_ID=$(echo $INDEX_RESPONSE | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
    if [ -n "$INDEX_ID" ]; then
        echo -e "${GREEN}✓ (ID: $INDEX_ID)${NC}"
    else
        echo -e "${YELLOW}! Creating index...${NC}"
        # Will need to create index if it doesn't exist
        INDEX_ID=1  # Default ID
    fi

    # Test job for EKKL (NV region)
    echo -n "  Creating test job: EKKL (NV)... "
    JOB_RESPONSE=$(curl -s -X POST "$API_BASE/jobs" \
        -H "Content-Type: application/json" \
        -d "{
            \"credential_id\": $NV_ID,
            \"index_target_id\": $INDEX_ID,
            \"region_code\": \"us-east-1\",
            \"start_epoch\": $(($(date +%s) - 86400)),
            \"end_epoch\": $(date +%s),
            \"phrases\": [
                \"ClassName CGetOAuthAccessTokenCommand SPAccountId\",
                \"ClassName CGetCustomerServicesCommand SPAccountId\"
            ],
            \"ids\": [\"Ekkl\"],
            \"label\": \"INVOICE_EKKL_TEST\",
            \"customer\": \"EKKL\"
        }")
    EKKL_JOB_ID=$(echo $JOB_RESPONSE | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
    if [ -n "$EKKL_JOB_ID" ]; then
        echo -e "${GREEN}✓ (Job ID: $EKKL_JOB_ID)${NC}"
    else
        echo -e "${YELLOW}! (Pending manual creation)${NC}"
    fi
}

# Create schedules
create_schedules() {
    echo
    echo -e "${YELLOW}Step 3: Creating Schedules${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Schedules will run daily at 00:00 UTC"
    echo "  Note: Schedule creation requires manual setup via UI or advanced API"
    echo -e "  ${YELLOW}→ Use LogVault UI for now, or implement schedule API${NC}"
}

# Summary and next steps
print_summary() {
    echo
    echo -e "${GREEN}╔════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              Setup Complete (Partial)              ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}"
    echo
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "  1. Verify credentials were created (check LogVault > Credentials)"
    echo "  2. Create jobs for remaining customers using LOGVAULT_JOB_SETUP_GUIDE.md"
    echo "  3. Set up daily schedules at 00:00 UTC"
    echo "  4. Test with one customer job to verify Last9 connectivity"
    echo "  5. Enable all production jobs once verified"
    echo
    echo -e "${YELLOW}Command to test Last9 connectivity:${NC}"
    echo "  curl -s http://localhost:8000/jobs/$EKKL_JOB_ID"
    echo
}

# Run setup
main() {
    check_api
    create_credentials
    create_sample_jobs
    create_schedules
    print_summary
}

main
