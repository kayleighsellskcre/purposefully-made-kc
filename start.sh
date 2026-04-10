#!/bin/bash
# Railway startup script - runs migrations then starts the app

echo "Starting Railway deployment..."
echo "Running database migrations..."

# Run the migration script
python migrate_db.py

# Also run emergency migration for design_fee
python emergency_migration.py || echo "Emergency migration skipped"

echo "Starting application..."
# Start gunicorn with proper syntax
exec gunicorn -w 4 -b 0.0.0.0:$PORT --timeout 120 'app:create_app()'
