#!/bin/bash
# Railway startup script - runs migrations then starts the app

echo "Starting Railway deployment..."

# Run database migrations
echo "Running database migrations..."
python migrate_db.py

echo "Migrations complete, starting application..."
# Start gunicorn with proper syntax
exec gunicorn -w 4 -b 0.0.0.0:$PORT --timeout 120 'app:create_app()'
