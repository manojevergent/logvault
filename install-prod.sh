#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# LogVault — single-file PRODUCTION installer (Linux, no Docker)
#
# Turns a fresh clone into a running, boot-persistent deployment:
#   • system packages (Postgres, Redis, Python, Node, nginx)
#   • dedicated `logvault` system user + directories
#   • PostgreSQL database/user with a generated password
#   • .env with generated secrets and admin account
#   • Python venvs, dependencies, Alembic migrations, seed
#   • Next.js production build (standalone)
#   • THREE systemd services (api, worker, web) — enabled on boot
#   • nginx reverse proxy + Let's Encrypt TLS (optional, via --domain)
#   • health checks and a credential summary
#
# The API is served under /api on the same domain (nginx strips the prefix).
# That keeps API routes (/jobs, /auth, …) from colliding with the web pages
# (/jobs, /jobs/new, …) which share the same names.
#
# Usage (run as root, from the repo root):
#   ./install-prod.sh --domain logvault.example.com --ssl-email ops@example.com
#   ./install-prod.sh --domain logvault.example.com --ssl-email ops@example.com --yes
#   ./install-prod.sh --domain logvault.example.com --no-tls      # test before DNS/TLS
#   ./install-prod.sh                                             # localhost, no nginx
#
# Common flags:
#   --domain HOST         Public hostname (enables nginx + HTTPS)
#   --ssl-email ADDR      Email for Let's Encrypt registration
#   --no-tls              Configure nginx for HTTP only (keeps :80)
#   --skip-nginx          Do not install/configure nginx at all
#   --api-port N          uvicorn port on 127.0.0.1 (default 8000)
#   --web-port N          Next.js port on 127.0.0.1 (default 3000)
#   --admin-email ADDR    Initial admin login
#   --admin-password PWD  Initial admin password (else generated/prompted)
#   --yes                 Non-interactive; generated admin password printed once
#   --no-build            Skip `npm run build` (reuse an existing build)
#
# Requires: bash, root, apt (Debian/Ubuntu), systemd, internet access.
# ─────────────────────────────────────────────────────────────────────────────

if [ -z "${BASH_VERSION:-}" ]; then
    echo "run with bash: sudo bash ./install-prod.sh" >&2
    exit 1
fi
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="logvault"
STATE_DIR="/var/lib/logvault"
API_PORT="8000"
WEB_PORT="3000"
DOMAIN=""
SSL_EMAIL=""
NO_TLS=0
SKIP_NGINX=0
NO_BUILD=0
YES=0
ADMIN_EMAIL=""
ADMIN_PASSWORD=""

# ── output helpers ───────────────────────────────────────────────────────────
c_reset=$'\033[0m'; c_cyan=$'\033[36m'; c_green=$'\033[32m'
c_yellow=$'\033[33m'; c_red=$'\033[31m'
step() { printf '\n%s==> %s%s\n' "$c_cyan" "$1" "$c_reset"; }
ok()   { printf '  %s[ok]%s %s\n' "$c_green" "$c_reset" "$1"; }
warn() { printf '  %s[!!]%s %s\n' "$c_yellow" "$c_reset" "$1"; }
die()  { printf '  %s[FAIL]%s %s\n' "$c_red" "$c_reset" "$1" >&2; exit 1; }

usage() { sed -n '2,/^# Requires:/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

# ── arguments ────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --domain)         DOMAIN="${2:?--domain needs a value}"; shift ;;
        --ssl-email)      SSL_EMAIL="${2:?--ssl-email needs a value}"; shift ;;
        --no-tls)         NO_TLS=1 ;;
        --skip-nginx)     SKIP_NGINX=1 ;;
        --no-build)       NO_BUILD=1 ;;
        --api-port)       API_PORT="${2:?--api-port needs a value}"; shift ;;
        --web-port)       WEB_PORT="${2:?--web-port needs a value}"; shift ;;
        --admin-email)    ADMIN_EMAIL="${2:?--admin-email needs a value}"; shift ;;
        --admin-password) ADMIN_PASSWORD="${2:?--admin-password needs a value}"; shift ;;
        --yes|-y)         YES=1 ;;
        -h|--help)        usage ;;
        *) die "unknown flag: $1 (try --help)" ;;
    esac
    shift
done

# ── preflight ────────────────────────────────────────────────────────────────
step "Preflight"
[ "$(id -u)" -eq 0 ] || die "run as root: sudo bash ./install-prod.sh"
command -v apt-get >/dev/null || die "this installer targets Debian/Ubuntu (apt)."
command -v systemctl >/dev/null || die "systemd is required."
[ -f "$APP_DIR/api/requirements.txt" ] || die "repo layout not found at $APP_DIR (run from the repo root)."
ok "root, apt, systemd, repo at $APP_DIR"

if [ -n "$DOMAIN" ]; then
    if [ "$NO_TLS" -eq 0 ] && [ -z "$SSL_EMAIL" ]; then
        warn "no --ssl-email given; certbot will prompt or TLS will be skipped."
    fi
    PUBLIC_WEB="https://$DOMAIN"; [ "$NO_TLS" -eq 1 ] && PUBLIC_WEB="http://$DOMAIN"
    if [ "$SKIP_NGINX" -eq 0 ]; then
        API_PUBLIC="$PUBLIC_WEB/api"
    else
        API_PUBLIC="$PUBLIC_WEB/api"   # still the intended public shape
    fi
else
    PUBLIC_WEB="http://localhost:$WEB_PORT"
    API_PUBLIC="http://localhost:$API_PORT"
fi

# ── system packages ──────────────────────────────────────────────────────────
step "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git build-essential \
    python3 python3-venv python3-dev python3-pip \
    postgresql postgresql-contrib libpq-dev \
    redis-server \
    nginx openssl
ok "base packages installed"

# Node 20+ (apt's node is often too old for Next.js 15).
need_node=0
if ! command -v node >/dev/null; then
    need_node=1
else
    major="$(node -v | sed 's/v//;s/\..*//')"
    [ "$major" -lt 18 ] && need_node=1
fi
if [ "$need_node" -eq 1 ]; then
    step "Installing Node.js 20"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi
ok "node $(node -v), npm $(npm -v)"

# Optional TLS tooling
if [ -n "$DOMAIN" ] && [ "$NO_TLS" -eq 0 ] && [ "$SKIP_NGINX" -eq 0 ]; then
    apt-get install -y --no-install-recommends certbot python3-certbot-nginx
    ok "certbot installed"
fi

# ── service user + directories ───────────────────────────────────────────────
step "Service user and directories"
mkdir -p "$STATE_DIR/exports" "$STATE_DIR/backups"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    # Home is the state dir (not the repo) so the service never needs to write
    # the checkout — that keeps `git pull` as root free of safe.directory noise.
    useradd --system --no-create-home --home-dir "$STATE_DIR" \
        --shell /usr/sbin/nologin "$APP_USER"
    ok "created system user $APP_USER"
else
    ok "user $APP_USER exists"
fi
chown -R "$APP_USER:$APP_USER" "$STATE_DIR"
ok "state dirs at $STATE_DIR"

# ── PostgreSQL ───────────────────────────────────────────────────────────────
step "PostgreSQL"
systemctl enable --now postgresql
for _ in $(seq 1 30); do sudo -u postgres pg_isready -q && break; sleep 1; done

DB_PASS=""
if [ -f "$APP_DIR/.env" ]; then
    DB_PASS="$(grep -E '^DATABASE_URL=' "$APP_DIR/.env" 2>/dev/null | sed -E 's#.*://logvault:([^@]*)@.*#\1#' || true)"
fi
if [ -z "$DB_PASS" ]; then
    DB_PASS="$(head -c 24 /dev/urandom | base64 | tr '+/' '-_' | tr -d '= \n')"
fi

sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='logvault'" | grep -q 1 \
    || sudo -u postgres createuser logvault
sudo -u postgres psql -q -c "ALTER USER logvault WITH PASSWORD '$DB_PASS';"
sudo -u postgres createdb -O logvault logvault 2>/dev/null || true
ok "database logvault ready"

# ── Redis ────────────────────────────────────────────────────────────────────
step "Redis"
systemctl enable --now redis-server 2>/dev/null || systemctl enable --now redis 2>/dev/null || true
for _ in $(seq 1 20); do redis-cli ping >/dev/null 2>&1 && break; sleep 1; done
ok "redis responding"

# ── .env ─────────────────────────────────────────────────────────────────────
step "Environment (.env)"
ENV_FILE="$APP_DIR/.env"
urlsafe() { head -c "$1" /dev/urandom | base64 | tr '+/' '-_' | tr -d '= \n'; }
set_env() {  # set_env KEY VALUE — safe for special characters
    if [ -f "$ENV_FILE" ] && grep -qE "^$1=" "$ENV_FILE"; then
        awk -v k="$1" -v v="$2" 'index($0,k"=")==1{print k"="v;next}{print}' "$ENV_FILE" > "$ENV_FILE.tmp"
        mv "$ENV_FILE.tmp" "$ENV_FILE"
    else
        printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
    fi
}
# dotenv truncates an unquoted value at " #" (space then hash) and treats a
# leading # as a comment. Generated secrets never contain either, but a
# user-supplied admin password might — single-quote just those.
env_safe() {
    case "$1" in
        *" #"*|"#"*)
            case "$1" in
                *"'"*) die "admin password contains both a space-hash and a single quote; choose another." ;;
                *) printf "'%s'" "$1" ;;
            esac
            ;;
        *) printf '%s' "$1" ;;
    esac
}
get_env() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true; }

if [ ! -f "$ENV_FILE" ]; then
    cp "$APP_DIR/.env.example" "$ENV_FILE"
    ok "created .env from .env.example"
else
    ok "existing .env kept (keys updated in place)"
fi

[ -n "$(get_env LAST9_ENCRYPTION_KEY)" ] && [ "$(get_env LAST9_ENCRYPTION_KEY)" != "replace-with-generated-fernet-key" ] \
    || { set_env LAST9_ENCRYPTION_KEY "$(urlsafe 32)"; ok "generated LAST9_ENCRYPTION_KEY"; }
[ -n "$(get_env JWT_SECRET)" ] && [ "$(get_env JWT_SECRET)" != "replace-with-random-secret" ] \
    || { set_env JWT_SECRET "$(urlsafe 48)"; ok "generated JWT_SECRET"; }

if [ -z "$ADMIN_EMAIL" ]; then
    if [ "$YES" -eq 1 ]; then ADMIN_EMAIL="admin@logvault.local"
    else read -rp "Initial admin email [admin@logvault.local]: " ADMIN_EMAIL
         ADMIN_EMAIL="${ADMIN_EMAIL:-admin@logvault.local}"; fi
fi
GENERATED_PW=0
if [ -z "$ADMIN_PASSWORD" ]; then
    if [ "$YES" -eq 1 ]; then
        ADMIN_PASSWORD="Logvault-$(urlsafe 9)"; GENERATED_PW=1
    else
        read -rsp "Initial admin password (hidden): " ADMIN_PASSWORD; echo
        [ -n "$ADMIN_PASSWORD" ] || die "admin password cannot be empty."
    fi
fi

set_env ENVIRONMENT production
set_env DATABASE_URL "postgresql+psycopg://logvault:$DB_PASS@127.0.0.1:5432/logvault"
set_env REDIS_URL "redis://127.0.0.1:6379/0"
set_env CELERY_BROKER_URL "redis://127.0.0.1:6379/1"
set_env CELERY_RESULT_BACKEND "redis://127.0.0.1:6379/2"
set_env STORAGE_DIR "$STATE_DIR/exports"
set_env BACKUP_DIR "$STATE_DIR/backups"
set_env INITIAL_ADMIN_EMAIL "$ADMIN_EMAIL"
set_env INITIAL_ADMIN_PASSWORD "$(env_safe "$ADMIN_PASSWORD")"
set_env NEXT_PUBLIC_API_BASE_URL "$API_PUBLIC"
set_env PUBLIC_API_BASE_URL "${PUBLIC_WEB%/}/api"
set_env WEB_BASE_URL "$PUBLIC_WEB"
if [ -n "$DOMAIN" ]; then
    set_env CORS_ORIGINS "$PUBLIC_WEB"
else
    set_env CORS_ORIGINS "http://localhost:3000,http://localhost:3001"
fi
chown "$APP_USER:$APP_USER" "$ENV_FILE"; chmod 600 "$ENV_FILE"
ok "environment written (admin: $ADMIN_EMAIL)"

# ── Python dependencies ──────────────────────────────────────────────────────
step "Python environments"
for svc in api worker; do
    venv="$APP_DIR/$svc/.venv"
    [ -x "$venv/bin/python" ] || python3 -m venv "$venv"
    "$venv/bin/pip" install --quiet --upgrade pip
    "$venv/bin/pip" install --quiet -r "$APP_DIR/$svc/requirements.txt"
    ok "$svc dependencies installed"
done
chown -R "$APP_USER:$APP_USER" "$APP_DIR/api/.venv" "$APP_DIR/worker/.venv"

step "Database migrations and seed"
( cd "$APP_DIR" && PYTHONPATH=api "$APP_DIR/api/.venv/bin/alembic" -c api/alembic.ini upgrade head )
ok "migrations at head"
( cd "$APP_DIR" && PYTHONPATH=api "$APP_DIR/api/.venv/bin/python" -m app.seed ) 2>&1 | tail -1 || true

# ── Frontend build ───────────────────────────────────────────────────────────
step "Frontend build"
if [ "$NO_BUILD" -eq 0 ]; then
    # npm ci wipes node_modules; only do it on a fresh checkout. A re-run keeps
    # the existing tree and just rebuilds (fast), which is the common case.
    if [ ! -d "$APP_DIR/web/node_modules" ]; then
        ( cd "$APP_DIR/web" && npm ci --no-audit --no-fund )
    fi
    ( cd "$APP_DIR/web" \
      && NEXT_PUBLIC_API_BASE_URL="$API_PUBLIC" NEXT_TELEMETRY_DISABLED=1 npm run build )
    ok "standalone build complete"
else
    warn "--no-build: reusing existing .next build"
fi
[ -f "$APP_DIR/web/.next/standalone/server.js" ] || die "standalone server.js missing — build failed."
# Replicate the Docker runtime layout: server.js expects .next/static and public
# beside it, not in the parent build directory.
mkdir -p "$APP_DIR/web/.next/standalone/.next"
rm -rf "$APP_DIR/web/.next/standalone/.next/static"
cp -r "$APP_DIR/web/.next/static" "$APP_DIR/web/.next/standalone/.next/static"
[ -d "$APP_DIR/web/public" ] && cp -r "$APP_DIR/web/public" "$APP_DIR/web/.next/standalone/public" || true
chown -R "$APP_USER:$APP_USER" "$APP_DIR/web/.next"
ok "runtime assets staged"

# ── systemd units ────────────────────────────────────────────────────────────
step "systemd services"

cat > /etc/systemd/system/logvault-api.service <<EOF
[Unit]
Description=LogVault API
After=network-online.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONPATH=$APP_DIR/api
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/api/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $API_PORT --workers 4 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=5
TimeoutStopSec=60
LimitNOFILE=65535
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/logvault-worker.service <<EOF
[Unit]
Description=LogVault Celery Worker + Beat
After=network-online.target postgresql.service redis-server.service logvault-api.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONPATH=$APP_DIR/worker
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/worker/.venv/bin/celery -A app.celery_app.celery worker -B --loglevel=INFO --concurrency=4
Restart=always
RestartSec=5
TimeoutStopSec=120
LimitNOFILE=65535
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/logvault-web.service <<EOF
[Unit]
Description=LogVault Web (Next.js standalone)
After=network-online.target logvault-api.service
Wants=logvault-api.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/web/.next/standalone
EnvironmentFile=$ENV_FILE
Environment=NODE_ENV=production
Environment=NEXT_TELEMETRY_DISABLED=1
Environment=PORT=$WEB_PORT
Environment=HOSTNAME=127.0.0.1
ExecStart=$(command -v node) server.js
Restart=always
RestartSec=5
TimeoutStopSec=30
LimitNOFILE=65535
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now logvault-api logvault-worker logvault-web
ok "api, worker, web enabled and started"

# ── nginx ────────────────────────────────────────────────────────────────────
if [ "$SKIP_NGINX" -eq 0 ]; then
    step "nginx reverse proxy"
    if [ -z "$DOMAIN" ]; then
        warn "no --domain: writing an nginx site for localhost (HTTP only)."
        SERVER_NAME="_"
    else
        SERVER_NAME="$DOMAIN"
    fi

    cat > /etc/nginx/sites-available/logvault <<EOF
# LogVault — API under /api (prefix stripped), everything else to Next.js.
map \$http_upgrade \$lv_connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name $SERVER_NAME;
    client_max_body_size 25m;

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:$API_PORT/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$lv_connection_upgrade;
        # SSE progress streams must not be buffered.
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
    }

    # Web
    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$lv_connection_upgrade;
        proxy_read_timeout 120s;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/logvault /etc/nginx/sites-enabled/logvault
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    systemctl enable --now nginx
    systemctl reload nginx
    ok "nginx configured for $SERVER_NAME"

    if [ -n "$DOMAIN" ] && [ "$NO_TLS" -eq 0 ]; then
        step "TLS (Let's Encrypt)"
        if [ -n "$SSL_EMAIL" ]; then
            if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$SSL_EMAIL" --redirect; then
                ok "TLS issued and HTTP redirected to HTTPS"
            else
                warn "certbot failed (DNS not pointing here yet?) — HTTP still works. Re-run: certbot --nginx -d $DOMAIN"
            fi
        else
            warn "no --ssl-email: run 'certbot --nginx -d $DOMAIN' manually to enable HTTPS."
        fi
    elif [ -n "$DOMAIN" ]; then
        warn "--no-tls: serving over HTTP only."
    fi
else
    warn "--skip-nginx: services bound to 127.0.0.1:$API_PORT and 127.0.0.1:$WEB_PORT only."
fi

# ── health checks ────────────────────────────────────────────────────────────
step "Health checks"
wait_for() {  # wait_for LABEL TIMEOUT CMD...
    local label="$1" timeout="$2"; shift 2
    local deadline=$(( SECONDS + timeout ))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if "$@" >/dev/null 2>&1; then ok "$label"; return 0; fi
        sleep 2
    done
    die "$label did not become ready in ${timeout}s (journalctl -u logvault-api -n 50)"
}
wait_for "api /health" 120 curl -fsS "http://127.0.0.1:$API_PORT/health"
wait_for "api /ready"  120 curl -fsS "http://127.0.0.1:$API_PORT/ready"
wait_for "web"         120 curl -fsS "http://127.0.0.1:$WEB_PORT/login"

# ── summary ──────────────────────────────────────────────────────────────────
echo
printf '%s========================================================================%s\n' "$c_green" "$c_reset"
printf '%s  LogVault is deployed and enabled on boot.%s\n' "$c_green" "$c_reset"
printf '%s========================================================================%s\n' "$c_green" "$c_reset"
echo "  Web UI     : $PUBLIC_WEB"
echo "  API        : $API_PUBLIC"
echo "  API docs   : $API_PUBLIC/docs"
echo "  Admin      : $ADMIN_EMAIL"
if [ "$GENERATED_PW" -eq 1 ]; then
    echo "  Password   : $ADMIN_PASSWORD    <-- generated; save it now"
else
    echo "  Password   : (the one you entered)"
fi
echo
echo "  Services   : systemctl status logvault-api logvault-worker logvault-web"
echo "  Logs       : journalctl -u logvault-api -f   (also -u logvault-worker, -u logvault-web)"
echo "  Restart    : systemctl restart logvault-api logvault-worker logvault-web"
echo "  Data       : $STATE_DIR/exports   (zip archives)"
echo "              $STATE_DIR/backups   (nightly pg_dump if the backup task runs)"
echo "  Config     : $ENV_FILE   (chmod 600)"
echo
echo "  After changing code: re-run this script (or 'npm run build' + systemctl restart logvault-web)."
printf '%s========================================================================%s\n' "$c_green" "$c_reset"
