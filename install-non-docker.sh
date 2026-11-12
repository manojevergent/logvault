#!/usr/bin/env bash
# LogVault single-step installer — Linux, NO Docker.
#
# Fresh clone to running stack:
#   1. System deps (postgres, redis, python3, node, curl, git, build tools)
#   2. Postgres database + user (logvault/logvault)
#   3. .env from .env.example (existing one never overwritten) with generated
#      LAST9_ENCRYPTION_KEY / JWT_SECRET plus the initial admin account
#   4. Backend: venv + pip install + alembic migrations + seed + uvicorn on :8000
#   5. Worker: venv + pip install + celery worker + beat
#   6. Frontend: npm install + next build (standalone) + node server on :3000
#   7. Health checks + print URLs and credentials
#
# Idempotent: safe to re-run. Installed services keep running; already-applied
# steps are skipped.
#
#   ./install-non-docker.sh                       # interactive (prompts for admin)
#   ./install-non-docker.sh --yes                 # non-interactive; generated admin password printed once
#   ./install-non-docker.sh --admin-email me@co.com --admin-password 's3cret!'
#   ./install-non-docker.sh --api-base http://myhost:8000
#
# Requires: bash, root (or sudo), apt (Debian/Ubuntu), curl.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "run with bash: ./install-non-docker.sh (or: bash install-non-docker.sh)" >&2
    exit 1
fi
set -euo pipefail

DEV=0
YES=0
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
API_BASE="http://localhost:8000"
WEB_PORT="3000"
API_PORT="8000"
PID_DIR="$(pwd)/.pids"
LOG_DIR="$(pwd)/.logs"

step() { printf '\n==> %s\n' "$1"; }
ok()   { printf '  [ok] %s\n' "$1"; }
warn() { printf '  [!!] %s\n' "$1"; }
fail() {
    printf '  [FAIL] %s\n' "$1"
    echo "  Check: tail -n 50 .logs/*.log"
    exit 1
}

have() { command -v "$1" >/dev/null 2>&1; }
is_root() { [ "$(id -u)" = "0" ]; }
SUDO=""
if ! is_root; then
    if have sudo; then SUDO="sudo"; else
        fail "not root and sudo not available — re-run as root or with sudo."
    fi
fi

# ---------------- argument parsing ----------------
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) YES=1 ;;
        --admin-email) ADMIN_EMAIL="${2:?--admin-email needs a value}"; shift ;;
        --admin-password) ADMIN_PASSWORD="${2:?--admin-password needs a value}"; shift ;;
        --api-base) API_BASE="${2:?--api-base needs a value}"; shift ;;
        -h|--help)
            sed -n '2,/^Requires:/p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "unknown flag: $1 (try --help)" >&2; exit 1 ;;
    esac
    shift
done

# ---------------- 1. preflight + system deps ----------------
step "Preflight + system packages"

have curl || fail "curl not found."
have git  || fail "git not found."

# Debian/Ubuntu package set.
PKGS="curl git build-essential libpq-dev python3 python3-venv python3-pip python3-dev postgresql postgresql-contrib redis-server nodejs npm"
missing=""
for p in $PKGS; do
    if ! dpkg -s "$p" >/dev/null 2>&1; then missing="$missing $p"; fi
done
if [ -n "$missing" ]; then
    step "Installing system packages:$missing"
    $SUDO apt-get update -y
    $SUDO apt-get install -y --no-install-recommends $missing
fi
ok "system packages present"

# Node version check (Next.js 15 needs Node 18+).
if have node; then
    NODE_MAJOR="$(node -v | sed 's/v//;s/\..*//')"
    if [ "$NODE_MAJOR" -lt 18 ] 2>/dev/null; then
        warn "node is v$(node -v); Next.js 15 needs Node 18+. Frontend build may fail."
    else
        ok "node $(node -v)"
    fi
else
    fail "node not found after install step."
fi

# Start system services.
$SUDO systemctl enable --now postgresql 2>/dev/null || $SUDO service postgresql start 2>/dev/null || true
$SUDO systemctl enable --now redis-server 2>/dev/null || $SUDO systemctl enable --now redis 2>/dev/null || $SUDO service redis-server start 2>/dev/null || true
# Give postgres a moment to start; createuser/createdb below are resilient
# (|| true) and alembic will fail with a clear message if it really isn't up.
sleep 3
if have pg_isready; then
    for _ in $(seq 1 20); do
        if ($SUDO -u postgres pg_isready >/dev/null 2>&1) || pg_isready >/dev/null 2>&1; then break; fi
        sleep 1
    done
fi
ok "postgres + redis started"

# ---------------- 2. database ----------------
step "Database (logvault / logvault)"

$SUDO -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='logvault'" | grep -q 1 \
    || $SUDO -u postgres createuser logvault 2>/dev/null || true
# Set a known password so the app can connect.
$SUDO -u postgres psql -c "ALTER USER logvault WITH PASSWORD 'logvault';" >/dev/null 2>&1 || true
$SUDO -u postgres createdb -O logvault logvault 2>/dev/null || true
ok "database ready"

# ---------------- 3. .env ----------------
step "Environment file (.env)"

ENV_FILE="$(pwd)/.env"
EXAMPLE_FILE="$(pwd)/.env.example"
[ -f "$EXAMPLE_FILE" ] || fail ".env.example missing — are you in the repo root?"
if [ ! -f "$ENV_FILE" ]; then
    cp "$EXAMPLE_FILE" "$ENV_FILE"
    ok "created .env from .env.example"
else
    ok "existing .env kept (never overwritten)"
fi

get_env() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true; }
set_env() {
    awk -v k="$1" -v v="$2" '
        BEGIN { found = 0 }
        index($0, k "=") == 1 { print k "=" v; found = 1; next }
        { print }
        END { if (!found) print k "=" v }
    ' "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
}

urlsafe_key() { head -c "$1" /dev/urandom | base64 | tr '+/' '-_' | tr -d '= \n'; }

# Fernet requires 32 bytes as url-safe base64 WITH padding (44 chars).
# `urlsafe_key` strips the '=', which Fernet rejects — keep it for this key.
fernet_key() { head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'; }
valid_fernet_key() { [ "${#1}" -eq 44 ] && printf '%s' "$1" | grep -qE '^[A-Za-z0-9+/_-]{43}=$'; }

if ! valid_fernet_key "$(get_env LAST9_ENCRYPTION_KEY)"; then
    # An invalid key never encrypted anything, so replacing it is safe.
    set_env LAST9_ENCRYPTION_KEY "$(fernet_key)"
    ok "generated LAST9_ENCRYPTION_KEY"
fi
if [ "$(get_env JWT_SECRET)" = "replace-with-random-secret" ] \
    || [ -z "$(get_env JWT_SECRET)" ]; then
    set_env JWT_SECRET "$(urlsafe_key 48)"
    ok "generated JWT_SECRET"
fi
set_env CORS_ORIGINS "http://localhost:3000,http://localhost:3001"
set_env NEXT_PUBLIC_API_BASE_URL "$API_BASE"
set_env DATABASE_URL "postgresql+psycopg://logvault:logvault@localhost:5432/logvault"
set_env REDIS_URL "redis://localhost:6379/0"
set_env CELERY_BROKER_URL "redis://localhost:6379/1"
set_env CELERY_RESULT_BACKEND "redis://localhost:6379/2"

if [ -z "$ADMIN_EMAIL" ]; then
    if [ "$YES" -eq 1 ]; then ADMIN_EMAIL="admin@logvault.local";
    else
        read -rp "Initial admin email [admin@logvault.local]: " ADMIN_EMAIL
        ADMIN_EMAIL="${ADMIN_EMAIL:-admin@logvault.local}"
    fi
fi
GENERATED_PASSWORD=0
if [ -z "$ADMIN_PASSWORD" ]; then
    if [ "$YES" -eq 1 ]; then
        ADMIN_PASSWORD="Logvault-$(urlsafe_key 9)"
        GENERATED_PASSWORD=1
    else
        read -rsp "Initial admin password (hidden): " ADMIN_PASSWORD
        echo
        [ -n "$ADMIN_PASSWORD" ] || fail "admin password cannot be empty."
        GENERATED_PASSWORD=0
    fi
else
    GENERATED_PASSWORD=0
fi
set_env INITIAL_ADMIN_EMAIL "$ADMIN_EMAIL"
set_env INITIAL_ADMIN_PASSWORD "$ADMIN_PASSWORD"
ok "admin account configured ($ADMIN_EMAIL)"

# Export for subprocesses (seed reads them).
export DATABASE_URL REDIS_URL CELERY_BROKER_URL CELERY_RESULT_BACKEND
export LAST9_ENCRYPTION_KEY JWT_SECRET INITIAL_ADMIN_EMAIL INITIAL_ADMIN_PASSWORD

# ---------------- 4. backend ----------------
step "Backend API (uvicorn on :$API_PORT)"

API_VENV="$(pwd)/api/.venv"
if [ ! -x "$API_VENV/bin/python" ]; then
    python3 -m venv "$API_VENV"
fi
"$API_VENV/bin/pip" install --quiet --upgrade pip
"$API_VENV/bin/pip" install --quiet -r api/requirements.txt
ok "backend deps installed"

# Apply migrations + seed (PYTHONPATH=api so the app package resolves; cwd stays
# the repo root so settings finds .env).
PYTHONPATH=api "$API_VENV/bin/alembic" -c api/alembic.ini upgrade head
ok "migrations at head"

# Seed (sample index + sample data).
PYTHONPATH=api "$API_VENV/bin/python" -m app.seed 2>&1 | tail -1 || true

mkdir -p "$PID_DIR" "$LOG_DIR"
if [ -f "$PID_DIR/api.pid" ] && kill -0 "$(cat "$PID_DIR/api.pid")" 2>/dev/null; then
    warn "api already running (pid $(cat "$PID_DIR/api.pid")) — skipping start."
else
    PYTHONPATH=api nohup "$API_VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$API_PORT" \
        > "$LOG_DIR/api.log" 2>&1 &
    echo $! > "$PID_DIR/api.pid"
    ok "api started (pid $(cat "$PID_DIR/api.pid"))"
fi

# ---------------- 5. worker ----------------
step "Worker (celery on :$API_PORT's redis)"

WORKER_VENV="$(pwd)/worker/.venv"
if [ ! -x "$WORKER_VENV/bin/python" ]; then
    python3 -m venv "$WORKER_VENV"
fi
"$WORKER_VENV/bin/pip" install --quiet --upgrade pip
"$WORKER_VENV/bin/pip" install --quiet -r worker/requirements.txt
ok "worker deps installed"

if [ -f "$PID_DIR/worker.pid" ] && kill -0 "$(cat "$PID_DIR/worker.pid")" 2>/dev/null; then
    warn "worker already running (pid $(cat "$PID_DIR/worker.pid")) — skipping start."
else
    PYTHONPATH=worker nohup "$WORKER_VENV/bin/celery" -A app.celery_app.celery worker -B --loglevel=INFO \
        > "$LOG_DIR/worker.log" 2>&1 &
    echo $! > "$PID_DIR/worker.pid"
    ok "worker started (pid $(cat "$PID_DIR/worker.pid"))"
fi

# ---------------- 6. frontend ----------------
step "Frontend (next build + standalone server on :$WEB_PORT)"

if [ ! -d "web/node_modules" ]; then
    (cd web && npm install --quiet --no-audit --no-fund)
fi
ok "frontend deps installed"

(cd web && NEXT_PUBLIC_API_BASE_URL="$API_BASE" npm --quiet run build) \
    || fail "frontend build failed."
ok "frontend built (standalone)"

if [ -f "$PID_DIR/web.pid" ] && kill -0 "$(cat "$PID_DIR/web.pid")" 2>/dev/null; then
    warn "web already running (pid $(cat "$PID_DIR/web.pid")) — skipping start."
else
    ( cd web
      nohup env NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 \
        NEXT_PUBLIC_API_BASE_URL="$API_BASE" \
        node .next/standalone/server.js \
        > "../$LOG_DIR/web.log" 2>&1 &
      echo $!
    ) > "$PID_DIR/web.pid"
    ok "frontend started (pid $(cat "$PID_DIR/web.pid")) on :$WEB_PORT"
fi

# ---------------- 7. health checks ----------------
step "Verify"

wait_for() {
    local label="$1" timeout="$2"; shift 2
    local deadline=$((SECONDS + timeout))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if "$@" >/dev/null 2>&1; then ok "$label"; return 0; fi
        sleep 2
    done
    fail "$label did not become ready within ${timeout}s."
}

wait_for "api /health" 120 curl -fsS "$API_BASE/health"
wait_for "api /ready" 120 curl -fsS "$API_BASE/ready"
wait_for "frontend" 120 curl -fsS "http://localhost:$WEB_PORT/"

echo
echo "============================================================="
echo "  LogVault is up (non-docker)."
echo "============================================================="
echo "  Frontend :  http://localhost:$WEB_PORT"
echo "  Backend  :  $API_BASE"
echo "  API docs :  $API_BASE/docs"
echo "  Login    :  $ADMIN_EMAIL"
if [ "$GENERATED_PASSWORD" -eq 1 ]; then
    echo "  Password :  $ADMIN_PASSWORD   <-- generated; save it now"
else
    echo "  Password :  (the one you entered)"
fi
echo
echo "  PIDs :  .pids/{api,worker,web}.pid"
echo "  Logs :  .logs/{api,worker,web}.log"
echo
echo "  Stop :  kill \$(cat .pids/api.pid) \$(cat .pids/worker.pid) \$(cat .pids/web.pid)"
echo "============================================================="
