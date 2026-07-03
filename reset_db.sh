#!/usr/bin/env bash
# Drop all tables and re-run migrations + seed (development only)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source .venv/bin/activate

read -r -p "This will DELETE ALL DATA in the configured database. Continue? [y/N] " confirm
if [[ "${confirm,,}" != "y" ]]; then
  echo "Aborted."
  exit 0
fi

python manage.py flush --noinput 2>/dev/null || true

python <<'PY'
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]
    for table in tables:
        cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
print(f"Dropped {len(tables)} tables.")
PY

python manage.py migrate --noinput
python manage.py seed_data

echo "Database reset complete."
