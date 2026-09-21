"""Run the dev server against the local SQLite file instead of production
Postgres, with the scheduler off. Keeps local testing from touching
production data or firing background sync jobs. Not used in deployment.
"""
import os

os.environ.setdefault('DATABASE_URL', 'sqlite:///' + os.path.abspath('apparel.db'))
os.environ.setdefault('SCHEDULER_ENABLED', 'false')
os.environ.setdefault('SESSION_COOKIE_SECURE', 'false')
# app.py enforces is_admin only on the account matching ADMIN_EMAIL at every
# startup (revoking it from everyone else), so local testing needs its own
# admin email to match whatever account dev seeding creates.
os.environ.setdefault('ADMIN_EMAIL', 'admin-local@example.com')

from app import app

if __name__ == '__main__':
    app.run(debug=False, port=5000)
