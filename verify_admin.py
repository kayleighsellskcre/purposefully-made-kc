"""
Verify admin user exists and can login
"""
from app import create_app
from models import db, User

app = create_app()
with app.app_context():
    # Check if admin exists
    admin = User.query.filter_by(email='kayleighsellskcre@gmail.com').first()
    
    if admin:
        print("Admin user EXISTS")
        print(f"  Email: {admin.email}")
        print(f"  Is Admin: {admin.is_admin}")
        print(f"  Has password hash: {bool(admin.password_hash)}")
        
        # Test password
        if admin.check_password('admin123'):
            print("\n  PASSWORD WORKS!")
        else:
            print("\n  PASSWORD DOES NOT WORK! Resetting...")
            admin.set_password('admin123')
            db.session.commit()
            print("  Password has been reset to: admin123")
    else:
        print("Admin user DOES NOT EXIST! Creating...")
        admin = User(
            email='kayleighsellskcre@gmail.com',
            first_name='Admin',
            last_name='User',
            is_admin=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Admin user created!")
    
    print("\n" + "="*60)
    print("LOGIN CREDENTIALS:")
    print("="*60)
    print("Email: kayleighsellskcre@gmail.com")
    print("Password: admin123")
    print("="*60)
    print("\nGo to: http://localhost:5000/login")
