"""
Set your email as the admin account
"""
from app import create_app
from models import db, User

app = create_app()

with app.app_context():
    your_email = 'kayleighsellskcre@gmail.com'
    
    # Check if account exists
    existing = User.query.filter_by(email=your_email).first()
    
    if existing:
        # Make this account admin
        existing.is_admin = True
        existing.first_name = 'Kayleigh'
        existing.last_name = 'Sells'
        print(f'[+] Made {your_email} an admin')
        print(f'[+] Use your existing password to login')
    else:
        # Create new admin account
        new_admin = User(
            email=your_email,
            first_name='Kayleigh',
            last_name='Sells',
            is_admin=True
        )
        new_admin.set_password('admin123')
        db.session.add(new_admin)
        print(f'[+] Created admin account: {your_email}')
        print(f'[+] Password: admin123')
    
    # Also keep the old admin for testing if needed
    old_admin = User.query.filter_by(email='admin@kbapparel.com').first()
    if old_admin:
        print(f'[+] Old admin (admin@kbapparel.com) still available')
    
    db.session.commit()
    
    print('\n==== ADMIN SETUP COMPLETE ====')
    print(f'Login with: {your_email}')
    print('Password: admin123')
    print('\nPlease change your password after first login!')
    print('Go to: Account -> Profile -> Change Password')
