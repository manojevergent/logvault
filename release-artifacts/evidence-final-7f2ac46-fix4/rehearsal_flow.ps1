$ErrorActionPreference = 'Continue'
$Api = 'http://localhost:8011'
$Evidence = 'E:\last9_web_app-p1\release-artifacts\evidence-final-7f2ac46-fix4'

$env:REH_ADMIN_EMAIL = docker exec r1reh-api printenv INITIAL_ADMIN_EMAIL
$env:REH_ADMIN_PASSWORD = docker exec r1reh-api printenv INITIAL_ADMIN_PASSWORD
if (-not $env:REH_ADMIN_EMAIL -or -not $env:REH_ADMIN_PASSWORD) { throw 'admin env missing on r1reh-api' }

# Fresh admin for the disposable copy (bootstrap runs on first login).
docker exec last9_web_app-postgres-1 psql -U logvault -d r1rehearsal -c "DELETE FROM users" *> $null

$login = Invoke-RestMethod -Method Post -Uri "$Api/auth/login" -ContentType 'application/json' `
    -Body (@{ email = $env:REH_ADMIN_EMAIL; password = $env:REH_ADMIN_PASSWORD } | ConvertTo-Json)
if (-not $login.access_token) { throw 'login failed' }
$H = @{ Authorization = "Bearer $($login.access_token)" }

$stats = Invoke-RestMethod "$Api/jobs/stats" -Headers $H
$test = Invoke-RestMethod -Method Post -Uri "$Api/credentials/9/test" -Headers $H
Write-Output "login=ok role=$($login.role) existing_jobs=$($stats.by_status.completed) credential_test=$($test.ok)/$($test.token_status)"

$now = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$body = @{
    credential_id = 9; index_target_id = 4; region_code = 'ap-southeast-1'
    start_epoch = $now - 3600; end_epoch = $now; chunk_hours = 1; id_batch_size = 100
    phrases = @('<channelPartnerID>LIGHTBOX</channelPartnerID>')
    message_types = @('sessionToken')
    label = 'rehearsal-upgraded-copy'; customer = 'REHEARSAL'
    output_format = 'csv'; is_preview = $false
} | ConvertTo-Json -Depth 5
$job = Invoke-RestMethod -Method Post -Uri "$Api/jobs" -Headers $H -ContentType 'application/json' -Body $body
Write-Output "job=$($job.id) submitted=$($job.status)"

$deadline = (Get-Date).AddMinutes(4)
do {
    Start-Sleep -Seconds 3
    $job = Invoke-RestMethod "$Api/jobs/$($job.id)" -Headers $H
} while ($job.status -notin @('completed','failed','canceled') -and (Get-Date) -lt $deadline)
Write-Output "job=$($job.id) final=$($job.status) rows=$($job.rows_written) err=$($job.error_message)"

if ($job.status -ne 'completed') { throw 'rehearsal extraction did not complete' }

$zip = Join-Path $env:TEMP "rehearsal-job-$($job.id).zip"
Invoke-WebRequest -Uri "$Api$($job.download_url)" -OutFile $zip
$out = Join-Path $env:TEMP "rehearsal-job-$($job.id)"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive -LiteralPath $zip -DestinationPath $out -Force
$csv = Get-ChildItem $out -Filter *.csv | Select-Object -First 1
$rows = Import-Csv -LiteralPath $csv.FullName
$count = @($rows).Count
$first = [string]$rows[0].PSObject.Properties.Value[0]
$last = [string]$rows[-1].PSObject.Properties.Value[0]
$pat = '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3}) UTC'
$firstTs = [regex]::Match($first, $pat).Groups[1].Value
$lastTs = [regex]::Match($last, $pat).Groups[1].Value
$winStart = [DateTimeOffset]::FromUnixTimeSeconds($job.start_epoch).UtcDateTime.ToString('yyyy-MM-dd HH:mm:ss:fff')
$winEnd = [DateTimeOffset]::FromUnixTimeSeconds($job.end_epoch).UtcDateTime.ToString('yyyy-MM-dd HH:mm:ss:fff')
$inWindow = ($firstTs -ge $winStart) -and ($lastTs -le $winEnd) -and $firstTs -and $lastTs
Write-Output "download bytes=$((Get-Item $zip).Length) rows=$count rows_match=$($count -eq $job.rows_written) window=$winStart..$winEnd first=$firstTs last=$lastTs in_window=$inWindow"

@{
    rehearsal = 'upgraded-copy'; schema = '0034'; existing_jobs = $stats.by_status.completed
    credential_test = $test.ok; job_id = $job.id; status = $job.status; rows = $job.rows_written
    csv_rows = $count; rows_match = ($count -eq $job.rows_written); in_window = $inWindow
} | ConvertTo-Json -Depth 3 | Out-File -Encoding utf8 "$Evidence\rehearsal-summary.json"

if (-not ($count -eq $job.rows_written -and $inWindow)) { throw 'download validation failed' }
Write-Output 'REHEARSAL COMPLETE'
