"""Organization routes — umbrella landing pages for multi-collection groups.

Public:
  GET  /org/<slug>              → landing page (sport tiles)

Organizer self-service:
  GET  /org/create              → create a new organization
  POST /org/create
  GET  /org/<slug>/manage       → organizer dashboard (password-protected)
  POST /org/<slug>/manage       → save org settings
  POST /org/<slug>/sections/add → add a section tile
  POST /org/<slug>/sections/<id>/delete → remove a section tile
  POST /org/<slug>/sections/reorder    → save sort order after drag
"""

import re
import secrets
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, abort,
)
from pathlib import Path
from flask_login import current_user
from models import db, Organization, OrgSection, Collection
from utils.group_designs import back_ids

org_bp = Blueprint('org', __name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    return text[:80] or 'org'


def _unique_slug(base):
    slug = _slugify(base)
    candidate = slug
    i = 2
    from models import District
    while Organization.query.filter_by(slug=candidate).first() or District.query.filter_by(slug=candidate).first():
        candidate = f'{slug}-{i}'
        i += 1
    return candidate


def _org_or_404(slug):
    org = Organization.query.filter_by(slug=slug, is_active=True).first()
    if not org:
        abort(404)
    return org


def _require_org_auth(org):
    """Return True if the organizer is authenticated for this org (site admins always are)."""
    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
        return True
    return session.get(f'org_auth_{org.id}') is True


_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


def _store_upload(f, subfolder):
    """Upload one FileStorage; return its stored path or None."""
    from flask import current_app
    from werkzeug.utils import secure_filename
    from utils.cloud_storage import upload_image

    if not f or not f.filename:
        return None
    if Path(secure_filename(f.filename)).suffix.lower() not in _IMAGE_EXTS:
        flash('Please choose a PNG, JPG, WEBP or GIF image.', 'error')
        return None
    return upload_image(f, current_app, subfolder=subfolder, public_id_prefix=subfolder,
                        process_artwork=False)


# ── main photos ──────────────────────────────────────────────────────────────
# An org's main photos are its Fan Wear designs plus anything the organizer
# uploads. Uploading adds to the set; nothing disappears unless it is removed.

def _photo_cfg(org):
    import json
    try:
        cfg = json.loads(org.photo_config or '{}')
    except (TypeError, ValueError):
        cfg = {}
    cfg = cfg if isinstance(cfg, dict) else {}
    cfg['uploads'] = [u for u in cfg.get('uploads') or [] if isinstance(u, str) and u]
    cfg['hidden'] = [i for i in cfg.get('hidden') or [] if isinstance(i, int)]
    # Keys of the photos shown big at the top of the org page. None = never
    # chosen yet, so the photos the organizer added themselves are used.
    hero = cfg.get('hero')
    cfg['hero'] = [k for k in hero if isinstance(k, str)] if isinstance(hero, list) else None
    return cfg


def _save_photo_cfg(org, cfg):
    import json
    org.photo_config = json.dumps(cfg, separators=(',', ':'))


def org_photos(org):
    """Every main photo for this org as dicts: key, url, kind, hidden."""
    from models import Design
    from utils.cloud_storage import image_url
    from utils.group_orders import org_fanwear_design_ids

    cfg = _photo_cfg(org)
    items = []
    try:
        lead = next((sec.collection for sec in org.sections
                     if sec.collection and sec.collection.is_active
                     and 'fan' not in (sec.label or '').lower()), None)
        ids = org_fanwear_design_ids(lead) if lead else []
        by_id = {d.id: d for d in Design.query.filter(Design.id.in_(ids)).all()} if ids else {}
        for i in ids:
            if i in by_id:
                items.append({'key': f'fan:{i}', 'kind': 'fan', 'url': image_url(by_id[i].file_path),
                              'hidden': i in cfg['hidden']})
    except Exception:
        pass
    if org.cover_image:   # photo added before multi-photo support
        items.append({'key': 'cover', 'kind': 'upload', 'url': image_url(org.cover_image), 'hidden': False})
    for path in cfg['uploads']:
        items.append({'key': f'up:{path}', 'kind': 'upload', 'url': image_url(path), 'hidden': False})
    for item in items:
        if cfg['hero'] is None:
            item['hero'] = item['kind'] == 'upload'
        else:
            item['hero'] = item['key'] in cfg['hero']
    return items


def fan_art_urls(org, limit=4):
    """URLs of the photos shown on the org's cards (visible ones, up to ``limit``)."""
    return [p['url'] for p in org_photos(org) if not p['hidden']][:limit]


def _fan_banner_urls(org, limit=3):
    """Designs fans can actually pick on the Fan Wear page (what the banner advertises)."""
    from models import Design
    from utils.cloud_storage import image_url
    from utils.group_orders import org_fan_wear_state
    try:
        ids = org_fan_wear_state(org)['shown_design_ids'][:limit]
        by_id = {d.id: d for d in Design.query.filter(Design.id.in_(ids)).all()} if ids else {}
        return [image_url(by_id[i].file_path) for i in ids if i in by_id]
    except Exception:
        return []


def _fan_design_urls(org, limit=4):
    return [p['url'] for p in org_photos(org) if p['kind'] == 'fan' and not p['hidden']][:limit]


def _apply_photo_changes(org):
    """Handle the Main photos part of the edit form."""
    cfg = _photo_cfg(org)
    removed = set()
    for key in request.form.getlist('remove_photo'):
        removed.add(key)
        if key.startswith('fan:') and key[4:].isdigit():
            if int(key[4:]) not in cfg['hidden']:
                cfg['hidden'].append(int(key[4:]))
        elif key == 'cover':
            org.cover_image = None
        elif key.startswith('up:') and key[3:] in cfg['uploads']:
            cfg['uploads'].remove(key[3:])
    for key in request.form.getlist('restore_photo'):
        if key.startswith('fan:') and key[4:].isdigit() and int(key[4:]) in cfg['hidden']:
            cfg['hidden'].remove(int(key[4:]))

    # Which photos appear at the top of the page (the form lists them all).
    if 'hero_present' in request.form:
        cfg['hero'] = [k for k in request.form.getlist('hero_photo') if k not in removed]
    elif cfg['hero'] is not None:
        cfg['hero'] = [k for k in cfg['hero'] if k not in removed]

    for f in request.files.getlist('photos'):
        saved = _store_upload(f, 'org-photos')
        if saved:
            cfg['uploads'].append(saved)
            if cfg['hero'] is not None:      # a photo you just added shows up right away
                cfg['hero'].append(f'up:{saved}')
    _save_photo_cfg(org, cfg)


# ── public: landing page ──────────────────────────────────────────────────────

@org_bp.route('/org/<slug>')
def landing(slug):
    from models import District
    district = District.query.filter_by(slug=slug, is_active=True).first()
    if district is not None:
        from routes.districts import district_page
        return district_page(district)
    org = _org_or_404(slug)
    if org.district_id:                      # a school lives on its district page
        from utils.districts import school_url
        return redirect(school_url(org))
    sections = [s for s in org.sections.order_by(OrgSection.sort_order).all()
                if s.collection and s.collection.is_active]

    # One Fan Wear link for the whole org (same page as every other Fan Wear button).
    from utils.group_orders import org_fan_wear_url
    fan_wear_url = org_fan_wear_url(org)

    # The welcome message lives on the team stores; show it here too unless the
    # organization has its own description.
    lead = next((s.collection for s in sections
                 if s.collection and s.collection.is_active
                 and 'fan' not in (s.label or '').lower()), None)
    from utils.group_orders import is_not_yet_open
    welcome = (org.description or (lead.description if lead else '') or '').strip()
    # Artwork for the page: each team's own logo, and a few fan designs for the banner.
    from utils.group_orders import (
        allowed_design_ids, load_showcase_designs, org_fanwear_design_ids,
    )
    from utils.cloud_storage import image_url as _img_url
    from models import Design
    section_art = {}
    fan_art = []
    try:
        for sec in sections:
            coll = sec.collection
            if not coll or 'fan' in (sec.label or '').lower():
                continue
            shown = load_showcase_designs(coll)
            if shown:
                section_art[sec.id] = shown[0]['url']
            elif coll.cover_image:
                section_art[sec.id] = _img_url(coll.cover_image)
        fan_art = _fan_banner_urls(org, 3)
    except Exception:
        pass
    return render_template('org/landing.html', org=org, sections=sections,
                           section_art=section_art, fan_art=fan_art,
                           hero_photos=[p['url'] for p in org_photos(org) if p['hero'] and not p['hidden']],
                           fan_wear_url=fan_wear_url, welcome=welcome,
                           lead_collection=lead,
                           lead_not_open=bool(lead and is_not_yet_open(lead)))


# ── organizer auth ────────────────────────────────────────────────────────────

@org_bp.route('/org/<slug>/login', methods=['GET', 'POST'])
def org_login(slug):
    org = _org_or_404(slug)
    if request.method == 'POST':
        password = request.form.get('password', '')
        if org.check_password(password):
            session[f'org_auth_{org.id}'] = True
            return redirect(url_for('org.manage', slug=slug))
        flash('Incorrect password. Try again.', 'error')
    return render_template('org/login.html', org=org)


@org_bp.route('/org/<slug>/logout')
def org_logout(slug):
    org = _org_or_404(slug)
    session.pop(f'org_auth_{org.id}', None)
    return redirect(url_for('org.landing', slug=slug))


# ── organizer: create ─────────────────────────────────────────────────────────

@org_bp.route('/org/create', methods=['GET', 'POST'])
def create():
    # Collect all existing collections for the section-linking dropdown
    collections = Collection.query.filter_by(is_active=True).order_by(Collection.name).all()

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        description = (request.form.get('description') or '').strip()
        password = (request.form.get('password') or '').strip()
        logo_url = (request.form.get('logo_url') or '').strip()
        email = (request.form.get('organizer_email') or '').strip()

        if not name:
            flash('Organization name is required.', 'error')
            return render_template('org/create.html', collections=collections)

        slug = _unique_slug(name)
        org = Organization(
            name=name,
            slug=slug,
            description=description or None,
            logo_url=logo_url or None,
            pending_organizer_email=email or None,
        )
        if password:
            org.set_password(password)

        db.session.add(org)
        db.session.commit()

        # Auto-authenticate the creator for the manage dashboard
        session[f'org_auth_{org.id}'] = True
        flash(f'"{name}" created! Add your first section below.', 'success')
        return redirect(url_for('org.manage', slug=slug))

    return render_template('org/create.html', collections=collections)


# ── organizer: manage dashboard ───────────────────────────────────────────────

@org_bp.route('/org/<slug>/manage', methods=['GET', 'POST'])
def manage(slug):
    org = _org_or_404(slug)

    # Redirect to login if password is set and not authenticated
    if org.password_hash and not _require_org_auth(org):
        return redirect(url_for('org.org_login', slug=slug))

    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'save_settings':
            org.name = (request.form.get('name') or org.name).strip()
            org.description = (request.form.get('description') or '').strip() or None
            # Main photos: uploads are added; remove only what is ticked.
            _apply_photo_changes(org)
            # Logo: upload to switch it, tick remove to delete.
            if request.form.get('remove_logo') == 'on':
                org.logo_url = None
            logo = _store_upload(request.files.get('logo'), 'org-logos')
            if logo:
                org.logo_url = logo
            new_password = (request.form.get('new_password') or '').strip()
            if new_password:
                org.set_password(new_password)
            db.session.commit()
            flash('Saved.', 'success')

        elif action == 'delete_org':
            if not (current_user.is_authenticated and getattr(current_user, 'is_admin', False)):
                flash('Only a site admin can delete an organization.', 'error')
            else:
                name = org.name
                # Older databases carry an unused collection.organization_id column.
                from sqlalchemy import inspect, text
                if 'organization_id' in [c['name'] for c in inspect(db.engine).get_columns('collection')]:
                    db.session.execute(text('UPDATE collection SET organization_id = NULL '
                                            'WHERE organization_id = :id'), {'id': org.id})
                from utils.org_fan_store import retire_org_fan_store
                retire_org_fan_store(org)
                OrgSection.query.filter_by(organization_id=org.id).delete(synchronize_session=False)
                db.session.delete(org)
                db.session.commit()
                flash(f'"{name}" deleted. Its stores and orders are all still there.', 'success')
                return redirect(url_for('admin.collections'))

        elif action == 'rename_section':
            section = OrgSection.query.filter_by(
                id=request.form.get('section_id', type=int), organization_id=org.id
            ).first()
            label = (request.form.get('label') or '').strip()
            if section and label:
                section.label = label[:100]
                icon = (request.form.get('icon') or '').strip()
                if icon:
                    section.icon = icon[:10]
                db.session.commit()
                flash('Team updated.', 'success')

        elif action == 'add_section':
            label = (request.form.get('label') or '').strip()
            icon = (request.form.get('icon') or '🏷️').strip()
            collection_id = request.form.get('collection_id', type=int)
            if not label or not collection_id:
                flash('Label and group order are required.', 'error')
            else:
                collection = Collection.query.get(collection_id)
                if not collection:
                    flash('Group order not found.', 'error')
                else:
                    max_order = db.session.query(
                        db.func.max(OrgSection.sort_order)
                    ).filter_by(organization_id=org.id).scalar() or 0
                    section = OrgSection(
                        organization_id=org.id,
                        collection_id=collection_id,
                        label=label,
                        icon=icon or '🏷️',
                        sort_order=max_order + 1,
                    )
                    # Tag the collection so we know which org it belongs to
                    collection.organization_id = org.id
                    db.session.add(section)
                    db.session.flush()
                    from utils.org_fan_store import sync_org_fan_store
                    sync_org_fan_store(org)
                    db.session.commit()
                    flash(f'"{label}" section added.', 'success')

        elif action == 'delete_section':
            section_id = request.form.get('section_id', type=int)
            section = OrgSection.query.filter_by(
                id=section_id, organization_id=org.id
            ).first()
            if section:
                db.session.delete(section)
                db.session.flush()
                from utils.org_fan_store import sync_org_fan_store
                sync_org_fan_store(org)
                db.session.commit()
                flash('Section removed.', 'success')

        elif action == 'reorder':
            order = request.form.getlist('section_order[]', type=int)
            for idx, section_id in enumerate(order):
                section = OrgSection.query.filter_by(
                    id=section_id, organization_id=org.id
                ).first()
                if section:
                    section.sort_order = idx
            db.session.commit()

        return redirect(url_for('org.manage', slug=slug))

    from utils.org_fan_store import fan_store_for, is_auto_fan_store
    from models import Order
    sections = org.sections.order_by(OrgSection.sort_order).all()
    fan_store = fan_store_for(org)
    if fan_store is not None and is_auto_fan_store(fan_store):
        sections = [sec for sec in sections if sec.collection_id != fan_store.id]   # shown on the Fan Wear card
    else:
        fan_store = None
    from utils.group_orders import order_counts_by_collection
    order_counts = order_counts_by_collection()
    in_org = {sec.collection_id for sec in OrgSection.query.all()}
    available_collections = [
        c for c in Collection.query.filter_by(is_active=True).order_by(Collection.name).all()
        if c.id not in in_org
    ]
    is_admin = current_user.is_authenticated and getattr(current_user, 'is_admin', False)
    return render_template(
        'org/manage.html',
        org=org,
        sections=sections,
        available_collections=available_collections,
        photos=org_photos(org),
        fan_summary=_fan_summary(org),
        fan_store=fan_store,
        order_counts=order_counts,
        is_admin=is_admin,
    )


# ── Fan Wear: one setup for the whole group ──────────────────────────────────

def _int_list(values):
    out = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _fan_summary(org):
    """Small summary for the Fan Wear card on the edit page."""
    from models import Design
    from utils.cloud_storage import image_url
    from utils.group_orders import collection_has_color_restrictions, org_fan_wear_state
    state = org_fan_wear_state(org)
    lead = state['lead']
    shown = state['shown_design_ids']
    by_id = {d.id: d for d in Design.query.filter(Design.id.in_(shown[:4])).all()} if shown else {}
    return {
        'styles': len(state['fan_product_ids']),
        'colors_limited': bool(lead and collection_has_color_restrictions(lead)),
        'designs_shown': len(shown),
        'designs_total': len(state['design_ids']),
        'thumbs': [image_url(by_id[i].file_path) for i in shown[:4] if i in by_id],
        'has_teams': bool(lead),
    }


@org_bp.route('/org/<slug>/fan-wear', methods=['GET', 'POST'])
def fan_wear(slug):
    """Shirt styles, colors and designs for Fan Wear, set once for every team."""
    import json
    from models import Design
    from utils.group_orders import (
        allowed_design_ids, apply_org_fan_wear, collection_has_color_restrictions,
        fan_color_checked_keys, org_fan_wear_state, serialize_allowed_colors_from_form,
        _KEEP,
    )
    from utils.product_filters import load_group_order_form_catalog

    org = _org_or_404(slug)
    if org.password_hash and not _require_org_auth(org):
        return redirect(url_for('org.org_login', slug=slug))
    state = org_fan_wear_state(org)
    lead = state['lead']
    if not lead:
        flash('Add a team first, then you can set up Fan Wear.', 'error')
        return redirect(url_for('org.manage', slug=slug))

    if request.method == 'POST':
        listed = _int_list(request.form.getlist('design_ids'))
        shown = set(_int_list(request.form.getlist('fan_designs')))

        new_ids = []
        if current_user.is_authenticated:
            from routes.admin import _save_collection_design
            for f in request.files.getlist('new_designs'):
                if f and f.filename:
                    try:
                        design = _save_collection_design(f, current_user.id)
                    except Exception:
                        design = None
                    if design:
                        new_ids.append(design.id)
        if new_ids:
            ids = allowed_design_ids(lead)
            lead.allowed_design_ids = json.dumps(ids + [i for i in new_ids if i not in ids])
            listed += new_ids
            shown |= set(new_ids)

        if listed and not shown:
            db.session.rollback()
            flash('Pick at least one design for fans to choose from.', 'error')
            return redirect(url_for('org.fan_wear', slug=slug))

        colors = (serialize_allowed_colors_from_form(request.form.getlist('allowed_colors'))
                  if 'color_picker_present' in request.form else _KEEP)
        apply_org_fan_wear(
            org,
            _int_list(request.form.getlist('products')),
            allowed_colors=colors,
            excluded_design_ids=[i for i in listed if i not in shown],
        )
        db.session.commit()
        flash('Fan Wear saved for every team.', 'success')
        return redirect(url_for('org.manage', slug=slug))

    catalog = load_group_order_form_catalog()
    designs = []
    if state['design_ids']:
        by_id = {d.id: d for d in Design.query.filter(Design.id.in_(state['design_ids'])).all()}
        designs = [by_id[i] for i in state['design_ids'] if i in by_id]
    return render_template(
        'org/fan_wear.html',
        org=org,
        products=catalog['products'],
        catalog_filter_opts=catalog['catalog_filter_opts'],
        catalog_filter_picker=True,
        fan_color_picker=catalog['fan_color_picker'],
        fan_color_checked=fan_color_checked_keys(lead, catalog['products'], catalog['uniform_colors_by_product']),
        checked_product_ids=set(state['fan_product_ids']),
        team_store={'uniform': {'product_ids': state['jersey_product_ids']}},
        designs=designs,
        shown_design_ids=set(state['shown_design_ids']),
        can_upload=current_user.is_authenticated,
        teams=[sec for sec in org.sections.order_by(OrgSection.sort_order).all()
               if sec.collection and 'fan' not in (sec.label or '').lower()
               and sec.collection_id in {c.id for c in state['team_collections']}],
    )


@org_bp.route('/org/<slug>/fan-wear/designs/<int:design_id>/delete', methods=['POST'])
def fan_wear_delete_design(slug, design_id):
    """Delete one design from every team in the group.

    Refuses while a team's jersey logo or back print uses it. A design that is
    part of the public Design Gallery is only taken out of this group; its
    gallery record is kept.
    """
    import json
    from models import Design
    from utils.group_orders import allowed_design_ids, org_fan_wear_state, showcase_design_ids, team_store_config

    org = _org_or_404(slug)
    if org.password_hash and not _require_org_auth(org):
        return redirect(url_for('org.org_login', slug=slug))
    back = redirect(url_for('org.fan_wear', slug=slug))

    state = org_fan_wear_state(org)
    if design_id not in state['design_ids']:
        flash('That design is not part of this group.', 'error')
        return back

    labels = {sec.collection_id: sec.label for sec in org.sections}
    for coll in state['team_collections']:
        uniform = team_store_config(coll)['uniform']
        if design_id in (uniform.get('home_design_id'), uniform.get('away_design_id')):
            flash(f'This design is the jersey logo for {labels.get(coll.id, "a team")}. '
                  'Change that team\'s jersey logo first, then delete it.', 'error')
            return back
        if design_id in back_ids(coll):
            flash(f'This design is the back print for {labels.get(coll.id, "a team")}. '
                  'Change it there first, then delete it.', 'error')
            return back

    for coll in state['team_collections']:
        ids = [i for i in allowed_design_ids(coll) if i != design_id]
        coll.allowed_design_ids = json.dumps(ids) if ids else None
        show = [i for i in showcase_design_ids(coll) if i != design_id]
        coll.showcase_design_ids = json.dumps(show) if show else None
        try:
            cfg = json.loads(coll.team_store_config or '{}')
        except (TypeError, ValueError):
            cfg = {}
        if isinstance(cfg, dict) and design_id in (cfg.get('fanwear_excluded_ids') or []):
            cfg['fanwear_excluded_ids'] = [i for i in cfg['fanwear_excluded_ids'] if i != design_id]
            coll.team_store_config = json.dumps(cfg, separators=(',', ':'))

    photos = _photo_cfg(org)
    photos['hidden'] = [i for i in photos['hidden'] if i != design_id]
    if photos['hero'] is not None:
        photos['hero'] = [k for k in photos['hero'] if k != f'fan:{design_id}']
    _save_photo_cfg(org, photos)
    from utils.org_fan_store import sync_org_fan_store
    sync_org_fan_store(org)

    design = Design.query.get(design_id)
    deleted = False
    if design and not design.is_gallery:
        try:
            from routes.admin import _delete_design_file
            _delete_design_file(design)
        except Exception:
            pass
        db.session.delete(design)
        deleted = True
    db.session.commit()
    flash('Design deleted.' if deleted else
          'Design taken out of this group. It stays in the Design Gallery.', 'success')
    return back
