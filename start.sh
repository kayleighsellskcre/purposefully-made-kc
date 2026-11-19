#!/bin/bash
# Railway startup — bind to $PORT as fast as possible so deploys don't hang.

echo "Starting Railway deployment..."

if [ -f migrate_db.py ]; then
  echo "Running database migrations..."
  python migrate_db.py || echo "migrate_db.py failed (non-fatal)"
else
  echo "No migrate_db.py — skipping."
fi

if [ -f emergency_migration.py ]; then
  python emergency_migration.py || echo "Emergency migration skipped"
fi

echo "Starting application..."
# 1 worker: rembg/onnx cannot fit 4 copies in a typical Railway memory limit.
# A 4-worker boot downloads a 170MB model 4 times, OOMs, and the deploy never finishes.
WORKERS="${WEB_CONCURRENCY:-1}"
# Threads let one worker answer several visitors at once, so a slow page (a big admin list, an image job)
# no longer makes everyone else wait in line. Memory stays the same as one worker. Set WEB_THREADS=1 on
# Railway to go back to one-at-a-time instantly.
THREADS="${WEB_THREADS:-4}"
exec gunicorn -w "$WORKERS" --threads "$THREADS" -b 0.0.0.0:$PORT --timeout 180 --graceful-timeout 30 'app:create_app()'
