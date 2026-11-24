$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$Evidence = 'E:\last9_web_app-p1\release-artifacts\evidence-final-7f2ac46-fix4'
$ApiImage = 'last9-api:release-1-final-84046b2-fix3'
$WrkImage = 'last9-worker:release-1-final-7f2ac46-fix4'
$Api = 'http://localhost:8010'

function Test-Docker {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    docker info --format '{{.ServerVersion}}' *> $null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    return $ok
}

function Ensure-Docker {
    for ($i = 0; $i -lt 100; $i++) {
        if (Test-Docker) { return }
        if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 5
    }
    throw 'Docker engine did not start'
}

Ensure-Docker

# ---------------------------------------------------------------- fresh stack
foreach ($c in 'r1acc-web','r1acc-beat','r1acc-worker','r1acc-api','r1acc-redis','r1acc-db') {
    docker rm -f $c *> $null
}
docker volume rm -f r1acc-db r1acc-exp *> $null
docker network rm r1acc *> $null
docker network create r1acc *> $null
docker volume create r1acc-db *> $null
docker volume create r1acc-exp *> $null

$env:ACC_DB_PASSWORD = docker run --rm --entrypoint python $ApiImage -c "import secrets;print(secrets.token_urlsafe(18))"
$env:JWT_SECRET = docker run --rm --entrypoint python $ApiImage -c "import secrets;print(secrets.token_urlsafe(48))"
$env:LAST9_ENCRYPTION_KEY = docker run --rm --entrypoint python $ApiImage -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
$env:INITIAL_ADMIN_EMAIL = 'acceptance@example.local'
$env:INITIAL_ADMIN_PASSWORD = docker run --rm --entrypoint python $ApiImage -c "import secrets;print(secrets.token_urlsafe(12))"
$env:DATABASE_URL = "postgresql+psycopg://accept:$($env:ACC_DB_PASSWORD)@r1acc-db:5432/accept"
$env:REDIS_URL = 'redis://r1acc-redis:6379/0'
$env:CELERY_BROKER_URL = 'redis://r1acc-redis:6379/1'
$env:CELERY_RESULT_BACKEND = 'redis://r1acc-redis:6379/2'
$env:STORAGE_DIR = '/data/exports'
$env:CORS_ORIGINS = 'http://localhost:3001'
$env:ENVIRONMENT = 'acceptance'
$env:WORKER_CONCURRENCY = '1'

docker run -d --name r1acc-db --network r1acc -v r1acc-db:/var/lib/postgresql/data `
    -e POSTGRES_USER=accept -e POSTGRES_PASSWORD=$env:ACC_DB_PASSWORD -e POSTGRES_DB=accept `
    postgres:16-alpine *> $null
docker run -d --name r1acc-redis --network r1acc redis:7-alpine *> $null

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    docker exec r1acc-db pg_isready -U accept -d accept *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { throw 'Postgres did not become ready' }

docker run --rm --network r1acc -e DATABASE_URL $ApiImage alembic upgrade head *> $null
$rev = docker exec r1acc-db psql -U accept -d accept -tAc 'SELECT version_num FROM alembic_version'
if ($rev.Trim() -ne '0034') { throw "unexpected schema $rev" }
Write-Output "schema=$($rev.Trim())"

# ------------------------------------------------- copy the configured token
$lines = Get-Content 'E:\last9_web_app\.env'
$env:DEV_KEY = (($lines | Where-Object { $_ -match '^LAST9_ENCRYPTION_KEY=' }) -replace '^LAST9_ENCRYPTION_KEY=','').Trim().Trim('"')

# ------------------------------------------------------------------- services
docker run -d --name r1acc-api --network r1acc -p 8010:8000 `
    -e DATABASE_URL -e REDIS_URL -e CELERY_BROKER_URL -e CELERY_RESULT_BACKEND `
    -e STORAGE_DIR -e CORS_ORIGINS -e ENVIRONMENT -e JWT_SECRET -e LAST9_ENCRYPTION_KEY `
    -e INITIAL_ADMIN_EMAIL -e INITIAL_ADMIN_PASSWORD `
    -v r1acc-exp:/data/exports -v "${Evidence}:/x:ro" $ApiImage *> $null
docker run -d --name r1acc-worker --network r1acc `
    -e DATABASE_URL -e REDIS_URL -e CELERY_BROKER_URL -e CELERY_RESULT_BACKEND `
    -e STORAGE_DIR -e ENVIRONMENT -e JWT_SECRET -e LAST9_ENCRYPTION_KEY -e WORKER_CONCURRENCY `
    -v r1acc-exp:/data/exports $WrkImage `
    celery -A app.celery_app.celery worker --loglevel=INFO *> $null
docker run -d --name r1acc-beat --network r1acc `
    -e DATABASE_URL -e REDIS_URL -e CELERY_BROKER_URL -e CELERY_RESULT_BACKEND `
    -e STORAGE_DIR -e ENVIRONMENT -e JWT_SECRET -e LAST9_ENCRYPTION_KEY `
    -v r1acc-exp:/data/exports $WrkImage python -m app.beat_guard *> $null

$up = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $health = Invoke-RestMethod "$Api/health" -TimeoutSec 3
        if ($health.status -eq 'ok') { $up = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $up) { throw 'API did not become healthy' }
$readyState = Invoke-RestMethod "$Api/ready"
Write-Output "ready=$($readyState.status) pg=$($readyState.checks.postgres) redis=$($readyState.checks.redis)"

# --------------------------------------------------- seed the configured token
$credRow = docker exec last9_web_app-postgres-1 psql -U logvault -d logvault -tAc "SELECT encrypted_refresh_token || '|' || label || '|' || org_slug || '|' || refresh_token_last4 FROM last9_credentials WHERE id=9"
if (-not $credRow) { throw 'development credential 9 not found' }
$parts = $credRow.Trim() -split '\|'
docker exec -e "DEV_CIPHERTEXT=$($parts[0])" -e "DEV_KEY=$($env:DEV_KEY)" -e "CRED_LABEL=$($parts[1])" -e "CRED_ORG=$($parts[2])" -e "CRED_LAST4=$($parts[3])" r1acc-api python /x/seed_credential.py
if ($LASTEXITCODE -ne 0) { throw 'credential seed failed' }

# ---------------------------------------------------------------------- A1/A2
$login = Invoke-RestMethod -Method Post -Uri "$Api/auth/login" -ContentType 'application/json' `
    -Body (@{ email = $env:INITIAL_ADMIN_EMAIL; password = $env:INITIAL_ADMIN_PASSWORD } | ConvertTo-Json)
if (-not $login.access_token) { throw 'login returned no token' }
$H = @{ Authorization = "Bearer $($login.access_token)" }
Write-Output "A1 login ok role=$($login.role)"

$credTest = Invoke-RestMethod -Method Post -Uri "$Api/credentials/9/test" -Headers $H
Write-Output "A2 credential_test ok=$($credTest.ok) status=$($credTest.token_status) msg=$($credTest.message)"

# ------------------------------------------------------------------------ A3
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
$idx = Invoke-RestMethod -Method Post -Uri "$Api/indexes" -Headers $H -ContentType 'application/json' `
    -Body (@{ name = 'acceptance-candidate'; region_code = 'ap-southeast-1'; physical_index = 'UMServices'; credential_id = 9 } | ConvertTo-Json)
Write-Output "A3 index id=$($idx.id) $($idx.region_code)"

function New-ExtractionJob([int]$indexId, [string]$region, [int]$credId = 9) {
    $now = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $body = @{
        credential_id = $credId; index_target_id = $indexId; region_code = $region
        start_epoch = $now - 3600; end_epoch = $now; chunk_hours = 1; id_batch_size = 100
        phrases = @('<channelPartnerID>LIGHTBOX</channelPartnerID>')
        message_types = @('sessionToken')
        label = "acceptance-$stamp"; customer = 'ACCEPTANCE'
        output_format = 'csv'; is_preview = $false
    } | ConvertTo-Json -Depth 5
    Invoke-RestMethod -Method Post -Uri "$Api/jobs" -Headers $H -ContentType 'application/json' -Body $body
}
function Wait-Status([int]$id, [string[]]$want, [int]$timeoutSec = 240) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        $j = Invoke-RestMethod "$Api/jobs/$id" -Headers $H
        if ($want -contains $j.status) { return $j }
        Start-Sleep -Seconds 3
    }
    $j = Invoke-RestMethod "$Api/jobs/$id" -Headers $H
    throw "job $id stuck at $($j.status)"
}

# ------------------------------------------------------------------------ A4-A7
$job = New-ExtractionJob $idx.id 'ap-southeast-1'
Write-Output "A4 job id=$($job.id) status=$($job.status)"
$job = Wait-Status $job.id @('completed','failed','canceled')
Write-Output "A5/A7 job=$($job.id) status=$($job.status) rows=$($job.rows_written) chunks=$($job.completed_chunks)/$($job.total_chunks) err=$($job.error_message)"
if ($job.status -ne 'completed') { throw "candidate extraction did not complete: $($job.error_message)" }

$events = Invoke-RestMethod "$Api/jobs/$($job.id)/events" -Headers $H
$job | ConvertTo-Json -Depth 6 | Out-File -Encoding utf8 "$Evidence\candidate-job-completed.json"
$events | ConvertTo-Json -Depth 4 | Out-File -Encoding utf8 "$Evidence\candidate-job-events.json"

# ------------------------------------------------------------------------- A8
$zip = Join-Path $env:TEMP "candidate-job-$($job.id).zip"
Invoke-WebRequest -Uri "$Api$($job.download_url)" -OutFile $zip
$out = Join-Path $env:TEMP "candidate-job-$($job.id)"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive -LiteralPath $zip -DestinationPath $out -Force
$csv = Get-ChildItem $out -Filter *.csv | Select-Object -First 1
$rows = Import-Csv -LiteralPath $csv.FullName
$dataRows = @($rows).Count
$header = (Get-Content -LiteralPath $csv.FullName -TotalCount 1)
$firstVal = $rows[0].PSObject.Properties.Value[0]
$lastVal = $rows[-1].PSObject.Properties.Value[0]
$tsPattern = '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3}) UTC'
$firstTs = [regex]::Match([string]$firstVal, $tsPattern).Groups[1].Value
$lastTs = [regex]::Match([string]$lastVal, $tsPattern).Groups[1].Value
$win = docker exec r1acc-db psql -U accept -d accept -tAc "SELECT start_epoch::text || ' ' || end_epoch::text FROM jobs WHERE id = $($job.id)"
$winParts = ($win.Trim() -split ' ')
$winStart = [DateTimeOffset]::FromUnixTimeSeconds([int64]$winParts[0]).UtcDateTime.ToString('yyyy-MM-dd HH:mm:ss:fff')
$winEnd = [DateTimeOffset]::FromUnixTimeSeconds([int64]$winParts[1]).UtcDateTime.ToString('yyyy-MM-dd HH:mm:ss:fff')
$inWindow = ($firstTs -ge $winStart) -and ($lastTs -le $winEnd) -and ($firstTs -ne '') -and ($lastTs -ne '')
$rowsMatch = ($dataRows -eq $job.rows_written)
$hasHeader = $header -like 'timestamp*'
Write-Output "A8 file=$($csv.Name) bytes=$((Get-Item $zip).Length) rows=$dataRows header_ok=$hasHeader window=$winStart..$winEnd first=$firstTs last=$lastTs in_window=$inWindow rows_match=$rowsMatch"
if (-not ($hasHeader -and $rowsMatch -and $inWindow)) { throw 'downloaded data failed validation' }

# ------------------------------------------------------------------------- A9
$schedBody = @{
    name = "acceptance-candidate-$stamp"; interval_seconds = 3600; lookback_seconds = 3600
    calendar_day = $false; credential_id = 9; index_target_id = $idx.id
    region_code = 'ap-southeast-1'; chunk_hours = 1; id_batch_size = 100
    phrases = @('<channelPartnerID>LIGHTBOX</channelPartnerID>')
    message_types = @('sessionToken')
    output_format = 'csv'; enabled = $true
} | ConvertTo-Json -Depth 6
$sched = Invoke-RestMethod -Method Post -Uri "$Api/schedules" -Headers $H -ContentType 'application/json' -Body $schedBody
Write-Output "A9 schedule id=$($sched.id)"
$schJobId = $null
for ($i = 0; $i -lt 45; $i++) {
    $schJobId = docker exec r1acc-db psql -U accept -d accept -tAc "SELECT id FROM jobs WHERE created_by = 'schedule:$($sched.id)' ORDER BY id DESC LIMIT 1"
    if ($schJobId) { break }
    Start-Sleep -Seconds 3
}
if (-not $schJobId) { throw 'no scheduled job appeared within 135s' }
$schJobId = [int]$schJobId.Trim()
Write-Output "A9 scheduled job id=$schJobId"
$schJob = Wait-Status $schJobId @('completed','failed','canceled') 240
Write-Output "A9 scheduled status=$($schJob.status) rows=$($schJob.rows_written)"
try { Invoke-RestMethod -Method Post -Uri "$Api/schedules/$($sched.id)/toggle" -Headers $H *> $null } catch { }

# ------------------------------------------------------------------- A10/A11
$badCred = Invoke-RestMethod -Method Post -Uri "$Api/credentials" -Headers $H -ContentType 'application/json' `
    -Body (@{ label = "acceptance-invalid-$stamp"; org_slug = 'evergentapse1'; refresh_token = "invalid-acceptance-$stamp"; owner_scope = 'shared' } | ConvertTo-Json)
Write-Output "A10 invalid credential id=$($badCred.id)"
$badIdx = Invoke-RestMethod -Method Post -Uri "$Api/indexes" -Headers $H -ContentType 'application/json' `
    -Body (@{ name = "acceptance-bad-$stamp"; region_code = 'ap-southeast-1'; physical_index = 'UMServices'; credential_id = $badCred.id } | ConvertTo-Json)
Write-Output "A10 bad index id=$($badIdx.id)"
$badJob = New-ExtractionJob $badIdx.id 'ap-southeast-1' $badCred.id
$badJob = Wait-Status $badJob.id @('failed','completed','canceled') 240
Write-Output "A10 job=$($badJob.id) status=$($badJob.status) err=$($badJob.error_message)"
if ($badJob.status -ne 'failed') { throw 'invalid-credential job did not fail as expected' }

$retry = Invoke-RestMethod -Method Post -Uri "$Api/jobs/$($badJob.id)/retry" -Headers $H
Write-Output "A11 retry job id=$($retry.id) status=$($retry.status)"
$retry = Wait-Status $retry.id @('failed','completed','canceled') 240
Write-Output "A11 retry status=$($retry.status) err=$($retry.error_message)"
if ($retry.status -ne 'failed') { throw 'retry job did not fail as expected' }

# ------------------------------------------------------------------------ A12
docker logs r1acc-worker 2>&1 | Out-File -Encoding utf8 "$Evidence\candidate-worker.log"
docker logs r1acc-beat 2>&1 | Out-File -Encoding utf8 "$Evidence\candidate-beat.log"
docker logs r1acc-api 2>&1 | Out-File -Encoding utf8 "$Evidence\candidate-api.log"
docker exec r1acc-db psql -U accept -d accept -c "SELECT id,status,rows_written,completed_chunks,total_chunks,created_at,started_at,finished_at,left(coalesce(error_message,'-'),100) AS error FROM jobs ORDER BY id" |
    Out-File -Encoding utf8 "$Evidence\candidate-jobs-db.txt"

@{
    commit = '7f2ac46'; worker_image = 'f96fac9f'; schema = '0034'
    login = 'ok'; credential_test = $credTest.ok
    job_id = $job.id; job_status = $job.status; rows = $job.rows_written
    csv_rows = $dataRows; csv_in_window = $inWindow; csv_rows_match = $rowsMatch
    schedule_id = $sched.id; scheduled_job_id = $schJobId; scheduled_status = $schJob.status
    bad_job_id = $badJob.id; bad_job_error = $badJob.error_message
    retry_job_id = $retry.id; retry_status = $retry.status
} | ConvertTo-Json -Depth 4 | Out-File -Encoding utf8 "$Evidence\candidate-acceptance-summary.json"

Write-Output 'CANDIDATE ACCEPTANCE COMPLETE'
