#!/usr/bin/env bash
# Terra Meta Backend - production deploy with PM2
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export DEBUG="${DEBUG:-False}"
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-api.terrameta.5ggeology.com,localhost,127.0.0.1}"
export FRONTEND_URL="${FRONTEND_URL:-https://terrameta.5ggeology.com}"
export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-https://terrameta.5ggeology.com}"
export CSRF_TRUSTED_ORIGINS="${CSRF_TRUSTED_ORIGINS:-https://terrameta.5ggeology.com,https://api.terrameta.5ggeology.com}"

echo "==> Terra Meta Backend Deploy"
echo "    API URL: https://api.terrameta.5ggeology.com"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "==> Installing dependencies..."
pip install -q -r requirements.txt

echo "==> Running migrations..."
python manage.py migrate --noinput

echo "==> Collecting static files..."
python manage.py collectstatic --noinput

mkdir -p logs media staticfiles

if ! command -v pm2 &>/dev/null; then
  echo "ERROR: pm2 is not installed. Run: npm install -g pm2"
  exit 1
fi

echo "==> Starting / restarting PM2 processes..."
pm2 startOrRestart ecosystem.config.cjs --update-env

pm2 save

echo ""
echo "Deploy complete."
echo "  API:  https://api.terrameta.5ggeology.com"
echo "  PM2:  pm2 status"
echo "  Logs: pm2 logs terra-meta-api"
