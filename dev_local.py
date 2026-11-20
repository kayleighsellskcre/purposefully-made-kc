"""Run the dev server against the local SQLite file instead of production
Postgres, with the scheduler off. Keeps local testing from touching
production data or firing background sync jobs. Not used in deployment.
"""
import os

os.environ.setdefault('DATABASE_URL', 'sqlite:///' + os.path.abspath('dev_fresh.db'))
os.environ.setdefault('SCHEDULER_ENABLED', 'false')
os.environ.setdefault('SESSION_COOKIE_SECURE', 'false')
# app.py enforces is_admin only on the account matching ADMIN_EMAIL at every
# startup (revoking it from everyone else), so local testing needs its own
# admin email to match whatever account dev seeding creates.
os.environ.setdefault('ADMIN_EMAIL', 'admin-local@example.com')

from app import app

def _seed_admin():
    """A fresh local database always gets one admin to sign in with (local only; never used in deployment)."""
    from models import User, db
    with app.app_context():
        db.create_all()
        email = os.environ['ADMIN_EMAIL']
        if not User.query.filter_by(email=email).first():
            u = User(email=email, first_name='Local', last_name='Admin', is_admin=True)
            u.set_password('local-admin-pass')
            db.session.add(u)
            db.session.commit()

if __name__ == '__main__':
    _seed_admin()
    app.run(debug=False, port=5000)
