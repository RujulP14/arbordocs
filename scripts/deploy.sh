#!/usr/bin/env bash
# Deploys ArborDocs to Fly.io: web + bot process groups, secrets from .env,
# migrations via Fly's release_command (see fly.toml). Idempotent — safe to
# re-run. Requires: flyctl installed and `fly auth login` already done.
#
# Secrets NOT read from .env (must be set once manually, see below):
#   DATABASE_URL   — local .env points at docker-compose Postgres; prod must
#                     point at your Neon connection string instead.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v fly &>/dev/null && ! command -v flyctl &>/dev/null; then
  echo "flyctl not found. Install with: brew install flyctl" >&2
  exit 1
fi
FLY=$(command -v fly || command -v flyctl)

if [ ! -f fly.toml ]; then
  echo "fly.toml not found in $(pwd)" >&2
  exit 1
fi

APP_NAME=$(grep -E '^app[[:space:]]*=' fly.toml | sed -E 's/^app[[:space:]]*=[[:space:]]*"(.*)"/\1/')
if [ "$APP_NAME" = "CHANGE_ME_ARBORDOCS_APP_NAME" ] || [ -z "$APP_NAME" ]; then
  echo "Set a real, globally-unique app name in fly.toml before deploying." >&2
  exit 1
fi

echo "==> Target Fly app: $APP_NAME"

if ! "$FLY" status --app "$APP_NAME" &>/dev/null; then
  echo "==> App '$APP_NAME' does not exist yet, creating it..."
  "$FLY" apps create "$APP_NAME"
else
  echo "==> App '$APP_NAME' already exists, reusing it."
fi

if [ ! -f .env ]; then
  echo ".env not found — copy .env.example and fill in real values first." >&2
  exit 1
fi

if [ -z "${DATABASE_URL_PROD:-}" ]; then
  echo "DATABASE_URL_PROD is not set in your shell environment." >&2
  echo "Export your Neon connection string before running this script, e.g.:" >&2
  echo "  export DATABASE_URL_PROD='postgresql+asyncpg://<user>:<pass>@<host>/<db>'" >&2
  exit 1
fi

echo "==> Pushing secrets to Fly (from .env, excluding DATABASE_URL/ENV/LOG_LEVEL/BASE_URL)"
SECRET_ARGS=()
while IFS='=' read -r key value; do
  [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
  case "$key" in
    DATABASE_URL|ENV|LOG_LEVEL|BASE_URL) continue ;;
  esac
  value="${value%%#*}"
  value="$(echo -n "$value" | sed -e 's/[[:space:]]*$//')"
  [ -z "$value" ] && continue
  SECRET_ARGS+=("$key=$value")
done < .env

SECRET_ARGS+=("DATABASE_URL=$DATABASE_URL_PROD")
SECRET_ARGS+=("ENV=production")
SECRET_ARGS+=("BASE_URL=https://$APP_NAME.fly.dev")

"$FLY" secrets set --app "$APP_NAME" "${SECRET_ARGS[@]}"

echo "==> Deploying (release_command runs 'alembic upgrade head' automatically)"
"$FLY" deploy --app "$APP_NAME"

echo "==> Scaling process groups (web/bot/worker: 1 machine each, no autoscale-to-zero)"
"$FLY" scale count web=1 bot=1 worker=1 --app "$APP_NAME" --yes

echo "==> Done. Web app: https://$APP_NAME.fly.dev"
echo "==> Remember to update your GitHub App's callback URL and Discord's redirect URI to point at that domain."
