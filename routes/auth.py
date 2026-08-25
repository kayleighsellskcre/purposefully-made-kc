from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from urllib.parse import urlparse
import os

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# Counting POSTs only. These routes answer GET and POST from one view, so the
# previous bare limit meant simply loading the sign-in page ten times in a
# minute locked a customer out of a form they had not yet submitted.
from utils.rate_limit import post_only as _rate_limit


def _clean_email(raw):
    """Normalise and check an address, returning (email, error).

    Registration used to store whatever was typed, unchanged. Two problems
    followed. A typo like "casey@gmial" was accepted, and that customer could
    then never receive a receipt or a password reset — they were locked out of
    their own account with no way back. And because the duplicate check was an
    exact match while login looks the address up case-insensitively, the same
    person could register twice as "Casey@..." and "casey@...", after which the
    account they signed into was down to row order.
    """
    email = (raw or '').strip().lower()
    if not email:
        return None, 'Please enter your email address.'
    try:
        from email_validator import EmailNotValidError, validate_email
        try:
            # deliverability off: a DNS lookup on the request path would make
            # signing up as slow as the slowest nameserver.
            validated = validate_email(email, check_deliverability=False)
            return validated.normalized.lower(), None
        except EmailNotValidError:
            return None, 'That email address does not look right. Please check it and try again.'
    except ImportError:
        # email-validator is in requirements.txt, but never let a missing
        # optional import stop someone from creating an account.
        if '@' not in email or '.' not in email.rsplit('@', 1)[-1]:
            return None, 'That email address does not look right. Please check it and try again.'
        return email, None


@auth_bp.route('/emergency-unlock')
def emergency_unlock():
    """Emergency: unlock the admin account lockout and optionally reset password.
    Protected by ADMIN_PROMOTE_TOKEN. Pass ?pw=newpassword to also reset password."""
    token = request.args.get('token')
    expected = os.environ.get('ADMIN_PROMOTE_TOKEN')
    if not expected or token != expected:
        return 'Unauthorized', 403
    admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip().lower()
    user = User.query.filter(db.func.lower(User.email) == admin_email).first()
    if not user:
        return f'No user found with email {admin_email}', 404
    user.failed_logins = 0
    user.locked_until = None
    msg = f'Account {admin_email} unlocked.'
    new_pw = request.args.get('pw', '').strip()
    if new_pw and len(new_pw) >= 8:
        user.set_password(new_pw)
        msg += f' Password reset to provided value.'
    db.session.commit()
    return msg + ' You can now log in.', 200


@auth_bp.route('/promote-admin')
def promote_admin():
    """One-time: promote purposefullymadekc@gmail.com to admin. Requires ADMIN_PROMOTE_TOKEN in env. No other account can be promoted."""
    token = request.args.get('token')
    expected = os.environ.get('ADMIN_PROMOTE_TOKEN')
    if not expected or token != expected:
        flash('Invalid or missing token.', 'error')
        return redirect(url_for('main.index'))
    admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip().lower()
    # Only allow promoting this single admin email; ignore any ?email= from request
    user = User.query.filter(db.func.lower(User.email) == admin_email).first()
    if not user:
        flash(f'No user found with email {admin_email}. Create an account with that email first, then use this link.', 'error')
        return redirect(url_for('main.index'))
    user.is_admin = True
    # Also clear any login lockout so the admin can sign in immediately
    user.failed_logins = 0
    user.locked_until = None
    db.session.commit()
    flash(f'{admin_email} is now an admin and any lockout has been cleared. Log in now.', 'success')
    return redirect(url_for('auth.login'))


def _start_fresh_login_session():
    """New session on login/register so cookies cannot leak across accounts.

    Guest cart lines are preserved so they can be merged into the account cart
    after login_user().
    """
    guest_cart = session.get('cart') if session.get('cart_owner_id') in (None, 'guest') else None
    session.clear()
    session.permanent = True
    if guest_cart:
        session['_pending_guest_cart'] = guest_cart


@auth_bp.route('/login', methods=['GET', 'POST'])
@_rate_limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        # Generic message regardless of whether the user exists (prevents user enumeration)
        _bad = lambda: (flash('Invalid email or password. Please try again.', 'error'),
                        redirect(url_for('auth.login')))[1]

        user = User.query.filter(db.func.lower(User.email) == email).first()

        if user is None:
            return _bad()

        # Account lockout check — admin email is never permanently locked out
        admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip().lower()
        if user.is_locked and email != admin_email:
            flash('Your account is temporarily locked due to too many failed attempts. '
                  'Please wait 15 minutes and try again.', 'error')
            return redirect(url_for('auth.login'))
        # Auto-clear any stale lockout on the admin account so it never gets
        # permanently blocked by automated attempts or AI-assistant retries.
        if email == admin_email and user.is_locked:
            user.failed_logins = 0
            user.locked_until = None

        if not user.check_password(password):
            user.record_failed_login()
            db.session.commit()
            if user.is_locked:
                flash('Too many failed attempts. Your account has been locked for 15 minutes.', 'error')
            else:
                remaining = 5 - (user.failed_logins or 0)
                flash(f'Invalid email or password. {remaining} attempt{"s" if remaining != 1 else ""} remaining before lockout.', 'error')
            return redirect(url_for('auth.login'))

        # Successful login — reset lockout counter
        user.reset_login_attempts()

        # Ensure the designated admin email always has admin access (fixes deploy/fresh DB)
        admin_email = os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com'
        if user.email.lower() == admin_email.lower():
            user.is_admin = True

        db.session.commit()
        _start_fresh_login_session()
        login_user(user, remember=remember)
        from utils.cart_store import adopt_guest_cart_on_login
        adopt_guest_cart_on_login(user, session.pop('_pending_guest_cart', None))

        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('main.index')

        flash(f'Welcome back, {user.first_name or user.email}!', 'success')
        return redirect(next_page)

    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
@_rate_limit("5 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        phone = request.form.get('phone')

        email, email_error = _clean_email(request.form.get('email'))
        if email_error:
            flash(email_error, 'error')
            return redirect(url_for('auth.register'))

        if not password:
            flash('Please choose a password.', 'error')
            return redirect(url_for('auth.register'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('auth.register'))
        
        if len(password) < 8:
            flash('Password must be at least 8 characters long', 'error')
            return redirect(url_for('auth.register'))
        
        # Case-insensitively, to match how login looks an account up.
        if User.query.filter(db.func.lower(User.email) == email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('auth.register'))
        
        # Create new user
        admin_email = os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com'
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            is_admin=(email.lower() == admin_email.lower())
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        _start_fresh_login_session()
        login_user(user)
        from utils.cart_store import adopt_guest_cart_on_login
        adopt_guest_cart_on_login(user, session.pop('_pending_guest_cart', None))
        flash('Account created successfully!', 'success')
        return redirect(url_for('main.index'))
    
    return render_template('auth/register.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@_rate_limit("5 per hour")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()

        # Always show the same success message regardless — prevents user enumeration
        if user:
            token = user.generate_reset_token()
            db.session.commit()
            from utils.background import run_in_background
            run_in_background(current_app._get_current_object(), _send_reset_email, user.id, token)

        flash(
            "If that email is in our system, you'll receive a reset link shortly. "
            "Check your spam folder if it doesn't arrive within a few minutes.",
            'success'
        )
        return redirect(url_for('auth.forgot_password'))

    return render_template('auth/forgot_password.html')


def _send_reset_email(user_or_id, token):
    """Send the password reset email.

    Runs in a background thread, which has an app context but no request. Both
    url_for(_external=True) and render_template need one — without it the link
    could not be built and the render tripped over flask_login's current_user,
    so no reset email was ever delivered.
    """
    try:
        from flask_mail import Message
        from utils.mailer import admin_base_url, reply_to, send

        app = current_app._get_current_object()
        user = user_or_id
        if isinstance(user_or_id, int):
            user = User.query.get(user_or_id)
            if not user:
                return

        with app.test_request_context(base_url=admin_base_url(app)):
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            name = user.first_name or 'there'
            html_body = render_template(
                'email/password_reset.html', name=name, reset_url=reset_url,
            )

        plain_body = (
            f"Hi {name},\n\n"
            f"Someone asked to reset the password for your Purposefully Made KC "
            f"account. Open this link to choose a new one:\n\n"
            f"{reset_url}\n\n"
            f"The link expires in 1 hour and can only be used once.\n\n"
            f"If you did not request this, you can ignore this email — your "
            f"password will not change.\n\n"
            f"— Purposefully Made KC\n"
            f"purposefullymadekc@gmail.com"
        )

        msg = Message(
            subject='Reset your Purposefully Made KC password',
            recipients=[user.email],
            body=plain_body,
            html=html_body,
            reply_to=reply_to(app),
        )
        send(app, msg, description=f'password reset for {user.email}')
    except Exception:
        current_app.logger.exception('Password reset email failed')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    user = User.verify_reset_token(token)
    if user is None:
        flash('This reset link is invalid or has expired. Please request a new one.', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return redirect(url_for('auth.reset_password', token=token))

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('auth.reset_password', token=token))

        user.set_password(password)
        user.clear_reset_token()
        user.reset_login_attempts()   # clear any lockout too
        db.session.commit()

        flash('Your password has been updated. You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    response = redirect(url_for('main.index'))
    remember_name = current_app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    response.delete_cookie(remember_name)
    return response
