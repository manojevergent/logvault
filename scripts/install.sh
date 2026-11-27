#!/usr/bin/env bash
# shellcheck disable=SC1090
#
# LogVault — non-Docker production install for a single Linux host.
#
# Installs Postgres, Redis, Python 3.12, Node 20, Nginx and four systemd
# services (api, worker, beat, web) from a git checkout of this repo. Use this
# when the target host cannot run Docker (for example a locked-down EC2
# instance). The Docker path stays the default; this script is the alternative.
#
# Supported: Ubuntu 22.04 / 24.04, Amazon Linux 2023.
#
# Usage:
#   sudo ./scripts/install.sh                 # install or update in place
#   sudo ./scripts/install.sh --update        # rebuild app code only, restart
#   sudo ./scripts/install.sh --dry-run       # print the plan, change nothing
#   sudo ./scripts/install.sh --help
#
# Everything is configured through environment variables (see the block below)
# or a config file at /etc/logvault/install.conf. Re-running the script is the
# update path: it is idempotent and keeps the generated env file, the database
# and the exports unless you ask otherwise.
#
#   sudo DOMAIN=logs.example.com TLS=1 ./scripts/install.sh
#
set -euo pipefail

# ── configuration ────────────────────────────────────────────────────────────
# Load an optional config file first; explicit environment variables win.
INSTALL_CONF="${INSTALL_CONF:-/etc/logvault/install.conf}"
if [[ -r "$INSTALL_CONF" ]]; then
  # shellcheck source=/dev/null
  # shellcheck disable=SC1090
  set -a; . "$INSTALL_CONF"; set +a
fi

APP_USER="${APP_USER:-logvault}"
APP_DIR="${APP_DIR:-/opt/logvault}"
DATA_DIR="${DATA_DIR:-/var/lib/logvault}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/logvault}"
ENV_FILE="${ENV_FILE:-/etc/logvault/logvault.env}"
LOG_DIR="${LOG_DIR:-/var/log/logvault}"

# Public hostname. Required for TLS; without it Nginx serves a default server.
DOMAIN="${DOMAIN:-}"
TLS="${TLS:-0}"                       # 1 = obtain a Let's Encrypt certificate
TLS_EMAIL="${TLS_EMAIL:-}"            # required when TLS=1
API_PORT="${API_PORT:-8000}"          # loopback only; Nginx proxies to it
WEB_PORT="${WEB_PORT:-3000}"          # loopback only; Nginx proxies to it
API_WORKERS="${API_WORKERS:-4}"

# Database. A local Postgres instance is created unless DATABASE_URL is set.
PG_VERSION="${PG_VERSION:-}"          # empty = whatever the distro ships
DB_NAME="${DB_NAME:-logvault}"
DB_USER="${DB_USER:-logvault}"
DB_PASSWORD="${DB_PASSWORD:-}"        # empty = generated on first install
DATABASE_URL="${DATABASE_URL:-}"      # set to use an external database instead

# Redis. A local instance is used unless REDIS_URL is set.
REDIS_URL="${REDIS_URL:-}"

# Runtime knobs carried into the generated env file.
WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-4}"
EXPORT_RETENTION_DAYS="${EXPORT_RETENTION_DAYS:-30}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
# The seed script only creates a sample index. A production host gets its
# indexes from the saved-search import, so leave this off unless you want it.
SEED_SAMPLE_INDEX="${SEED_SAMPLE_INDEX:-0}"
DEFAULT_ORG_SLUG="${DEFAULT_ORG_SLUG:-evergentapse1}"
LAST9_API_BASE="${LAST9_API_BASE:-https://app.last9.io/api/v4}"

# Secrets. Empty means "generate once and keep"; set them to manage them
# yourself. Changing LAST9_ENCRYPTION_KEY later makes saved credentials
# undecryptable, so it is written once and never regenerated.
LAST9_ENCRYPTION_KEY="${LAST9_ENCRYPTION_KEY:-}"
JWT_SECRET="${JWT_SECRET:-}"

# Initial admin, created by the seed step on a fresh database.
INITIAL_ADMIN_EMAIL="${INITIAL_ADMIN_EMAIL:-}"
INITIAL_ADMIN_PASSWORD="${INITIAL_ADMIN_PASSWORD:-}"

MODE="install"
DRY_RUN=0

# ── output helpers ───────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_OFF=""
fi
step()  { printf '\n%s==>%s %s\n' "$C_OK" "$C_OFF" "$*"; }
info()  { printf '    %s\n' "$*"; }
warn()  { printf '%s  ! %s%s\n' "$C_WARN" "$*" "$C_OFF" >&2; }
die()   { printf '%s  x %s%s\n' "$C_ERR" "$*" "$C_OFF" >&2; exit 1; }
run()   {
  if (( DRY_RUN )); then printf '%s  + %s%s\n' "$C_DIM" "$*" "$C_OFF"
  else "$@"; fi
}
# systemctl/psql wrappers that stay quiet on a dry run.
svc()   { run systemctl "$@"; }

usage() {
  sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --update)   MODE="update" ;;
    --dry-run)  DRY_RUN=1 ;;
    --help|-h)  usage ;;
    *)          die "unknown argument: $1 (try --help)" ;;
  esac
  shift
done

# ── preflight ────────────────────────────────────────────────────────────────
step "Preflight"
[[ $EUID -eq 0 ]] || die "run as root (sudo ./scripts/install.sh)"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$REPO_DIR/api/app/main.py" ]] || die "not a LogVault checkout: $REPO_DIR"
info "checkout: $REPO_DIR"

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
else
  die "/etc/os-release missing; cannot identify the distribution"
fi

FAMILY=""
case "${ID:-}${ID_LIKE:-}" in
  *ubuntu*|*debian*)        FAMILY="debian" ;;
  *amzn*|*rhel*|*fedora*)   FAMILY="rhel" ;;
esac
[[ -n "$FAMILY" ]] || die "unsupported distribution: ${PRETTY_NAME:-unknown} (Ubuntu/Debian and Amazon Linux 2023 only)"

if [[ "$FAMILY" == "debian" ]]; then
  case "${VERSION_ID:-}" in
    22.04|24.04) : ;;
    *) warn "untested Ubuntu/Debian version ${VERSION_ID:-?}; continuing" ;;
  esac
fi
info "distribution: ${PRETTY_NAME:-$ID} ($FAMILY)"

if (( DRY_RUN )); then warn "dry run: nothing will be installed or restarted"; fi

if [[ "$TLS" == "1" ]]; then
  [[ -n "$DOMAIN" ]]      || die "TLS=1 requires DOMAIN"
  [[ -n "$TLS_EMAIL" ]]   || die "TLS=1 requires TLS_EMAIL (Let's Encrypt expiry notices)"
fi

# ── package installation ─────────────────────────────────────────────────────
pkg_install() {
  if [[ "$FAMILY" == "debian" ]]; then
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
  else
    run dnf install -y "$@"
  fi
}

pkg_update() {
  if [[ "$FAMILY" == "debian" ]]; then
    run env DEBIAN_FRONTEND=noninteractive apt-get update -qq
  else
    run dnf makecache -q >/dev/null
  fi
}

# True when a package is already installed (keeps re-runs fast and quiet).
pkg_present() {
  if [[ "$FAMILY" == "debian" ]]; then
    dpkg -s "$1" >/dev/null 2>&1
  else
    rpm -q "$1" >/dev/null 2>&1
  fi
}

# Start and enable a unit, tolerating the naming differences between distros.
svc_up() {
  local unit="$1" units
  if (( DRY_RUN )); then
    printf '%s  + systemctl enable --now %s%s\n' "$C_DIM" "$unit" "$C_OFF" >&2
    return 0
  fi
  # Capture first, then grep. A `systemctl ... | awk ... | grep -q` pipeline
  # returns 141 under `set -o pipefail` when grep exits on the first match and
  # the writers get SIGPIPE, which made a present unit look absent.
  units="$(systemctl list-unit-files --no-legend 2>/dev/null || true)"
  if grep -qx "${unit}.service" <<<"$units"; then
    svc enable --now "$unit" >/dev/null 2>&1 || svc start "$unit"
    return 0
  fi
  return 1
}

# Try each candidate name until one exists (redis vs redis6 vs valkey, and the
# versioned postgres units on Amazon Linux).
svc_up_any() {
  local unit
  for unit in "$@"; do
    if svc_up "$unit"; then
      echo "$unit"
      return 0
    fi
  done
  return 1
}

step "Installing system packages"
pkg_update

if [[ "$FAMILY" == "debian" ]]; then
  pkg_install ca-certificates curl gnupg git build-essential libpq-dev \
              nginx postgresql postgresql-contrib redis-server \
              software-properties-common rsync cron openssl
  # Ubuntu 22.04 ships Python 3.10; the app needs 3.11+.
  PY_BIN=""
  for cand in python3.12 python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then PY_BIN="$cand"; break; fi
  done
  if [[ -z "$PY_BIN" ]]; then
    info "adding deadsnakes PPA for Python 3.12"
    run add-apt-repository -y ppa:deadsnakes/ppa
    pkg_update
    pkg_install python3.12 python3.12-venv python3.12-dev
    PY_BIN="python3.12"
  fi
  pkg_install "${PY_BIN}-venv" "${PY_BIN}-dev" 2>/dev/null || true
else
  # Amazon Linux 2023: versioned package names, no libpq-dev equivalent.
  pkg_install ca-certificates curl git gcc gcc-c++ make libpq-devel \
              nginx rsync cronie openssl

  PG_PKG=""
  for cand in postgresql16-server postgresql15-server; do
    if dnf list --available "$cand" >/dev/null 2>&1 || rpm -q "$cand" >/dev/null 2>&1; then
      PG_PKG="$cand"; break
    fi
  done
  [[ -n "$PG_PKG" ]] || die "no supported postgresql server package in the AL2023 repos"
  pkg_install "$PG_PKG"

  # Redis 6 is what AL2023 ships; valkey is the drop-in on newer images.
  REDIS_PKG=""
  for cand in redis6 valkey; do
    if dnf list --available "$cand" >/dev/null 2>&1 || rpm -q "$cand" >/dev/null 2>&1; then
      REDIS_PKG="$cand"; break
    fi
  done
  [[ -n "$REDIS_PKG" ]] || die "no redis/valkey package in the AL2023 repos"
  pkg_install "$REDIS_PKG"

  PY_BIN=""
  for cand in python3.12 python3.11; do
    if dnf list --available "$cand" >/dev/null 2>&1 || rpm -q "$cand" >/dev/null 2>&1; then
      PY_BIN="$cand"; break
    fi
  done
  [[ -n "$PY_BIN" ]] || die "no python3.11+ package in the AL2023 repos"
  pkg_install "$PY_BIN" "${PY_BIN}-devel" "${PY_BIN}-pip" 2>/dev/null || pkg_install "$PY_BIN"
fi
if (( DRY_RUN )); then
  info "python: would install $PY_BIN"
else
  info "python: $("$PY_BIN" --version 2>&1)"
fi

# Node 20 for the Next.js build. Only needed when the web app is rebuilt.
if (( DRY_RUN )); then
  info "node: would install Node 20"
elif command -v node >/dev/null 2>&1 && [[ "$(node -v | sed 's/^v\([0-9]*\).*/\1/')" -ge 20 ]]; then
  info "node: $(node -v)"
elif [[ "$FAMILY" == "rhel" ]] && pkg_install nodejs20 >/dev/null 2>&1; then
  info "node: $(node -v)"
else
  info "installing Node 20 from NodeSource"
  run bash -c 'curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -' 2>/dev/null \
    || run bash -c 'curl -fsSL https://deb.nodesource.com/setup_20.x | bash -'
  pkg_install nodejs
  info "node: $(node -v)"
fi

# ── service user and directories ─────────────────────────────────────────────
step "Service user and directories"
if ! id "$APP_USER" >/dev/null 2>&1; then
  run useradd --system --user-group --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
  info "created user $APP_USER"
else
  info "user $APP_USER exists"
fi

for d in "$APP_DIR" "$DATA_DIR/exports" "$BACKUP_DIR" "$LOG_DIR"; do
  run install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$d"
done
# The config directory stays root-owned: the app user may read the env file but
# must not be able to replace it.
run install -d -o root -g "$APP_USER" -m 0750 "$(dirname "$ENV_FILE")"

# ── PostgreSQL ───────────────────────────────────────────────────────────────
step "PostgreSQL"
if [[ -n "$DATABASE_URL" ]]; then
  info "using provided DATABASE_URL (skipping local database setup)"
else
  if PG_UNIT="$(svc_up_any postgresql postgresql-16 postgresql-15)"; then
    info "postgresql service is up ($PG_UNIT)"
  else
    # AL2023 does not create the cluster on install.
    if [[ "$FAMILY" == "rhel" ]] && command -v postgresql-setup >/dev/null 2>&1; then
      run postgresql-setup --initdb
      PG_UNIT="$(svc_up_any postgresql postgresql-16 postgresql-15)" || die "could not start postgresql"
      info "postgresql service is up ($PG_UNIT)"
    else
      die "postgresql service not found"
    fi
  fi

  if [[ -z "$DB_PASSWORD" ]]; then
    if [[ -f "$ENV_FILE" ]] && grep -q '^LOGVAULT_DB_PASSWORD=' "$ENV_FILE"; then
      DB_PASSWORD="$(sed -n 's/^LOGVAULT_DB_PASSWORD=//p' "$ENV_FILE" | head -1)"
    elif (( DRY_RUN )); then
      DB_PASSWORD="<generated-on-install>"
    else
      DB_PASSWORD="$(openssl rand -hex 24)"
      info "generated a database password"
    fi
  fi

  # Idempotent role + database creation. psql runs as the postgres superuser
  # over the local socket, so no password is needed for this step.
  psql_super() {
    if (( DRY_RUN )); then return 0; fi
    run sudo -u postgres psql -v ON_ERROR_STOP=1 -qtAc "$1"
  }

  if [[ "$(psql_super "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")" != "1" ]]; then
    run sudo -u postgres psql -v ON_ERROR_STOP=1 -qc \
      "CREATE ROLE \"$DB_USER\" LOGIN PASSWORD '$DB_PASSWORD'"
    info "created role $DB_USER"
  else
    run sudo -u postgres psql -v ON_ERROR_STOP=1 -qc \
      "ALTER ROLE \"$DB_USER\" WITH LOGIN PASSWORD '$DB_PASSWORD'"
    info "role $DB_USER exists; password synced with the env file"
  fi

  if [[ "$(psql_super "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" != "1" ]]; then
    run sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
    info "created database $DB_NAME"
  else
    info "database $DB_NAME exists"
  fi

  DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME"

  # Password auth over loopback. Ubuntu's default already allows it; AL2023's
  # initdb default is peer/ident, which would reject the API's TCP login.
  PG_HBA=""
  for cand in /etc/postgresql/*/main/pg_hba.conf /var/lib/pgsql/data/pg_hba.conf; do
    [[ -f "$cand" ]] && PG_HBA="$cand" && break
  done
  if [[ -n "$PG_HBA" ]] && ! grep -qE '^host\s+all\s+all\s+127\.0\.0\.1/32\s+(scram-sha-256|md5)' "$PG_HBA"; then
    run bash -c "printf '\nhost all all 127.0.0.1/32 scram-sha-256\n' >> '$PG_HBA'"
    svc reload postgresql >/dev/null 2>&1 || true
    info "allowed password auth on 127.0.0.1 in $PG_HBA"
  fi
fi

# ── Redis ────────────────────────────────────────────────────────────────────
step "Redis"
if [[ -n "$REDIS_URL" ]]; then
  info "using provided REDIS_URL"
else
  if REDIS_UNIT="$(svc_up_any redis-server redis redis6 valkey)"; then
    info "redis is up ($REDIS_UNIT)"
  else
    die "no redis/valkey service found"
  fi
  REDIS_URL="redis://127.0.0.1:6379/0"
fi

# ── application code ─────────────────────────────────────────────────────────
step "Application code"
# The script is run from a checkout. Two shapes are supported:
#   * run from APP_DIR itself   -> the checkout is the deployment; `--update`
#                                  pulls it in place.
#   * run from another clone    -> that clone is the source of truth; it is
#                                  synced into APP_DIR on every run, so you
#                                  pull once and re-run the installer.
REPO_REAL="$(cd "$REPO_DIR" && pwd -P)"
if [[ -d "$APP_DIR" ]]; then APP_REAL="$(cd "$APP_DIR" && pwd -P)"; else APP_REAL="$APP_DIR"; fi

if [[ "$REPO_REAL" == "$APP_REAL" ]]; then
  info "running from $APP_DIR"
  if [[ "$MODE" == "update" && -d "$APP_DIR/.git" ]]; then
    run sudo -u "$APP_USER" git -C "$APP_DIR" fetch --prune origin
    run sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
  fi
  # A fresh clone made as root has to become writable by the service user
  # before the venvs and the web build can be created.
  if [[ "$MODE" == "install" ]] && [[ "$(stat -c %U "$APP_DIR" 2>/dev/null || echo '')" == "root" ]]; then
    run chown -R "$APP_USER:$APP_USER" "$APP_DIR"
  fi
else
  info "syncing $REPO_DIR -> $APP_DIR"
  if [[ "$MODE" == "update" && -d "$REPO_DIR/.git" ]]; then
    run git -C "$REPO_DIR" pull --ff-only \
      || warn "could not pull $REPO_DIR; syncing the checkout as-is"
  fi
  run rsync -a --delete \
    --exclude node_modules --exclude .next --exclude __pycache__ \
    --exclude '.venv' --exclude '*.pyc' --exclude '.pytest_cache' \
    --exclude '.ruff_cache' --exclude 'release-artifacts' \
    --exclude '*.log' --exclude 'web/tsconfig.tsbuildinfo' \
    "$REPO_DIR/" "$APP_DIR/"
  run chown -R "$APP_USER:$APP_USER" "$APP_DIR"
  info "copied checkout to $APP_DIR"
fi

if (( ! DRY_RUN )); then
  [[ -f "$APP_DIR/api/requirements.txt" ]] || die "api/requirements.txt missing in $APP_DIR"
  [[ -f "$APP_DIR/worker/requirements.txt" ]] || die "worker/requirements.txt missing in $APP_DIR"
fi

# ── Python environments ──────────────────────────────────────────────────────
step "Python environments"
# Separate venvs: the API and the worker have different dependency sets and a
# worker-only upgrade should never be able to break the API.
for part in api worker; do
  if [[ ! -x "$APP_DIR/$part/.venv/bin/python" ]]; then
    run sudo -u "$APP_USER" "$PY_BIN" -m venv "$APP_DIR/$part/.venv"
    info "created $part venv"
  fi
  run sudo -u "$APP_USER" "$APP_DIR/$part/.venv/bin/pip" install --upgrade pip wheel >/dev/null
  run sudo -u "$APP_USER" env PIP_NO_CACHE_DIR=1 \
    "$APP_DIR/$part/.venv/bin/pip" install -r "$APP_DIR/$part/requirements.txt"
  info "$part dependencies installed"
done

# ── environment file ─────────────────────────────────────────────────────────
step "Configuration file"
# Read a previous value, so updates never rotate a secret by accident. Rotating
# LAST9_ENCRYPTION_KEY would make every saved Last9 token undecryptable.
env_get() {
  [[ -f "$ENV_FILE" ]] || return 0
  sed -n "s/^$1=//p" "$ENV_FILE" | head -1
}

SCHEME="http"
[[ "$TLS" == "1" ]] && SCHEME="https"
PUBLIC_HOST="${DOMAIN:-$(hostname -f 2>/dev/null || hostname)}"
API_BASE_URL="${SCHEME}://${PUBLIC_HOST}/api"
WEB_BASE_URL="${SCHEME}://${PUBLIC_HOST}"

[[ -n "$LAST9_ENCRYPTION_KEY" ]] || LAST9_ENCRYPTION_KEY="$(env_get LAST9_ENCRYPTION_KEY)"
if [[ -z "$LAST9_ENCRYPTION_KEY" ]]; then
  if (( DRY_RUN )); then
    LAST9_ENCRYPTION_KEY="<generated-on-install>"
  else
    LAST9_ENCRYPTION_KEY="$("$APP_DIR/api/.venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  fi
fi
[[ -n "$JWT_SECRET" ]]          || JWT_SECRET="$(env_get JWT_SECRET)"
if [[ -z "$JWT_SECRET" ]]; then
  if (( DRY_RUN )); then JWT_SECRET="<generated-on-install>"; else JWT_SECRET="$(openssl rand -hex 32)"; fi
fi
INITIAL_ADMIN_EMAIL="${INITIAL_ADMIN_EMAIL:-$(env_get INITIAL_ADMIN_EMAIL)}"
INITIAL_ADMIN_EMAIL="${INITIAL_ADMIN_EMAIL:-admin@logvault.local}"
INITIAL_ADMIN_PASSWORD="${INITIAL_ADMIN_PASSWORD:-$(env_get INITIAL_ADMIN_PASSWORD)}"
GENERATED_ADMIN_PASSWORD=0
if [[ -z "$INITIAL_ADMIN_PASSWORD" ]]; then
  if (( DRY_RUN )); then
    INITIAL_ADMIN_PASSWORD="<generated-on-install>"
  else
    INITIAL_ADMIN_PASSWORD="$(openssl rand -hex 12)"
    GENERATED_ADMIN_PASSWORD=1
  fi
fi

ENV_TMP="$(mktemp)"
chmod 600 "$ENV_TMP"
emit() { printf '%s=%s\n' "$1" "$2" >>"$ENV_TMP"; }

emit ENVIRONMENT production
emit LOG_LEVEL INFO
emit DATABASE_URL "$DATABASE_URL"
emit REDIS_URL "$REDIS_URL"
emit CELERY_BROKER_URL "redis://127.0.0.1:6379/1"
emit CELERY_RESULT_BACKEND "redis://127.0.0.1:6379/2"
emit LAST9_ENCRYPTION_KEY "$LAST9_ENCRYPTION_KEY"
emit JWT_SECRET "$JWT_SECRET"
emit DEFAULT_ORG_SLUG "$DEFAULT_ORG_SLUG"
emit LAST9_API_BASE "$LAST9_API_BASE"
emit CORS_ORIGINS "$WEB_BASE_URL"
emit PUBLIC_API_BASE_URL "$API_BASE_URL"
emit WEB_BASE_URL "$WEB_BASE_URL"
emit STORAGE_DIR "$DATA_DIR/exports"
emit BACKUP_DIR "$BACKUP_DIR"
emit DOWNLOAD_URL_TTL_SECONDS 604800
emit EXPORT_RETENTION_DAYS "$EXPORT_RETENTION_DAYS"
emit AUTO_REGISTER_FORMATS true
emit MIN_FREE_DISK_GB 10
emit WORKER_CONCURRENCY "$WORKER_CONCURRENCY"
emit STALE_JOB_MINUTES 60
emit STALE_RECLAIM_MINUTES 10
emit HEALTH_CHECK_INTERVAL_SECONDS 60
emit BACKUP_STALE_HOURS 36
emit WORKER_BEAT_STALE_SECONDS 300
emit LOGIN_MAX_ATTEMPTS 5
emit LOGIN_LOCKOUT_SECONDS 900
emit INITIAL_ADMIN_EMAIL "$INITIAL_ADMIN_EMAIL"
emit INITIAL_ADMIN_PASSWORD "$INITIAL_ADMIN_PASSWORD"
emit NEXT_PUBLIC_API_BASE_URL "$API_BASE_URL"
# Kept for re-runs and the backup timer; the app itself reads DATABASE_URL.
emit LOGVAULT_DB_PASSWORD "$DB_PASSWORD"

run install -m 0640 -o root -g "$APP_USER" "$ENV_TMP" "$ENV_FILE"
rm -f "$ENV_TMP"
info "wrote $ENV_FILE"

# ── database migrations and admin seed ───────────────────────────────────────
step "Database migrations"
run sudo -u "$APP_USER" bash -c \
  "set -a; . '$ENV_FILE'; set +a; cd '$APP_DIR/api' && exec .venv/bin/alembic upgrade head"

if [[ "$SEED_SAMPLE_INDEX" == "1" && -f "$APP_DIR/api/app/seed.py" ]]; then
  info "seeding the sample index"
  run sudo -u "$APP_USER" bash -c \
    "set -a; . '$ENV_FILE'; set +a; cd '$APP_DIR/api' && exec .venv/bin/python -m app.seed"
fi

# ── web build (Next.js standalone) ───────────────────────────────────────────
step "Web build"
if [[ "$MODE" == "update" && "${SKIP_WEB_BUILD:-0}" == "1" ]]; then
  info "skipped (SKIP_WEB_BUILD=1)"
  WEB_START="node .next/standalone/server.js"
else
  # NEXT_PUBLIC_* is inlined into the browser bundle at build time, so the API
  # base URL has to be present here — setting it only at runtime has no effect.
  run sudo -u "$APP_USER" bash -c \
    "cd '$APP_DIR/web' && (npm ci --no-audit --no-fund || npm install --no-audit --no-fund)"
  run sudo -u "$APP_USER" bash -c \
    "cd '$APP_DIR/web' && NEXT_PUBLIC_API_BASE_URL='$API_BASE_URL' NEXT_TELEMETRY_DISABLED=1 npm run build"
  # `output: "standalone"` writes a server plus the node_modules it needs; the
  # static assets and public files are not copied by Next and must be added.
  if [[ -d "$APP_DIR/web/.next/standalone" ]]; then
    run sudo -u "$APP_USER" bash -c \
      "mkdir -p '$APP_DIR/web/.next/standalone/.next' && rsync -a '$APP_DIR/web/.next/static/' '$APP_DIR/web/.next/standalone/.next/static/'"
    if [[ -d "$APP_DIR/web/public" ]]; then
      run sudo -u "$APP_USER" bash -c \
        "rsync -a '$APP_DIR/web/public/' '$APP_DIR/web/.next/standalone/public/'"
    fi
    WEB_START="node .next/standalone/server.js"
    info "standalone server: $WEB_START"
  else
    WEB_START="node node_modules/next/dist/bin/next start -p $WEB_PORT"
    warn "standalone output not found; falling back to next start"
  fi
fi

NODE_BIN="$(command -v node 2>/dev/null || echo /usr/bin/node)"

# ── systemd services ─────────────────────────────────────────────────────────
step "systemd services"
UNIT_DIR="/etc/systemd/system"

write_unit() {
  local name="$1"
  if (( DRY_RUN )); then
    printf '%s  + write %s/%s%s\n' "$C_DIM" "$UNIT_DIR" "$name" "$C_OFF"
    cat >/dev/null
    return 0
  fi
  cat >"$UNIT_DIR/$name"
  info "wrote $UNIT_DIR/$name"
}

write_unit logvault-api.service <<EOF
[Unit]
Description=LogVault API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/api
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/api/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $API_PORT --workers $API_WORKERS --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=5
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$DATA_DIR $LOG_DIR

[Install]
WantedBy=multi-user.target
EOF

write_unit logvault-worker.service <<EOF
[Unit]
Description=LogVault extraction worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/worker
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/worker/.venv/bin/celery -A app.celery_app.celery worker --loglevel=INFO --concurrency=$WORKER_CONCURRENCY
Restart=always
RestartSec=5
# Long stop window: an in-flight chunk must finish writing its checkpoint.
TimeoutStopSec=120
KillSignal=SIGTERM
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$DATA_DIR $LOG_DIR

[Install]
WantedBy=multi-user.target
EOF

write_unit logvault-beat.service <<EOF
[Unit]
Description=LogVault scheduler (single-instance guarded)
After=network-online.target
Wants=network-online.target
# The Redis lock has a 90s TTL; a restart overlap must keep retrying, not
# trip systemd's start-rate limit.
StartLimitIntervalSec=0

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/worker
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/worker/.venv/bin/python -m app.beat_guard
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

write_unit logvault-web.service <<EOF
[Unit]
Description=LogVault web
After=network-online.target logvault-api.service
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/web
Environment=NODE_ENV=production
Environment=PORT=$WEB_PORT
Environment=HOSTNAME=127.0.0.1
Environment=NEXT_TELEMETRY_DISABLED=1
ExecStart=$NODE_BIN $WEB_START
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$APP_DIR/web

[Install]
WantedBy=multi-user.target
EOF

# ── nightly database backup ──────────────────────────────────────────────────
step "Backup timer"
if (( DRY_RUN )); then
  info "would write /usr/local/bin/logvault-backup and its timer"
else
  cat >/usr/local/bin/logvault-backup <<'BACKUP'
#!/usr/bin/env bash
set -euo pipefail

# Parse the SQLAlchemy URL rather than requiring the password twice.
url="${DATABASE_URL:?DATABASE_URL is required}"
rest="${url#*://}"
creds="${rest%%@*}"
hostpart="${rest#*@}"
user="${creds%%:*}"
pass="${creds#*:}"
hostport="${hostpart%%/*}"
db="${hostport#*/}"
db="${db%%\?*}"
host="${hostport%%:*}"
port="${hostport#*:}"
[[ "$port" == "$hostport" ]] && port=5432

export PGPASSWORD="$pass"
mkdir -p "${BACKUP_DIR:?BACKUP_DIR is required}"
stamp="$(date +%Y%m%d-%H%M%S)"
out="${BACKUP_DIR}/logvault-${stamp}.dump"
pg_dump -h "$host" -p "$port" -U "$user" -d "$db" -Fc -f "$out"
find "$BACKUP_DIR" -name 'logvault-*.dump' -mtime +"${BACKUP_RETENTION_DAYS:-14}" -delete
echo "wrote $out"
BACKUP
  chmod 0755 /usr/local/bin/logvault-backup
fi

write_unit logvault-backup.service <<EOF
[Unit]
Description=LogVault database backup

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
EnvironmentFile=$ENV_FILE
ExecStart=/usr/local/bin/logvault-backup
EOF

write_unit logvault-backup.timer <<'EOF'
[Unit]
Description=Nightly LogVault database backup

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF

# ── nginx ────────────────────────────────────────────────────────────────────
step "Nginx"
NGINX_CONF="/etc/nginx/conf.d/logvault.conf"

# The API routes are mounted at the root, so /api/ is stripped when proxying.
# SSE (job progress) needs buffering off and a long read timeout.
nginx_proxy_api() {
  cat <<EOF
    location /api/ {
        proxy_pass http://127.0.0.1:${API_PORT}/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
EOF
}

nginx_proxy_web() {
  cat <<EOF
    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
    }
EOF
}

# server_name without default_server: a distro's stock default server (AL2023
# ships one inside nginx.conf) would otherwise collide with "duplicate default
# server" and fail nginx -t. Requests reach us by matching a name, so the
# host's own names are included when no domain is configured.
HOST_NAMES="$(hostname -f 2>/dev/null || hostname) $(hostname) $(hostname -I 2>/dev/null | awk '{print $1}')"
SERVER_NAMES="${DOMAIN:-_} ${HOST_NAMES}"

nginx_write_http() {
  {
    printf 'server {\n'
    printf '    listen 80;\n'
    printf '    listen [::]:80;\n'
    printf '    server_name %s;\n\n' "$SERVER_NAMES"
    printf '    client_max_body_size 20m;\n\n'
    printf '    location /.well-known/acme-challenge/ {\n        root /var/www/certbot;\n    }\n\n'
    nginx_proxy_api
    printf '\n'
    nginx_proxy_web
    printf '}\n'
  } >"$NGINX_CONF"
}

nginx_write_tls() {
  local cert="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
  local key="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
  {
    printf 'server {\n'
    printf '    listen 80;\n'
    printf '    listen [::]:80;\n'
    printf '    server_name %s;\n\n' "$DOMAIN"
    printf '    location /.well-known/acme-challenge/ {\n        root /var/www/certbot;\n    }\n'
    printf '    location / {\n        return 301 https://$host$request_uri;\n    }\n}\n\n'
    printf 'server {\n'
    printf '    listen 443 ssl http2;\n'
    printf '    listen [::]:443 ssl http2;\n'
    printf '    server_name %s;\n\n' "$DOMAIN"
    printf '    ssl_certificate %s;\n' "$cert"
    printf '    ssl_certificate_key %s;\n' "$key"
    printf '    ssl_protocols TLSv1.2 TLSv1.3;\n'
    printf '    ssl_prefer_server_ciphers off;\n'
    printf '    client_max_body_size 20m;\n\n'
    nginx_proxy_api
    printf '\n'
    nginx_proxy_web
    printf '}\n'
  } >"$NGINX_CONF"
}

run install -d -m 0755 /var/www/certbot
if [[ "$FAMILY" == "debian" ]]; then
  # A dedicated host: the distro's default site would shadow `server_name _`.
  run rm -f /etc/nginx/sites-enabled/default
fi

if (( DRY_RUN )); then
  info "would write $NGINX_CONF and reload nginx"
else
  if [[ "$TLS" == "1" ]]; then
    nginx_write_http
    nginx -t >/dev/null || die "nginx rejected the HTTP config"
    svc enable --now nginx >/dev/null 2>&1 || true
    systemctl reload nginx || systemctl start nginx

    CERTBOT="$(command -v certbot || true)"
    if [[ -z "$CERTBOT" ]]; then
      info "installing certbot into a dedicated venv"
      "$PY_BIN" -m venv /opt/logvault/certbot-venv
      /opt/logvault/certbot-venv/bin/pip install -q --upgrade pip certbot
      CERTBOT=/opt/logvault/certbot-venv/bin/certbot
    fi
    "$CERTBOT" certonly --webroot -w /var/www/certbot -d "$DOMAIN" \
      --non-interactive --agree-tos -m "$TLS_EMAIL" --keep-until-expiring \
      || die "certbot failed; check that $DOMAIN resolves here and port 80 is open"
    nginx_write_tls

    # A distro-packaged certbot ships its own timer; a venv install does not.
    # Register one either way — `certbot renew` is a no-op when the cert is not
    # close to expiry.
    write_unit logvault-certbot-renew.service <<EOF
[Unit]
Description=Renew the LogVault TLS certificate
After=network-online.target

[Service]
Type=oneshot
ExecStart=$CERTBOT renew --quiet --deploy-hook "systemctl reload nginx"
EOF
    write_unit logvault-certbot-renew.timer <<'EOF'
[Unit]
Description=Twice-daily LogVault certificate renewal check

[Timer]
OnCalendar=*-*-* 00,12:17:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
EOF
    svc enable --now logvault-certbot-renew.timer >/dev/null 2>&1 || true
  else
    nginx_write_http
  fi
  nginx -t || die "nginx rejected $NGINX_CONF"
  svc enable --now nginx >/dev/null 2>&1 || true
  systemctl reload nginx || systemctl start nginx
  info "nginx serving ${DOMAIN:-this host}"
fi

# ── start everything ─────────────────────────────────────────────────────────
step "Starting services"
svc daemon-reload
for unit in logvault-api logvault-worker logvault-beat logvault-web; do
  if [[ "$MODE" == "update" ]]; then
    svc restart "$unit" >/dev/null 2>&1 || svc start "$unit"
  else
    svc enable --now "$unit" >/dev/null 2>&1 || svc start "$unit"
  fi
done
svc enable --now logvault-backup.timer >/dev/null 2>&1 || true

if (( DRY_RUN )); then
  warn "dry run complete; no service was started"
  exit 0
fi

# ── health check ─────────────────────────────────────────────────────────────
step "Health check"
ok=0
for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/ready" >/dev/null 2>&1 \
     && curl -fsS "http://127.0.0.1:${WEB_PORT}/login" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 2
done
if (( ok )); then
  info "api /ready and web /login respond"
else
  warn "services did not answer within 40s; check: journalctl -u logvault-api -n 80"
fi

# ── summary ──────────────────────────────────────────────────────────────────
step "Installed"
cat <<EOF
  Web:        ${WEB_BASE_URL}
  API:        ${API_BASE_URL}
  Env file:   ${ENV_FILE}
  Exports:    ${DATA_DIR}/exports
  Backups:    ${BACKUP_DIR} (nightly 02:30, ${BACKUP_RETENTION_DAYS}-day retention)

  Services:   systemctl status logvault-api logvault-worker logvault-beat logvault-web
  Logs:       journalctl -u logvault-api -f

  Admin:      ${INITIAL_ADMIN_EMAIL}
EOF
if [[ "$GENERATED_ADMIN_PASSWORD" == "1" ]]; then
  printf '  Password:   %s  %s(shown once; also stored in %s)%s\n' \
    "$INITIAL_ADMIN_PASSWORD" "$C_WARN" "$ENV_FILE" "$C_OFF"
else
  printf '  Password:   (unchanged; see %s)\n' "$ENV_FILE"
fi
cat <<EOF

  Import the saved searches exported from the old instance:
    python3 ${APP_DIR}/scripts/import_saved_searches.py \\
      --base-url http://127.0.0.1:${API_PORT} \\
      --email '${INITIAL_ADMIN_EMAIL}' --password '<the password above>' \\
      --bundle /path/to/saved-searches-bundle.json --dry-run

  AWS security group: allow 80/443 only. ${API_PORT} and ${WEB_PORT} listen on
  127.0.0.1 and are reached through Nginx; Postgres and Redis are local.

  Update later:  sudo ${APP_DIR}/scripts/install.sh --update
EOF
