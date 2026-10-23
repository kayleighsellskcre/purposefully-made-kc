from flask import Blueprint, Response, render_template, session, current_app, send_file, send_from_directory, request, flash, redirect, url_for
from models import Product, Collection
from utils.rate_limit import post_only
from utils.admin_gate import require_admin_or_404
from datetime import datetime
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
        from utils.mockups import product_has_shop_image
        featured_products = [
            p for p in Product.query.filter_by(is_active=True).order_by(Product.style_number).all()
            if product_has_shop_image(p)
        ][:8]
        from utils.group_orders import public_group_directory
        # Same list as the Group Orders page (one card per organization), minus
        # password-protected stores, which need the password to shop.
        orgs, stores = public_group_directory(skip_password_protected=True)
        cards = [{'kind': 'org', **o} for o in orgs] + [{'kind': 'store', **c} for c in stores]
        from utils.site_content import REVIEWS as SITE_REVIEWS
        SITE_REVIEWS = _approved_reviews() + list(SITE_REVIEWS)
        return render_template('index.html',
                             featured_products=featured_products,
                             group_cards=cards[:3],
                             group_cards_total=len(cards),
                             reviews=SITE_REVIEWS)
    except Exception as e:
        # Log the error but don't crash
        import sys
        print(f"Error in index route: {e}", file=sys.stderr)
        # Return a simple homepage without products if there's an error
        return render_template('index.html',
                             featured_products=[],
                             group_cards=[],
                             group_cards_total=0)

def _approved_reviews(limit=6):
    """Approved customer reviews for the homepage. A photo only appears when the customer allowed it."""
    try:
        from models import Review
        rows = Review.query.filter_by(status='approved').order_by(Review.created_at.desc()).limit(limit).all()
    except Exception:
        return []
    out = []
    for r in rows:
        text = (r.body or '').strip()
        photos = r.photo_urls() if r.photos_ok else []
        if not text and not photos:
            continue
        out.append({'name': r.name, 'occasion': (r.order.occasion_note if r.order and r.order.occasion_note else ''),
                    'text': text, 'photo': photos[0] if photos else ''})
    return out


def _owner():
    """The owner's name, note and photo URL. Saved in Site settings; the files in utils/site_content.py are the fallback."""
    from utils import site_content
    from utils.cloud_storage import image_url
    from utils.site_settings import get_setting
    photo = (get_setting('owner_photo_url', '') or '').strip()
    if not photo and os.path.exists(os.path.join(current_app.static_folder, *site_content.OWNER_PHOTO.split('/'))):
        photo = '/static/' + site_content.OWNER_PHOTO
    return {
        'name': (get_setting('owner_name', '') or '').strip() or site_content.OWNER_NAME,
        'note': (get_setting('owner_note', '') or '').strip() or site_content.OWNER_NOTE,
        'photo': image_url(photo) if photo else None,
    }


@main_bp.route('/about')
def about():
    """About page"""
    return render_template('about.html', owner=_owner())

@main_bp.route('/contact', methods=['GET', 'POST'])
# Public, unauthenticated, and it sends an email on every POST. Without a limit
# it is a relay into the owner's inbox and burns the mail provider's quota.
# Generous enough that a customer who mistypes their address and resubmits a
# few times is unaffected.
@post_only("5 per hour")
def contact():
    """Contact page"""
    if request.method == 'POST':
        # Honeypot: real visitors never see or fill this field. A bot that
        # fills every input trips it, and we pretend to succeed so it doesn't
        # learn to look for a different tell.
        if request.form.get('website', '').strip():
            flash('Thank you for reaching out! We will get back to you within 1 to 2 business days.', 'success')
            return redirect(url_for('main.contact'))

        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        order_number = ''.join(ch for ch in request.form.get('order_number', '') if ch.isalnum() or ch in '-_ ')[:40].strip()
        if order_number and subject == 'Order question':
            message = f'Order number: {order_number}\n\n{message}'

        if len(name) > 100 or len(email) > 254 or len(subject) > 150 or len(message) > 3000:
            flash('One of those fields is longer than we can take. Please shorten it and try again.', 'error')
            return redirect(url_for('main.contact'))

        if name or email or message:
            try:
                from utils.admin_notifications import notify_contact_message
                notify_contact_message(name, email, subject, message)
            except Exception as e:
                try:
                    from models import db as _db
                    _db.session.rollback()
                except Exception:
                    pass
                current_app.logger.exception('Contact inbox error: %s', e)

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

    digits = ''.join(c for c in str(current_app.config.get('ADMIN_PHONE', '')) if c.isdigit())
    contact_phone_display = f'({digits[0:3]}) {digits[3:6]}-{digits[6:10]}' if len(digits) == 10 else None
    return render_template('contact.html', contact_phone_display=contact_phone_display,
                           contact_phone_digits=digits, owner=_owner())


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
        '',
        f'Sitemap: {url_for("main.sitemap_xml", _external=True)}',
        '',
    ]
    return Response('\n'.join(lines), mimetype='text/plain')


def _template_lastmod(template_name):
    """The template file's own modified date, as a sitemap lastmod value.

    These are static informational pages with no database row to carry an
    updated_at, so the template file on disk is the closest honest signal
    for "when did this page last change."
    """
    try:
        _source, filename, _uptodate = current_app.jinja_loader.get_source(
            current_app.jinja_env, template_name,
        )
        if filename:
            return datetime.fromtimestamp(os.path.getmtime(filename)).date().isoformat()
    except Exception:
        pass
    return None


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

    add('main.index', 'weekly', '1.0', lastmod=_template_lastmod('index.html'))
    add('shop.index', 'daily', '0.9', lastmod=_template_lastmod('shop/index.html'))
    add('shop.design_gallery', 'weekly', '0.8', lastmod=_template_lastmod('shop/design_gallery.html'))
    add('shop.group_orders', 'weekly', '0.7', lastmod=_template_lastmod('shop/group_orders.html'))
    add('custom_request.index', 'monthly', '0.7', lastmod=_template_lastmod('custom_request/index.html'))
    add('main.about', 'yearly', '0.5', lastmod=_template_lastmod('about.html'))
    add('main.contact', 'yearly', '0.5', lastmod=_template_lastmod('contact.html'))
    add('main.privacy', 'yearly', '0.3', lastmod=_template_lastmod('privacy.html'))
    add('main.terms', 'yearly', '0.3', lastmod=_template_lastmod('terms.html'))
    add('main.faq', 'monthly', '0.6', lastmod=_template_lastmod('faq.html'))
    add('main.size_guide', 'monthly', '0.6', lastmod=_template_lastmod('size_guide.html'))

    try:
        from utils.mockups import product_has_shop_image
        products = Product.query.filter_by(is_active=True).all()
        for product in products:
            if not product_has_shop_image(product):
                continue
            lastmod = product.updated_at or product.created_at
            if not product.slug:
                continue
            add(
                'shop.product_detail', 'weekly', '0.8',
                lastmod=lastmod.date().isoformat() if lastmod else None,
                product_slug=product.slug,
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
            lastmod = collection.updated_at or collection.created_at
            add(
                'collection.view', 'weekly', '0.6',
                lastmod=lastmod.date().isoformat() if lastmod else None,
                slug=collection.slug,
            )
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
    # Fixed to the day this text was last published, not the current date.
    return render_template('privacy.html', privacy_last_updated='September 21, 2026')

@main_bp.route('/faq')
def faq():
    """Questions people ask before they order."""
    return render_template('faq.html')


@main_bp.route('/size-guide')
def size_guide():
    """Chest and length by brand, measured flat, in inches."""
    from utils.size_guide import GENERAL_NOTE, brand_charts
    return render_template('size_guide.html', charts=brand_charts(), general_note=GENERAL_NOTE)


@main_bp.route('/terms')
def terms():
    """Terms of Service page"""
    return render_template('terms.html')

@main_bp.route('/status')
@require_admin_or_404
def status():
    """Admin-only diagnostics: what's configured (no secrets, keys or emails shown)."""
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
        admin_user_exists=admin_user is not None,
        admin_user_is_admin=admin_user.is_admin if admin_user else False,
        ss_key_set=bool(ss_key and ss_key.strip() and 'your_' not in ss_key.lower() and 'paste' not in ss_key.lower()),
        ss_account_set=bool(ss_account and ss_account.strip() and 'your_' not in ss_account.lower() and 'paste' not in ss_account.lower()),
        db_using_postgres='postgresql' in db_url or 'postgres' in db_url,
        db_ok=db_ok,
        product_count=product_count,
    )


# ---- Reviews: a private link per order, words and photos, shown only once approved ----

_REVIEW_PHOTO_LIMIT = 3
_REVIEW_PHOTO_MAX_BYTES = 8 * 1024 * 1024
_REVIEW_PHOTO_TYPES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif'}


def _review_order(token):
    from models import Order
    token = (token or '').strip()
    if len(token) < 16:
        return None
    return Order.query.filter_by(review_token=token).first()


def _suggest_review_name(order):
    first = (order.first_name or '').strip()
    last = (order.last_name or '').strip()
    return f'{first} {last[:1]}.'.strip() if last else first


def _save_review_photos(files):
    """Store up to three photos. Returns (urls, message): message is set when something was skipped."""
    from utils.cloud_storage import store_upload
    urls, skipped = [], False
    for f in files[:_REVIEW_PHOTO_LIMIT]:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename.lower())[1]
        f.stream.seek(0, os.SEEK_END)
        size = f.stream.tell()
        f.stream.seek(0)
        if ext not in _REVIEW_PHOTO_TYPES or size > _REVIEW_PHOTO_MAX_BYTES or size == 0:
            skipped = True
            continue
        urls.append(store_upload(f, 'reviews', 'review'))
    msg = 'One of your photos could not be added (photos must be images under 8 MB).' if skipped else ''
    return urls, msg


@main_bp.route('/review/<token>', methods=['GET', 'POST'])
def review(token):
    """The page a customer reaches from the review email. No account needed."""
    import json
    from models import Review, db
    order = _review_order(token)
    if order is None:
        return render_template('review/thanks.html', state='unknown'), 404
    if Review.query.filter_by(order_id=order.id).first():
        return render_template('review/thanks.html', state='already')
    errors = {}
    form = {'name': _suggest_review_name(order), 'body': '', 'photos_ok': False}
    if request.method == 'POST':
        form['name'] = (request.form.get('name') or '').strip()[:80]
        form['body'] = (request.form.get('body') or '').strip()[:2000]
        form['photos_ok'] = bool(request.form.get('photos_ok'))
        files = [f for f in request.files.getlist('photos') if f and f.filename]
        if not form['name']:
            errors['name'] = 'Please tell us what name to show.'
        if not form['body'] and not files:
            errors['body'] = 'Share a few words or add a photo and we will be so happy.'
        if not errors:
            urls, note = _save_review_photos(files)
            if not form['body'] and not urls:
                errors['body'] = note or 'We could not add that photo. Please try another or write a few words.'
            else:
                row = Review(order_id=order.id, name=form['name'], body=form['body'] or None,
                             photos=json.dumps(urls) if urls else None,
                             photos_ok=bool(urls) and form['photos_ok'], status='pending')
                db.session.add(row)
                db.session.commit()
                _alert_owner_of_review(row, order)
                return redirect(url_for('main.review_thanks', token=token))
    return render_template('review/form.html', order=order, form=form, errors=errors,
                           photo_limit=_REVIEW_PHOTO_LIMIT)


@main_bp.route('/review/<token>/thanks')
def review_thanks(token):
    order = _review_order(token)
    return render_template('review/thanks.html', state='thanks' if order else 'unknown')


def _alert_owner_of_review(row, order):
    """Tell the owner a review is waiting for approval. Best effort, never blocks the customer."""
    try:
        from utils.mailer import admin_recipient
        from utils.sponsor_emails import _send
        to = admin_recipient(current_app)
        if not to:
            return
        _send(to, 'A new review is waiting for you', 'A new review is waiting',
              [f'{row.name} shared a review for order {order.order_number}.',
               'It will not show on the website until you approve it.'],
              details=[('Review', (row.body or 'Photos only')[:200])],
              button={'label': 'Open reviews', 'url': url_for('admin.reviews', _external=True)})
    except Exception:
        current_app.logger.exception('review alert email failed')
