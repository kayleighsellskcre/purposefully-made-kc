from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from urllib.parse import urlparse
import os

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/promote-admin')
def promote_admin():
    """One-time: promote purposefullymadekc@gmail.com to admin. Requires ADMIN_PROMOTE_TOKEN in env. No other account can be promoted."""
    token = request.args.get('token')
    expected = os.environ.get('ADMIN_PROMOTE_TOKEN')
    if not expected or token != expected:
        flash('Invalid or missing token.', 'error')
        return redirect(url_for('main.index'))
    admin_email = os.environ.get('ADMIN_EMAIL', 'purposefullymadekc@gmail.com')
    # Only allow promoting this single admin email; ignore any ?email= from request
    user = User.query.filter_by(email=admin_email).first()
    if not user:
        flash(f'No user found with email {admin_email}. Create an account with that email first, then use this link.', 'error')
        return redirect(url_for('main.index'))
    user.is_admin = True
    db.session.commit()
    flash(f'{admin_email} is now an admin. Log in with that account to access Admin.', 'success')
    return redirect(url_for('auth.login'))


def _clear_cart_for_new_user():
    """Clear cart when user logs in/registers so each account has its own cart."""
    if 'cart' in session:
        session.pop('cart', None)
    if 'cart_owner_id' in session:
        session.pop('cart_owner_id', None)
    session.modified = True


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(email=email).first()
        
        if user is None or not user.check_password(password):
            flash('Invalid email or password', 'error')
            return redirect(url_for('auth.login'))
        
        login_user(user, remember=remember)
        _clear_cart_for_new_user()
        
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('main.index')
        
        flash(f'Welcome back, {user.first_name or user.email}!', 'success')
        return redirect(next_page)
    
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        phone = request.form.get('phone')
        
        # Validation
        if not email or not password:
            flash('Email and password are required', 'error')
            return redirect(url_for('auth.register'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('auth.register'))
        
        if len(password) < 8:
            flash('Password must be at least 8 characters long', 'error')
            return redirect(url_for('auth.register'))
        
        # Check if user exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('auth.register'))
        
        # Create new user
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        _clear_cart_for_new_user()
        flash('Account created successfully!', 'success')
        return redirect(url_for('main.index'))
    
    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.index'))
