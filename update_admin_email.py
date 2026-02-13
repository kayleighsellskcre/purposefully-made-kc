"""
Switch admin account to purposefullymadekc@gmail.com
"""
from app import create_app
from models import db, User

app = create_app()

with app.app_context():
    old_admin = User.query.filter_by(email='kayleighsellskcre@gmail.com').first()
    new_admin_user = User.query.filter_by(email='purposefullymadekc@gmail.com').first()
    
    if new_admin_user:
        # purposefullymadekc already exists - make them admin, remove from old
        new_admin_user.is_admin = True
        if old_admin:
            old_admin.is_admin = False
        db.session.commit()
        print('[+] purposefullymadekc@gmail.com is now the admin')
        print('[+] Removed admin from kayleighsellskcre@gmail.com')
    elif old_admin:
        # Update old admin email to new one
        old_admin.email = 'purposefullymadekc@gmail.com'
        old_admin.is_admin = True
        db.session.commit()
        print('[+] Admin email updated to: purposefullymadekc@gmail.com')
        print('[+] Password unchanged - use your existing password to log in')
    else:
        # Create new admin
        new_admin = User(
            email='purposefullymadekc@gmail.com',
            first_name='Admin',
            last_name='User',
            is_admin=True
        )
        new_admin.set_password('admin123')
        db.session.add(new_admin)
        db.session.commit()
        print('[+] Created new admin account')
        print('Email: purposefullymadekc@gmail.com')
        print('Password: admin123 (change after logging in!)')
