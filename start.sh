#!/bin/bash
# Railway startup script - runs migrations then starts the app

echo "Starting Railway deployment..."

# Run database migrations
echo "Running database migrations..."
python migrate_db.py

# Check if migration succeeded
if [ $? -eq 0 ]; then
    echo "✓ Migrations complete, starting application..."
    # Start gunicorn
    exec gunicorn -w 4 -b 0.0.0.0:$PORT app:app
else
    echo "✗ Migration failed, starting app anyway (tables may already exist)..."
    exec gunicorn -w 4 -b 0.0.0.0:$PORT app:app
fi
