"""School district pages and short links.

  /org/<district>                     district page: find your school
  /org/<district>/<school>            school page: School Spirit first, then each sport
  /<district>[/<school>[/<store>]]    permanent short links (redirect to the pages above)
  .../qr.png and .../flyer.pdf        the QR code and the one-page flyer for any of them
"""
from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_login import current_user

from models import District, Organization
from utils import districts as DS

district_bp = Blueprint('district', __name__)


def _is_admin():
    return current_user.is_authenticated and getattr(current_user, 'is_admin', False)


def _store_art(store):
    """(image url or None, emoji) for a store card."""
    from utils.cloud_storage import image_url
    from utils.group_orders import load_showcase_designs
    from models import OrgSection
    try:
        shown = load_showcase_designs(store)
    except Exception:
        shown = []
    if shown:
        return shown[0]['url'], None
    if store.cover_image:
        return image_url(store.cover_image), None
    sec = OrgSection.query.filter_by(collection_id=store.id).first()
    return None, (sec.icon if sec and sec.icon else '🏷️')


def _school_countdown(school):
    """The soonest "Closes in N days" among a school's live stores."""
    from utils.group_orders import closing_countdown
    best = None
    for store in DS.live_stores(school):
        text = closing_countdown(store)
        if text and (best is None or store.order_deadline < best[0]):
            best = (store.order_deadline, text)
    return best[1] if best else ''


def _logo(obj):
    from utils.cloud_storage import image_url
    return image_url(obj.logo_url) if obj.logo_url else None


@district_bp.route('/school-districts')
def directory():
    """Every listed district, so families can find their school without a link."""
    items = []
    for d in District.query.filter_by(is_active=True, listed=True).order_by(District.name).all():
        count = sum(1 for level in DS.schools_by_level(d, public=True) for _ in level[2])
        items.append({'district': d, 'schools': count, 'logo': _logo(d), 'url': DS.district_url(d)})
    return render_template('district/index.html', districts=items)


def _district_or_404(slug):
    d = District.query.filter_by(slug=slug, is_active=True).first()
    if d is None:
        abort(404)
    return d


def district_page(d):
    """Page 1: every school in the district, grouped by level."""
    g.nav_here = 'schools'                      # the menu keeps Schools lit on a district page
    admin = _is_admin()
    levels = DS.schools_by_level(d, public=not admin)
    cards = {}
    for _key, _heading, schools in levels:
        for school in schools:
            stores = DS.stores_of(school) if admin else DS.live_stores(school)
            cards[school.id] = {'deadline': DS.school_deadline(school, DS.live_stores(school) or stores),
                                'logo': _logo(school) or next((x['url'] for x in DS.school_logos(school)), None), 'live': bool(DS.live_stores(school)),
                                'url': DS.school_url(school),
                                'countdown': _school_countdown(school)}
    return render_template('district/district.html', district=d, levels=levels, cards=cards, logo=_logo(d),
                           share=DS.share_info(d), accent=DS.accent, accent2=DS.accent2)


@district_bp.route('/org/<district_slug>/<school_slug>')
def school_page(district_slug, school_slug):
    d = _district_or_404(district_slug)
    school = Organization.query.filter_by(district_id=d.id, school_slug=school_slug, is_active=True).first_or_404()
    admin = _is_admin()
    stores = DS.stores_of(school) if admin else DS.live_stores(school)
    spirit = next((s for s in stores if s.store_kind == 'spirit'), None)
    sections = DS.store_sections([s for s in stores if s.store_kind != 'spirit'])

    def card(store):
        image, emoji = _store_art(store)
        return {'store': store, 'label': DS.store_label(store), 'image': image, 'emoji': emoji,
                'live': DS.is_live(store), 'share': DS.share_info(store, school)}
    logo = _logo(school) or next((x['url'] for x in DS.school_logos(school)), None)     # a main logo stands in
    return render_template('district/school.html', district=d, school=school, logo=logo,
                           spirit=card(spirit) if spirit else None,
                           sections=[(kind, heading, [card(s) for s in group]) for kind, heading, group in sections],
                           deadline=DS.school_deadline(school),
                           share=DS.share_info(school), level_heading=DS.level_heading(school), accent=DS.accent(school), accent2=DS.accent2(school),
                           tagline=DS.SPIRIT_TAGLINE)


# ── short links ───────────────────────────────────────────────────────────────────────────

def _go(obj, school=None):
    """Send a short link to its real page."""
    if isinstance(obj, District):
        return redirect(DS.district_url(obj))
    if isinstance(obj, Organization):
        return redirect(DS.school_url(obj))
    if not obj.is_active:
        abort(404)
    return redirect(url_for('collection.view', slug=obj.slug))


def _resolve(*parts):
    obj = DS.resolve_short(*parts)
    if obj is None:
        abort(404)
    return obj


@district_bp.route('/<d_short>')
def short_district(d_short):
    return _go(_resolve(d_short))


@district_bp.route('/<d_short>/<s_short>')
def short_school(d_short, s_short):
    return _go(_resolve(d_short, s_short))


@district_bp.route('/<d_short>/<s_short>/<store_short>')
def short_store(d_short, s_short, store_short):
    school = _resolve(d_short, s_short)
    return _go(_resolve(d_short, s_short, store_short), school)


def _qr_response(obj, school=None):
    link = DS.short_url(obj, school)
    headers = {'Cache-Control': 'public, max-age=3600'}
    if request.args.get('download'):
        name = DS._file_safe(getattr(obj, 'name', 'qr'))
        headers['Content-Disposition'] = f'attachment; filename="{name} QR.png"'
    return Response(DS.qr_png(link), mimetype='image/png', headers=headers)


def _flyer_response(obj, school=None):
    name = DS._file_safe(getattr(obj, 'name', 'flyer'))
    disposition = 'attachment' if request.args.get('download') else 'inline'
    return Response(DS.flyer_pdf(obj, school, request.args.get('style')), mimetype='application/pdf',
                    headers={'Content-Disposition': f'{disposition}; filename="{name} flyer.pdf"'})


def _flyer_image_response(obj, school=None):
    name = DS._file_safe(getattr(obj, 'name', 'flyer'))
    disposition = 'attachment' if request.args.get('download') else 'inline'
    return Response(DS.flyer_png(obj, school, request.args.get('style')), mimetype='image/png',
                    headers={'Content-Disposition': f'{disposition}; filename="{name} flyer.png"',
                             'Cache-Control': 'private, no-store, no-cache, max-age=0, must-revalidate',
                             'CDN-Cache-Control': 'no-store', 'Pragma': 'no-cache'})


@district_bp.route('/<d_short>/qr.png')
def district_qr(d_short):
    return _qr_response(_resolve(d_short))


@district_bp.route('/<d_short>/flyer.pdf')
def district_flyer(d_short):
    return _flyer_response(_resolve(d_short))


@district_bp.route('/<d_short>/flyer.png')
def district_flyer_image(d_short):
    return _flyer_image_response(_resolve(d_short))


@district_bp.route('/<d_short>/<s_short>/qr.png')
def school_qr(d_short, s_short):
    return _qr_response(_resolve(d_short, s_short))


@district_bp.route('/<d_short>/<s_short>/flyer.pdf')
def school_flyer(d_short, s_short):
    return _flyer_response(_resolve(d_short, s_short))


@district_bp.route('/<d_short>/<s_short>/flyer.png')
def school_flyer_image(d_short, s_short):
    return _flyer_image_response(_resolve(d_short, s_short))


@district_bp.route('/<d_short>/<s_short>/<store_short>/qr.png')
def store_qr(d_short, s_short, store_short):
    school = _resolve(d_short, s_short)
    return _qr_response(_resolve(d_short, s_short, store_short), school)


@district_bp.route('/<d_short>/<s_short>/<store_short>/flyer.pdf')
def store_flyer(d_short, s_short, store_short):
    school = _resolve(d_short, s_short)
    return _flyer_response(_resolve(d_short, s_short, store_short), school)


@district_bp.route('/<d_short>/<s_short>/<store_short>/flyer.png')
def store_flyer_image(d_short, s_short, store_short):
    school = _resolve(d_short, s_short)
    return _flyer_image_response(_resolve(d_short, s_short, store_short), school)
