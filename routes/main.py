from flask import Blueprint, Response, render_template, session, current_app, send_file, send_from_directory, request, flash, redirect, url_for
from models import Product, Collection
from datetime import datetime, timezone
import os

main_bp = Blueprint('main', __name__)


@main_bp.route('/uploads/mockups/<path:path>')
def serve_mockup(path):
    """Serve mockup images from uploads/mockups (static/uploads/mockups or project uploads/mockups)."""
    path = path.strip('/').replace('..', '').replace('\\', '/')
    if not path:
        return '', 404
    # Check both locations: static/uploads/mockups and project uploads/mockups
    bases = [
        os.path.join(current_app.root_path, 'static', 'uploads', 'mockups'),
        os.path.join(current_app.root_path, 'uploads', 'mockups'),
    ]
    for base in bases:
        base = os.path.normpath(base)
        if not os.path.isdir(base):
            continue
        full_path = os.path.normpath(os.path.join(base, path.replace('/', os.sep)))
        if os.path.isfile(full_path) and full_path.startswith(base):
            directory = os.path.dirname(full_path)
            filename = os.path.basename(full_path)
            return send_from_directory(directory, filename)
    return '', 404


@main_bp.route('/')
def index():
    """Homepage"""
    try:
        featured_products = Product.query.filter_by(is_active=True).order_by(Product.style_number).limit(8).all()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Only admin-created, non-password stores. Customer group orders stay
        # off the homepage and are reached only via the organizer's share link.
        active_collections = Collection.query.filter(
            Collection.is_active == True,
            Collection.is_password_protected == False,
            Collection.created_by_user_id.is_(None),
            (Collection.order_deadline == None) | (Collection.order_deadline >= now),
            (Collection.order_opens_at == None) | (Collection.order_opens_at <= now),
        ).order_by(Collection.created_at.desc()).limit(6).all()
        return render_template('index.html', 
                             featured_products=featured_products,
                             active_collections=active_collections)
    except Exception as e:
        # Log the error but don't crash
        import sys
        print(f"Error in index route: {e}", file=sys.stderr)
        # Return a simple homepage without products if there's an error
        return render_template('index.html', 
                             featured_products=[],
                             active_collections=[])

@main_bp.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    """Contact page"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()

        # Send email to admin if mail is configured — after the thank-you redirect.
        try:
            from flask_mail import Message as MailMessage
            mail = current_app.extensions.get('mail')
            admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip()
            if mail and current_app.config.get('MAIL_SERVER') and current_app.config.get('MAIL_USERNAME'):
                subject_line = f"[PMKC Contact] {subject or 'New message'} — from {name}"
                body = (
                    f"New contact form submission from purposefullymadekc.com\n\n"
                    f"Name:    {name}\n"
                    f"Email:   {email}\n"
                    f"Subject: {subject}\n\n"
                    f"Message:\n{message}\n\n"
                    f"---\nReply directly to this email to respond to {name}."
                )
                msg = MailMessage(
                    subject=subject_line,
                    recipients=[admin_email],
                    reply_to=email or admin_email,
                    body=body,
                )
                from utils.background import run_in_background
                from utils.mailer import send as _send_mail
                run_in_background(
                    current_app._get_current_object(), _send_mail,
                    current_app._get_current_object(), msg,
                    description=f'contact form message from {email}',
                )
        except Exception as e:
            import sys
            print(f"Contact email error: {e}", file=sys.stderr)

        flash('Thank you for reaching out! We will get back to you within 1 to 2 business days.', 'success')
        return redirect(url_for('main.contact'))
    return render_template('contact.html')


@main_bp.route('/robots.txt')
def robots_txt():
    """Tell crawlers what to index. Keeps carts, accounts, and admin out of search."""
    lines = [
        'User-agent: *',
        'Allow: /',
        # Nothing behind these is public or useful in search results, and
        # crawling them wastes budget on pages that require a session.
        'Disallow: /admin/',
        'Disallow: /account/',
        'Disallow: /cart/',
        'Disallow: /checkout/',
        'Disallow: /auth/',
        'Disallow: /design/',
        'Disallow: /custom-design/submit',
        'Disallow: /custom-design/my-requests',
        'Disallow: /status',
        'Disallow: /version',
        '',
        f'Sitemap: {url_for("main.sitemap_xml", _external=True)}',
        '',
    ]
    return Response('\n'.join(lines), mimetype='text/plain')


@main_bp.route('/sitemap.xml')
def sitemap_xml():
    """Generated sitemap of the public pages and every active product."""
    from xml.sax.saxutils import escape

    entries = []

    def add(endpoint, changefreq, priority, lastmod=None, **values):
        try:
            loc = url_for(endpoint, _external=True, **values)
        except Exception:
            return
        entries.append({
            'loc': loc,
            'changefreq': changefreq,
            'priority': priority,
            'lastmod': lastmod,
        })

    add('main.index', 'weekly', '1.0')
    add('shop.index', 'daily', '0.9')
    add('shop.design_gallery', 'weekly', '0.8')
    add('shop.group_orders', 'weekly', '0.7')
    add('custom_request.index', 'monthly', '0.7')
    add('main.about', 'yearly', '0.5')
    add('main.contact', 'yearly', '0.5')
    add('main.privacy', 'yearly', '0.3')
    add('main.terms', 'yearly', '0.3')

    try:
        products = Product.query.filter_by(is_active=True).all()
        for product in products:
            lastmod = product.updated_at or product.created_at
            add(
                'shop.product_detail', 'weekly', '0.8',
                lastmod=lastmod.date().isoformat() if lastmod else None,
                product_id=product.id,
            )
    except Exception:
        current_app.logger.exception('sitemap product listing failed')

    try:
        # Only collections the owner has deliberately published to the
        # public directory, and never a password-protected one.
        collections = Collection.query.filter(
            Collection.is_active == True,
            Collection.show_in_directory == True,
            Collection.is_password_protected == False,
        ).all()
        for collection in collections:
            add('collection.view', 'weekly', '0.6', slug=collection.slug)
    except Exception:
        current_app.logger.exception('sitemap collection listing failed')

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for entry in entries:
        parts.append('  <url>')
        parts.append(f'    <loc>{escape(entry["loc"])}</loc>')
        if entry['lastmod']:
            parts.append(f'    <lastmod>{entry["lastmod"]}</lastmod>')
        parts.append(f'    <changefreq>{entry["changefreq"]}</changefreq>')
        parts.append(f'    <priority>{entry["priority"]}</priority>')
        parts.append('  </url>')
    parts.append('</urlset>')

    return Response('\n'.join(parts), mimetype='application/xml')


@main_bp.route('/privacy')
def privacy():
    """Privacy Policy page"""
    return render_template('privacy.html')

@main_bp.route('/terms')
def terms():
    """Terms of Service page"""
    return render_template('terms.html')

@main_bp.route('/status')
def status():
    """Diagnostics: what's configured (no secrets shown). Visit /status to see why things might not connect."""
    from models import db, User, Product
    import os

    admin_email = (os.environ.get('ADMIN_EMAIL') or 'purposefullymadekc@gmail.com').strip()
    ss_key = os.environ.get('SSACTIVEWEAR_API_KEY') or ''
    ss_account = os.environ.get('SSACTIVEWEAR_ACCOUNT_NUMBER') or ''
    db_url = os.environ.get('DATABASE_URL') or ''

    db_ok = False
    try:
        Product.query.first()
        db_ok = True
    except Exception:
        pass

    admin_user = User.query.filter(db.func.lower(User.email) == admin_email.lower()).first() if admin_email else None
    product_count = Product.query.count()

    return render_template('status.html',
        admin_email_set=bool(admin_email),
        admin_email_value=admin_email,
        admin_user_exists=admin_user is not None,
        admin_user_is_admin=admin_user.is_admin if admin_user else False,
        ss_key_set=bool(ss_key and ss_key.strip() and 'your_' not in ss_key.lower() and 'paste' not in ss_key.lower()),
        ss_account_set=bool(ss_account and ss_account.strip() and 'your_' not in ss_account.lower() and 'paste' not in ss_account.lower()),
        db_using_postgres='postgresql' in db_url or 'postgres' in db_url,
        db_ok=db_ok,
        product_count=product_count,
    )
