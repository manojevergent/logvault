#!/bin/bash
# Rebuild and redeploy LogVault services. This stack runs baked images with no
# source bind-mount, so `docker restart` alone does NOT pick up code changes —
# the image has to be rebuilt and the container recreated from it.
#
# Usage:
#   ./deploy.sh                # rebuild + redeploy api, worker, web
#   ./deploy.sh worker         # just the worker (e.g. after a worker/ change)
#   ./deploy.sh api web        # any subset

set -e

cd "$(dirname "$0")"

SERVICES="${*:-api worker web}"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# beat runs the worker image, so rebuilding worker without recreating beat
# leaves the scheduler on the previous build. Follow worker automatically.
if echo "$SERVICES" | tr ' ' '\n' | grep -qx worker \
   && ! echo "$SERVICES" | tr ' ' '\n' | grep -qx beat; then
  SERVICES="$SERVICES beat"
fi

echo "Building: $SERVICES"
$COMPOSE build $SERVICES

# The API does not migrate on startup: without this, a deploy that adds a
# migration runs new code against the old schema. `upgrade head` is idempotent.
echo "Migrating database"
$COMPOSE run --rm --no-deps api alembic upgrade head

echo "Redeploying: $SERVICES"
$COMPOSE up -d --no-deps $SERVICES

echo "Done. Status:"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|$(echo "$SERVICES" | tr ' ' '|')"
