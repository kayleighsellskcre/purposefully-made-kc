"""
Set purposefullymadekc@gmail.com as the only admin. All other accounts keep customer portals only.
Run once after deploy or if the admin account lost access: python set_purposefullymadekc_admin.py
"""
import os
from app import create_app
from models import db, User

ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'purposefullymadekc@gmail.com')

def main():
    app = create_app()
    with app.app_context():
        # Ensure the designated admin has access
        admin_user = User.query.filter_by(email=ADMIN_EMAIL).first()
        if admin_user:
            admin_user.is_admin = True
            print(f"[OK] Admin access set for: {ADMIN_EMAIL}")
        else:
            print(f"[SKIP] No user with email {ADMIN_EMAIL}. Create an account with that email first, then run this again or use /auth/promote-admin?token=YOUR_ADMIN_PROMOTE_TOKEN")

        # Remove admin from everyone else (only purposefullymadekc can be admin)
        others = User.query.filter(User.email != ADMIN_EMAIL).all()
        for u in others:
            if getattr(u, 'is_admin', False):
                u.is_admin = False
                print(f"[REMOVED] Admin removed from: {u.email}")

        db.session.commit()
        print("\nDone. Only", ADMIN_EMAIL, "can access the Admin dashboard.")

if __name__ == '__main__':
    main()
