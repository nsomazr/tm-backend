#!/usr/bin/env bash
# Terra Meta Backend - local development startup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

if [[ ! -f .env ]]; then
  echo "Copying .env.example → .env (edit credentials before production use)"
  cp .env.example .env
fi

echo "Installing Python dependencies..."
pip install -q -r requirements.txt

echo "Applying database migrations..."
python manage.py makemigrations --noinput 2>/dev/null || true
python manage.py migrate --noinput

if ! python manage.py shell -c "from apps.geography.models import Country; exit(0 if Country.objects.exists() else 1)" 2>/dev/null; then
  echo "Seeding initial data..."
  python manage.py seed_data
fi

if ! python manage.py shell -c "from apps.reports.models import Report; exit(0 if Report.objects.filter(is_active=True).exists() else 1)" 2>/dev/null; then
  echo "Seeding report catalog..."
  python manage.py seed_catalog
fi

echo ""
echo "Starting Django dev server at http://127.0.0.1:8085"
echo "API base: http://127.0.0.1:8085/api/v1/"
echo ""
python manage.py runserver 0.0.0.0:8085
