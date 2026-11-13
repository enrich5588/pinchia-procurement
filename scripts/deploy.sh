#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export DEPLOY_ROOT=/srv/pinjia
export RELEASE="${1:?Usage: bash scripts/deploy.sh COMMIT_SHA}"
[[ "$RELEASE" =~ ^[0-9a-f]{40}$ ]] || { echo "Expected full commit SHA" >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$RELEASE" ]] || { echo "Checkout differs from requested commit" >&2; exit 1; }
[[ -f "$DEPLOY_ROOT/shared/production.env" && -f "$DEPLOY_ROOT/shared/server.env" ]] || {
    echo "Configure shared/production.env and shared/server.env first" >&2; exit 1;
}
exec 9>"$DEPLOY_ROOT/deploy.lock"
flock -n 9 || { echo "Another deployment is running" >&2; exit 1; }
release_dir="$DEPLOY_ROOT/releases/$RELEASE"
mkdir -p "$release_dir" "$DEPLOY_ROOT/backups"
git archive "$RELEASE" | tar --no-same-owner --same-permissions -x -C "$release_dir"
cd "$release_dir"
compose=(docker compose --env-file "$DEPLOY_ROOT/shared/server.env" -f deploy/compose.yaml)
docker build --tag "pinjia:$RELEASE" .
"${compose[@]}" run --rm --no-deps web python manage.py check --deploy --fail-level WARNING
"${compose[@]}" run --rm --no-deps web python manage.py check_m365

# Stop all app writers before taking a consistent database + attachments snapshot.
# Failures after this point leave the app stopped for an explicit recovery decision.
trap '"${compose[@]}" stop web audit_cleanup || true; echo "Deployment failed; app stopped. Inspect logs and backup before resuming; see docs/auto-deploy.md." >&2' ERR
"${compose[@]}" stop web audit_cleanup
backup="$DEPLOY_ROOT/backups/$(date -u +%Y%m%dT%H%M%SZ)-$RELEASE.tar.gz"
tar -czf "$backup" -C "$DEPLOY_ROOT/shared" data
if [[ -L "$DEPLOY_ROOT/current" ]]; then
    readlink "$DEPLOY_ROOT/current" > "$backup.previous-release"
fi
"${compose[@]}" run --rm --no-deps web python manage.py migrate --noinput
"${compose[@]}" run --rm --no-deps web python manage.py maintain_operation_logs
"${compose[@]}" run --rm --no-deps web python manage.py collectstatic --noinput --clear
"${compose[@]}" up -d --wait --wait-timeout 180
ln -sfn "$release_dir" "$DEPLOY_ROOT/current"
printf 'Deployed %s; backup: %s\n' "$RELEASE" "$backup"
