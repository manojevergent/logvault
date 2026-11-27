<#
.SYNOPSIS
Dump the local Docker Postgres database and upload it to the EC2 host.

.DESCRIPTION
Runs pg_dump inside the local Docker Postgres container (custom format),
copies the archive to this Windows host, and scp's it to the EC2 host.

This moves the database only. The LAST9_ENCRYPTION_KEY from .env must be
copied into /etc/logvault/logvault.env on the EC2 host before the restored
credentials can be decrypted - see the "Next steps" output.

.PARAMETER SshHost
EC2 host name or IP.

.PARAMETER SshUser
SSH user on the EC2 host. Default: ubuntu.

.PARAMETER SshKey
Path to the private key file. Omit to use your ssh agent / default key.

.PARAMETER RemoteDir
Directory on the EC2 host to upload into. Default: /tmp.

.PARAMETER Container
Local Docker Postgres container name. Default: last9_web_app-postgres-1.

.PARAMETER DbName
Database name. Default: logvault.

.PARAMETER DbUser
Database role. Default: logvault.

.PARAMETER SkipUpload
Dump and copy locally only; do not scp.

.EXAMPLE
.\migrate-db-to-ec2.ps1 -SshHost 10.0.1.25 -SshKey C:\keys\logvault.pem

.EXAMPLE
.\migrate-db-to-ec2.ps1 -SshHost 10.0.1.25 -SkipUpload
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SshHost,

    [string]$SshUser = "ubuntu",
    [string]$SshKey,
    [string]$RemoteDir = "/tmp",
    [string]$Container = "last9_web_app-postgres-1",
    [string]$DbName = "logvault",
    [string]$DbUser = "logvault",
    [switch]$SkipUpload
)

$ErrorActionPreference = "Stop"

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found on PATH: $Name"
    }
}

Assert-Command docker
if (-not $SkipUpload) { Assert-Command scp }

$running = docker inspect -f '{{.State.Running}}' $Container 2>$null
if ($running -ne "true") {
    throw "Container '$Container' is not running. Start the local stack first."
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archiveName = "logvault-$stamp.dump"
$localFile = Join-Path $env:TEMP $archiveName

Write-Host "Dumping $DbName from $Container ..."
docker exec $Container pg_dump -U $DbUser -d $DbName --no-owner --no-privileges -Fc -f "/tmp/$archiveName"
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed (exit $LASTEXITCODE)." }

docker cp "${Container}:/tmp/$archiveName" $localFile
if ($LASTEXITCODE -ne 0) { throw "docker cp failed (exit $LASTEXITCODE)." }

$size = (Get-Item $localFile).Length
if ($size -lt 1) { throw "Dump is empty: $localFile" }
Write-Host ("Dump written: {0} ({1:N1} MB)" -f $localFile, ($size / 1MB))

if (-not $SkipUpload) {
    $target = "${SshUser}@${SshHost}:${RemoteDir}/$archiveName"
    $scpArgs = @()
    if ($SshKey) { $scpArgs += @("-i", $SshKey) }
    $scpArgs += @($localFile, $target)

    Write-Host "Uploading to $target ..."
    & scp @scpArgs
    if ($LASTEXITCODE -ne 0) { throw "scp failed (exit $LASTEXITCODE)." }
    Write-Host "Uploaded: $target"
}

Write-Host ""
Write-Host "Next steps on the EC2 host:"
Write-Host "  1. Copy LAST9_ENCRYPTION_KEY from this machine's .env into /etc/logvault/logvault.env"
Write-Host "  2. Stop services:  sudo systemctl stop logvault-api logvault-worker logvault-beat"
Write-Host "  3. Back up the current DB:"
Write-Host "       sudo -u postgres pg_dump -Fc -d logvault -f /tmp/logvault-before.dump"
Write-Host "  4. Restore:"
Write-Host "       sudo -u postgres pg_restore --clean --if-exists --no-owner --no-privileges -d logvault /tmp/$archiveName"
Write-Host "  5. Start services:  sudo systemctl start logvault-api logvault-worker logvault-beat"
Write-Host "  6. Verify:  curl -s http://127.0.0.1:8000/ready"
