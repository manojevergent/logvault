#!/usr/bin/env bash
# LogVault single-step installer (Linux + Docker).
#
# Fresh clone to running stack:
#   1. Preflight (docker, compose, daemon, curl, conflicting ports)
#   2. .env from .env.example (existing one never overwritten) with generated
#      LAST9_ENCRYPTION_KEY / JWT_SECRET plus the initial admin account
#   3. Build + up (production overlay by default)
#   4. Wait for Postgres/Redis/API health, then migrations + seed
#   5. Verify /ready and print URLs + credentials
#
# Idempotent: safe to re-run. `up -d`, migrations and seed are no-ops when
# already done.
#
#   ./install.sh                       # interactive (prompts for admin)
#   ./install.sh --yes                 # non-interactive; generated admin password printed once
#   ./install.sh --dev                 # hot-reloading dev stack, no prod overlay
#   ./install.sh --admin-email me@co.com --admin-password 's3cret!'
#   ./install.sh --api-base http://myhost:8000
#
# Requires: bash, docker, curl.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "run with bash: ./install.sh (or: bash install.sh)" >&2
    exit 1
fi
set -euo pipefail

DEV=0
YES=0
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
API_BASE="http://localhost:8000"
COMPOSE=""

step() { printf '\n==> %s\n' "$1"; }
ok()   { printf '  [ok] %s\n' "$1"; }
warn() { printf '  [!!] %s\n' "$1"; }
fail() {
    printf '  [FAIL] %s\n' "$1"
    echo "  Check: \$COMPOSE logs api worker   (or: \$COMPOSE logs -f <service>)"
    exit 1
}

get_env() {  # get_env KEY -> value or empty
    grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true
}

set_env() {  # set_env KEY VALUE (awk, so any characters in VALUE are safe)
    awk -v k="$1" -v v="$2" '
        BEGIN { found = 0 }
        index($0, k "=") == 1 { print k "=" v; found = 1; next }
        { print }
        END { if (!found) print k "=" v }
    ' .env > .env.tmp && mv .env.tmp .env
}

urlsafe_key() {  # urlsafe_key BYTES -> random urlsafe-base64, no padding
    head -c "$1" /dev/urandom | base64 | tr '+/' '-_' | tr -d '= \n'
}

wait_for() {  # wait_for LABEL TIMEOUT CMD...
    local label="$1" timeout="$2"; shift 2
    local deadline=$((SECONDS + timeout))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if "$@" >/dev/null 2>&1; then ok "$label"; return 0; fi
        sleep 3
    done
    fail "$label did not become ready within ${timeout}s."
}

preflight() {
    step "Preflight checks"

    command -v docker >/dev/null || fail "docker not found. Install Docker Engine and re-run."
    ok "docker present"

    if docker compose version >/dev/null 2>&1; then
        COMPOSE="docker compose"
    elif command -v docker-compose >/dev/null; then
        COMPOSE="docker-compose"
    else
        fail "neither 'docker compose' nor 'docker-compose' is available."
    fi
    ok "compose present ($COMPOSE)"

    docker info >/dev/null 2>&1 || fail "Docker daemon is not running. Start it and re-run."
    ok "docker daemon running"

    command -v curl >/dev/null || fail "curl not found. Install it (e.g. apt install curl) and re-run."
    ok "curl present"

    # Ports this stack publishes (must match docker-compose.yml).
    for port in 5432 6380 8000 3001; do
        if (command -v ss >/dev/null && ss -ltn "sport = :$port" | grep -q LISTEN) \
            || (command -v netstat >/dev/null && netstat -ltn 2>/dev/null | grep -q ":$port "); then
            warn "port $port is already in use. The stack may fail to start - free it or remap it in docker-compose.yml."
        fi
    done
    ok "port check done"

    if [ "$DEV" -eq 0 ]; then
        COMPOSE="$COMPOSE -f docker-compose.yml -f docker-compose.prod.yml"
    else
        COMPOSE="$COMPOSE -f docker-compose.yml"
    fi
}

setup_env() {
    step "Environment file (.env)"

    [ -f .env.example ] || fail ".env.example missing - are you in the repo root?"
    if [ ! -f .env ]; then
        cp .env.example .env
        ok "created .env from .env.example"
    else
        ok "existing .env kept (never overwritten)"
    fi

    if [ "$(get_env LAST9_ENCRYPTION_KEY)" = "replace-with-generated-fernet-key" ] \
        || [ -z "$(get_env LAST9_ENCRYPTION_KEY)" ]; then
        set_env LAST9_ENCRYPTION_KEY "$(urlsafe_key 32)"
        ok "generated LAST9_ENCRYPTION_KEY"
    fi
    if [ "$(get_env JWT_SECRET)" = "replace-with-random-secret" ] \
        || [ -z "$(get_env JWT_SECRET)" ]; then
        set_env JWT_SECRET "$(urlsafe_key 48)"
        ok "generated JWT_SECRET"
    fi
    # The web port in docker-compose.yml is 3001; the example file only allows
    # 3000, which surfaces as a CORS error on login. Allow both.
    set_env CORS_ORIGINS "http://localhost:3000,http://localhost:3001"
    set_env NEXT_PUBLIC_API_BASE_URL "$API_BASE"

    if [ -z "$ADMIN_EMAIL" ]; then
        if [ "$YES" -eq 1 ]; then
            ADMIN_EMAIL="admin@logvault.local"
        else
            read -rp "Initial admin email [admin@logvault.local]: " ADMIN_EMAIL
            ADMIN_EMAIL="${ADMIN_EMAIL:-admin@logvault.local}"
        fi
    fi
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
}

build_up() {
    step "Build images"
    # shellcheck disable=SC2086
    if ! $COMPOSE build 2>&1 | tail -2; then
        fail "image build failed (see output above)."
    fi
    if [ "$DEV" -eq 1 ]; then ok "images built (dev stack)"; else ok "images built (prod overlay)"; fi

    step "Start stack"
    # shellcheck disable=SC2086
    if ! $COMPOSE up -d 2>&1 | tail -5; then
        fail "'compose up -d' failed."
    fi
    ok "containers started"
}

wait_healthy() {
    step "Wait for services"

    # pg_isready / redis-cli inside the (already started) containers: exact,
    # and independent of `compose ps` output formats across versions.
    # shellcheck disable=SC2086
    wait_for "postgres accepting connections" 180 \
        env COMPOSE_STR="$COMPOSE" bash -c 'exec $COMPOSE_STR exec -T postgres pg_isready -U "${POSTGRES_USER:-logvault}"'
    # shellcheck disable=SC2086
    wait_for "redis answering" 180 \
        env COMPOSE_STR="$COMPOSE" bash -c 'exec $COMPOSE_STR exec -T redis redis-cli ping | grep -q PONG'
    wait_for "api /health" 240 curl -fsS "$API_BASE/health"
}

migrate_seed() {
    step "Database migrations + seed"
    # shellcheck disable=SC2086
    $COMPOSE exec -T api alembic upgrade head 2>&1 | tail -3
    ok "migrations at head"

    # shellcheck disable=SC2086
    if $COMPOSE exec -T api python -m app.seed 2>&1 | tail -2; then
        ok "seed done"
    else
        warn "seed step failed (non-fatal) - the app still runs; see output above."
    fi
}

verify_print() {
    step "Verify"
    local ready
    ready="$(curl -fsS "$API_BASE/ready" 2>/dev/null)" \
        || fail "/ready check failed."
    ok "api /ready: $(printf '%s' "$ready" | grep -o '"status":"[a-z]*"' | head -1)"

    # Both stacks publish the web UI on 3001 (see docker-compose.yml).
    local web_port="3001"

    echo
    echo "============================================================="
    echo "  LogVault is up."
    echo "============================================================="
    echo "  Frontend :  http://localhost:$web_port"
    echo "  API docs :  $API_BASE/docs"
    echo "  Login    :  $ADMIN_EMAIL"
    if [ "$GENERATED_PASSWORD" -eq 1 ]; then
        echo "  Password :  $ADMIN_PASSWORD   <-- generated; save it now"
    else
        echo "  Password :  (the one you entered)"
    fi
    echo
    echo "  Useful:"
    echo "    \$COMPOSE logs -f api worker     # follow logs"
    echo "    \$COMPOSE ps                     # status"
    if [ "$DEV" -eq 0 ]; then
        echo "    ./deploy.sh <svc>               # rebuild after code changes"
    fi
    echo "============================================================="
}

main() {
    preflight
    setup_env
    build_up
    wait_healthy
    migrate_seed
    verify_print
}

if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
    while [ $# -gt 0 ]; do
        case "$1" in
            --dev) DEV=1 ;;
            --yes) YES=1 ;;
            --admin-email) ADMIN_EMAIL="${2:?--admin-email needs a value}"; shift ;;
            --admin-password) ADMIN_PASSWORD="${2:?--admin-password needs a value}"; shift ;;
            --api-base) API_BASE="${2:?--api-base needs a value}"; shift ;;
            -h|--help) sed -n '2,/^Requires:/p' "$0" | sed 's/^# \?//'; exit 0 ;;
            *) echo "unknown flag: $1 (try --help)" >&2; exit 1 ;;
        esac
        shift
    done
    main
fi
