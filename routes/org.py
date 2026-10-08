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
from models import db, Organization, OrgSection, Collection

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
    while Organization.query.filter_by(slug=candidate).first():
        candidate = f'{slug}-{i}'
        i += 1
    return candidate


def _org_or_404(slug):
    org = Organization.query.filter_by(slug=slug, is_active=True).first()
    if not org:
        abort(404)
    return org


def _require_org_auth(org):
    """Return True if the organizer is authenticated for this org."""
    return session.get(f'org_auth_{org.id}') is True


# ── public: landing page ──────────────────────────────────────────────────────

@org_bp.route('/org/<slug>')
def landing(slug):
    org = _org_or_404(slug)
    sections = org.sections.order_by(OrgSection.sort_order).all()
    return render_template('org/landing.html', org=org, sections=sections)


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
            org.logo_url = (request.form.get('logo_url') or '').strip() or None
            new_password = (request.form.get('new_password') or '').strip()
            if new_password:
                org.set_password(new_password)
            db.session.commit()
            flash('Settings saved.', 'success')

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
                    db.session.commit()
                    flash(f'"{label}" section added.', 'success')

        elif action == 'delete_section':
            section_id = request.form.get('section_id', type=int)
            section = OrgSection.query.filter_by(
                id=section_id, organization_id=org.id
            ).first()
            if section:
                db.session.delete(section)
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

    sections = org.sections.order_by(OrgSection.sort_order).all()
    available_collections = Collection.query.filter_by(is_active=True).order_by(Collection.name).all()
    return render_template(
        'org/manage.html',
        org=org,
        sections=sections,
        available_collections=available_collections,
    )
