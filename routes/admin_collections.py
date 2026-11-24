"""Admin Collections: group stores, their products, designs, sections and settings.

Split out of routes/admin.py. Everything here is still on the admin blueprint, so every URL and every
url_for('admin.something') name is exactly as before (see the import at the bottom of routes/admin.py).
"""
import json

from flask import render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user
from models import db, Collection, Design
from utils import sales_tax

from routes.admin import _save_collection_design, admin_bp, admin_required  # noqa: E402
from routes.admin_design_requests import _delete_design_file  # noqa: E402


# ===== COLLECTIONS =====

@admin_bp.route('/collections')
@admin_required
def collections():
    """Manage collections — grouped under their org when applicable."""
    from utils.group_orders import is_deadline_passed
    from models import Organization, OrgSection
    from routes.org import fan_art_urls
    pass

    all_collections = Collection.query.order_by(Collection.created_at.desc()).all()
    # School district stores are managed from Districts, not mixed in here.
    district_store_ids = {sec.collection_id for sec in OrgSection.query.join(Organization).filter(
        Organization.district_id.isnot(None)).all()}
    all_collections = [c for c in all_collections if c.id not in district_store_ids]
    for c in all_collections:
        c.list_active = bool(c.is_active) and not is_deadline_passed(c)

    # Pre-compute order counts in ONE query instead of one .count() per card.
    from utils.group_orders import order_counts_by_collection
    order_counts = order_counts_by_collection()
    for c in all_collections:
        c.cached_order_count = order_counts.get(c.id, 0)

    # Pre-load ALL org sections in one query — avoids N+1 from org.sections.all()
    all_sections = OrgSection.query.order_by(OrgSection.sort_order).all()
    sections_by_org = {}
    for sec in all_sections:
        sections_by_org.setdefault(sec.organization_id, []).append(sec)

    orgs = Organization.query.filter(Organization.district_id.is_(None)).order_by(Organization.created_at.desc()).all()
    coll_by_id = {c.id: c for c in all_collections}
    org_collection_ids = set()
    for org in orgs:
        sections = sections_by_org.get(org.id, [])
        org.grouped_collections = [
            {'section': sec, 'collection': coll_by_id[sec.collection_id]}
            for sec in sections
            if sec.collection_id in coll_by_id
        ]
        org_collection_ids.update(sec.collection_id for sec in sections)
        org.total_orders = sum(c['collection'].cached_order_count for c in org.grouped_collections)
        org.team_store_count = sum(1 for c in org.grouped_collections if 'fan' not in (c['section'].label or '').lower())
        org.fan_art = fan_art_urls(org)

    standalone = [c for c in all_collections if c.id not in org_collection_ids]
    return render_template(
        'admin/collections.html',
        collections=all_collections,
        orgs=orgs,
        standalone_collections=standalone,
    )


@admin_bp.route('/collections/add', methods=['GET', 'POST'])
@admin_required
def add_collection():
    """Add new collection"""
    if request.method == 'POST':
        from slugify import slugify
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Please enter a name for the group order.', 'error')
            return redirect(url_for('admin.add_collection'))

        try:
            slug = (request.form.get('slug') or slugify(name)).strip() or slugify(name)
            base_slug = slug
            n = 1
            while Collection.query.filter_by(slug=slug).first():
                slug = f"{base_slug}-{n}"
                n += 1
            if slug != base_slug:
                flash(f'URL slug adjusted to "{slug}" (original was already in use).', 'info')

            collection = Collection(
                name=name,
                slug=slug,
                description=request.form.get('description'),
                is_active=request.form.get('is_active') == 'on',
                pickup_address=request.form.get('pickup_address'),
                pickup_instructions=request.form.get('pickup_instructions'),
                shipping_enabled=request.form.get('shipping_enabled') == 'on',
                allow_cash_pickup=request.form.get('allow_cash_pickup') == 'on',
                tax_rate=sales_tax.rate_percent(),
                # Without this, a store made here never showed up under My
                # Group Orders for the admin who made it - only the
                # customer-facing create flow was setting it.
                created_by_user_id=current_user.id,
            )
            from utils.group_orders import apply_collection_visibility, apply_organizer_from_form
            apply_collection_visibility(collection)
            ok, organizer_error, organizer_notice = apply_organizer_from_form(collection)
            if not ok:
                flash(organizer_error, 'error')
                organizer_notice = None

            collection.restrict_options = request.form.get('restrict_options') == 'on'
            collection.allow_custom_upload = True
            from utils.group_orders import serialize_allowed_colors_from_form
            allowed_colors_json = serialize_allowed_colors_from_form(request.form.getlist('allowed_colors'))
            collection.allowed_colors = allowed_colors_json
            allowed_placements = request.form.getlist('allowed_placements')
            collection.allowed_placements = json.dumps(allowed_placements) if allowed_placements else None

            from utils.privacy import selectable_group_order_design_ids
            allowed_design_ids = selectable_group_order_design_ids(
                request.form.getlist('allowed_designs'), current_user
            )
            pending_uploads = [
                f for f in request.files.getlist('design_uploads') if f and f.filename
            ]
            if allowed_design_ids:
                collection.allowed_design_ids = json.dumps(allowed_design_ids)
            if allowed_design_ids or allowed_colors_json:
                collection.restrict_options = True

            from utils.group_orders import apply_back_fonts
            apply_back_fonts(collection, request.form)
            # Uniform back-design style controls
            collection.back_design_text_color = request.form.get('back_design_text_color') or None
            collection.back_design_outline = request.form.get('back_design_outline') != 'off'
            collection.back_design_outline_color = request.form.get('back_design_outline_color') or None
            collection.lock_back_design_style = request.form.get('lock_back_design_style') == 'on'
            back_type = request.form.get('back_design_type', 'both')
            collection.allow_back_design = back_type != 'none'
            collection.back_design_type = (
                back_type
                if back_type in ('name_number', 'image', 'both')
                else 'both'
            )
            if collection.allow_back_design and collection.back_design_type in (
                'name_number', 'both'
            ):
                name_part = (request.form.get('back_design_name_part') or 'last').strip().lower()
                collection.back_design_name_part = (
                    name_part if name_part in ('first', 'last') else 'last'
                )
            # Stacked names are chosen separately for jerseys and for Fan Wear. A jersey team store takes the
            # jersey choice; Fan Wear has its own store (set below) or, with no organization, shares this store.
            _jersey_stacked = _fan_stacked = None
            if 'stacked_name_present' in request.form:
                _jersey_stacked = request.form.get('allow_stacked_name') == 'on'
                _fan_stacked = request.form.get('fan_allow_stacked_name') == 'on'
                has_org = request.form.get('org_action', '') in ('new', 'existing')
                collection.allow_stacked_name = _jersey_stacked if has_org else _fan_stacked
            from utils.group_orders import apply_locked_back_design
            apply_locked_back_design(collection, current_user)

            from utils.group_orders import apply_collection_card, apply_schedule_from_form, apply_group_kind, set_collection_products_from_form
            apply_collection_card(collection)
            ok, kind_error = apply_group_kind(collection, required=True)
            if not ok:
                flash(kind_error, 'error')
                return redirect(url_for('admin.add_collection'))
            from utils.group_roster import apply_payment_mode_from_form
            ok, payment_error = apply_payment_mode_from_form(collection)
            if not ok:
                flash(payment_error, 'error')
                return redirect(url_for('admin.add_collection'))

            password = request.form.get('password')
            if password:
                collection.set_password(password)
            ok, schedule_error = apply_schedule_from_form(collection)
            if not ok:
                flash(schedule_error, 'error')
                return redirect(url_for('admin.add_collection'))

            db.session.add(collection)
            db.session.flush()

            selected_products, product_error = set_collection_products_from_form(collection)
            if product_error:
                db.session.rollback()
                flash(product_error, 'error')
                return redirect(url_for('admin.add_collection'))
            if not selected_products:
                db.session.rollback()
                flash('Please choose a uniform or at least one shirt style for fan wear.', 'error')
                return redirect(url_for('admin.add_collection'))
            from utils.group_roster import roster_item_error
            roster_error = roster_item_error(collection)
            if roster_error:
                db.session.rollback()
                flash(roster_error, 'error')
                return redirect(url_for('admin.add_collection'))

            # Artwork uploaded with the form (no-JavaScript fallback) joins the
            # store before any team copies are made, so every team gets it.
            upload_count = 0
            new_upload_ids = []
            for f in pending_uploads:
                try:
                    design = _save_collection_design(f, current_user.id)
                except Exception as e:
                    current_app.logger.exception('Collection design upload failed: %s', e)
                    design = None
                if design:
                    allowed_design_ids.append(design.id)
                    new_upload_ids.append(design.id)
                    upload_count += 1
            if upload_count:
                collection.allowed_design_ids = json.dumps(allowed_design_ids)
                collection.restrict_options = True

            from utils.group_orders import resolve_showcase_design_ids
            from utils.group_designs import link_uploaded_colors
            new_upload_ids = link_uploaded_colors(new_upload_ids, request.form)
            showcase_ids = resolve_showcase_design_ids(
                allowed_design_ids,
                form_showcase=request.form.getlist('showcase_designs'),
                new_upload_ids=new_upload_ids,
                showcase_new_uploads=request.form.get('showcase_new_uploads') == 'on',
            )
            collection.showcase_design_ids = json.dumps(showcase_ids) if showcase_ids else None
            from utils.group_designs import save_design_labels
            save_design_labels(collection, request.form, current_user)

            # ── Multi-team organization (optional) ──────────────────────────
            # Built in the same transaction as the store: either everything
            # saves (org page, every team store, jerseys, logos) or nothing does.
            from utils.group_org import OrgSetupError, add_store_to_org, create_org_from_wizard
            org_action = request.form.get('org_action', '')
            org_flash = None
            if org_action == 'existing':
                org = add_store_to_org(collection, request.form)
                if org:
                    org_flash = f'Added to the {org.name} organization page.'
            elif org_action == 'new':
                try:
                    org, stores = create_org_from_wizard(collection, request.form, current_user)
                except OrgSetupError as e:
                    db.session.rollback()
                    flash(str(e), 'error')
                    return redirect(url_for('admin.add_collection'))
                if len(stores) > 1:
                    org_flash = (
                        f'Created {len(stores)} team stores for {org.name}. '
                        f'Share the organization page: purposefullymadekc.com/org/{org.slug}'
                    )
                else:
                    org_flash = (
                        f'Organization page created. Share '
                        f'purposefullymadekc.com/org/{org.slug} with your organizer.'
                    )

            if _jersey_stacked is not None:
                if org_action == 'new' and org:
                    from utils.org_fan_store import fan_store_for
                    fan_store = fan_store_for(org)
                    if fan_store is not None:
                        fan_store.allow_stacked_name = _fan_stacked
                elif org_action not in ('new', 'existing') and _jersey_stacked != _fan_stacked:
                    from utils.group_orders import team_store_config
                    if team_store_config(collection)['uniform']['enabled']:
                        cfg = json.loads(collection.team_store_config)
                        cfg['jersey_allow_stacked_name'] = _jersey_stacked
                        collection.team_store_config = json.dumps(cfg, separators=(',', ':'))

            db.session.commit()

            msg = 'Group order created successfully'
            if upload_count:
                msg += f' with {upload_count} design(s) uploaded'
            flash(msg + '.', 'success')
            if org_flash:
                flash(org_flash, 'success')
            if organizer_notice:
                flash(organizer_notice, 'success')
            return redirect(url_for('admin.collections'))

        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.warning('Admin add_collection IntegrityError: %s', e)
            flash('A group order with that name or URL already exists. Try a different name.', 'error')
            return redirect(url_for('admin.add_collection'))
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('Admin add_collection database error: %s', e)
            flash('Could not save the group order due to a server issue. Please try again.', 'error')
            return redirect(url_for('admin.add_collection'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Admin add_collection unexpected error: %s', e)
            flash('Something went wrong while creating the group order. Please try again.', 'error')
            return redirect(url_for('admin.add_collection'))
    
    from utils.product_filters import load_group_order_form_catalog
    from utils.fonts import GROUP_ORDER_FONTS
    from utils.group_order_templates import TEMPLATE_KEYS, group_order_templates
    from utils.group_defaults import default_fan_color_keys
    from models import Organization
    catalog = load_group_order_form_catalog()
    selected_template = request.args.get('type')
    existing_orgs = Organization.query.order_by(Organization.name).all()
    return render_template(
        'admin/add_collection.html',
        group_templates=group_order_templates(catalog['products']),
        selected_group_template=selected_template if selected_template in TEMPLATE_KEYS else '',
        products=catalog['products'],
        gallery_designs=catalog['gallery_designs'],
        fan_color_picker=catalog['fan_color_picker'],
        fan_color_checked=default_fan_color_keys(catalog['fan_color_picker'], catalog['products']),
        uniform_colors_by_product=catalog['uniform_colors_by_product'],
        team_store={'configured': True, 'uniform': {'enabled': False}, 'fan_product_ids': []},
        back_design_fonts=GROUP_ORDER_FONTS,
        catalog_filter_opts=catalog['catalog_filter_opts'],
        catalog_filter_picker=True,
        existing_orgs=existing_orgs,
    )


@admin_bp.route('/collections/<int:collection_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_collection(collection_id):
    """Edit collection"""
    from utils.product_filters import load_group_order_form_catalog
    from utils.group_orders import (
        apply_collection_form,
        designs_for_group_order_form,
        team_store_config,
    )
    import json

    collection = Collection.query.get_or_404(collection_id)
    
    if request.method == 'POST':
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        try:
            ok, error, upload_count = apply_collection_form(
                collection, current_user, allow_slug=True, require_products=True
            )
            if not ok:
                db.session.rollback()
                flash(error, 'error')
                return redirect(url_for('admin.edit_collection', collection_id=collection.id))

            db.session.commit()
            msg = 'Group order updated successfully'
            if upload_count:
                msg += f' with {upload_count} new design(s) uploaded'
            flash(msg + '.', 'success')
            return redirect(url_for('admin.edit_collection', collection_id=collection.id))

        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.warning('Admin edit_collection IntegrityError: %s', e)
            flash('A group order with that URL slug already exists. Choose a different slug.', 'error')
            return redirect(url_for('admin.edit_collection', collection_id=collection.id))
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('Admin edit_collection database error: %s', e)
            flash('Could not save the group order due to a server issue. Please try again.', 'error')
            return redirect(url_for('admin.edit_collection', collection_id=collection.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Admin edit_collection unexpected error: %s', e)
            flash('Something went wrong while saving the group order. Please try again.', 'error')
            return redirect(url_for('admin.edit_collection', collection_id=collection.id))
    
    catalog = load_group_order_form_catalog()
    products = catalog['products']
    gallery_designs = designs_for_group_order_form(collection)
    from utils.group_orders import fan_color_checked_keys
    fan_color_checked = fan_color_checked_keys(
        collection, collection.products, catalog['uniform_colors_by_product']
    )
    allowed_design_ids_list = json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    showcase_design_ids_list = json.loads(collection.showcase_design_ids) if getattr(collection, 'showcase_design_ids', None) else []
    allowed_placements_list = json.loads(collection.allowed_placements) if collection.allowed_placements else ['center_chest', 'left_chest', 'right_chest', 'center_back']
    from utils.group_orders import fanwear_excluded_ids, org_sync_info
    from utils.group_designs import section_names, sections_map
    fanwear_excluded_ids_list = fanwear_excluded_ids(collection)
    from utils.fonts import GROUP_ORDER_FONTS
    return render_template('admin/edit_collection.html',
                         collection=collection,
                         products=products,
                         gallery_designs=gallery_designs,
                         fan_color_picker=catalog['fan_color_picker'],
                         fan_color_checked=fan_color_checked,
                         uniform_colors_by_product=catalog['uniform_colors_by_product'],
                         team_store=team_store_config(collection),
                         allowed_design_ids_list=allowed_design_ids_list,
                         showcase_design_ids_list=showcase_design_ids_list,
                         design_sections_map=sections_map(collection),
                         design_section_list=section_names(collection),
                         allowed_placements_list=allowed_placements_list,
                         fanwear_excluded_ids_list=fanwear_excluded_ids_list,
                         sync_org=org_sync_info(collection),
                         back_design_fonts=GROUP_ORDER_FONTS,
                         collection_product_ids=[p.id for p in collection.products],
                         catalog_filter_opts=catalog['catalog_filter_opts'],
                         catalog_filter_picker=True)


@admin_bp.route('/collections/bulk-delete', methods=['POST'])
@admin_required
def collections_bulk_delete():
    """Delete several group orders (and whole organizations) at once. Anything with orders is turned off and kept."""
    from models import Organization
    from utils.group_delete import remove_organization, remove_stores, summary
    store_ids = [int(i) for i in request.form.getlist('store_id') if i.isdigit()]
    org_ids = [int(i) for i in request.form.getlist('org_id') if i.isdigit()]
    deleted, kept = remove_stores(Collection.query.filter(Collection.id.in_(store_ids)).all()) if store_ids else ([], [])
    orgs = Organization.query.filter(Organization.id.in_(org_ids), Organization.district_id.is_(None)).all() if org_ids else []
    for org in orgs:
        _result, d, k = remove_organization(org)
        deleted += d
        kept += k
    flash(summary(deleted, kept, 'group order') + (f' ({len(orgs)} organization{"s" if len(orgs) != 1 else ""} handled.)' if orgs else ''),
          'success' if deleted or kept else 'info')
    return redirect(url_for('admin.collections'))


@admin_bp.route('/collections/<int:collection_id>/delete', methods=['POST'])
@admin_required
def delete_collection(collection_id):
    """Delete a collection, cleaning up ALL FK references first via raw SQL."""
    from models import Order, OrgSection, GroupRosterEntry
    from sqlalchemy import text
    collection = Collection.query.get_or_404(collection_id)
    team_section = OrgSection.query.filter_by(collection_id=collection_id).first()
    team_org = team_section.organization if team_section else None
    try:
        # Step 1: nullify FK references that allow NULL
        db.session.query(Order).filter(Order.collection_id == collection_id).update(
            {Order.collection_id: None}, synchronize_session=False
        )
        # Step 2: hard-delete rows where FK is NOT NULL (cannot nullify)
        db.session.query(OrgSection).filter(OrgSection.collection_id == collection_id).delete(
            synchronize_session=False
        )
        db.session.query(GroupRosterEntry).filter(
            GroupRosterEntry.collection_id == collection_id
        ).delete(synchronize_session=False)
        # Step 3: clear the collection_products secondary/association table via
        # raw SQL — the ORM's automatic secondary-table cleanup can fail after
        # synchronize_session=False bulk operations leave the identity map stale.
        db.session.execute(
            text('DELETE FROM collection_products WHERE collection_id = :cid'),
            {'cid': collection_id}
        )
        # Step 4: flush all FK cleanup to the DB BEFORE touching the parent row
        db.session.flush()
        # Step 5: now safe to delete the collection row itself
        db.session.delete(collection)
        db.session.commit()
        if team_org is not None:      # the org's Fan Wear store follows its remaining teams
            from utils.org_fan_store import sync_org_fan_store
            sync_org_fan_store(team_org)
            db.session.commit()
        flash('Group order deleted', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(
            'delete_collection %s FAILED — %s: %s',
            collection_id, type(e).__name__, e
        )
        flash('Could not delete the group order. Please try again.', 'error')
    return redirect(url_for('admin.collections'))


@admin_bp.route('/collections/<int:collection_id>/designs/attach', methods=['POST'])
@admin_required
def collection_designs_attach(collection_id):
    """Offer artwork from another group in this one."""
    from utils.group_designs import attach
    collection = Collection.query.get_or_404(collection_id)
    n = attach(collection, request.form.getlist('design_ids'), show_at_top=bool(request.form.get('show_at_top')))
    db.session.commit()
    flash(f'Added {n} design{"s" if n != 1 else ""} to this group order.' if n else 'Tick the designs you want to add.', 'success' if n else 'error')
    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


@admin_bp.route('/collections/<int:collection_id>/designs/<int:design_id>/detach', methods=['POST'])
@admin_required
def collection_design_detach(collection_id, design_id):
    """Take a design off this group order only. The artwork and every other group are untouched."""
    from utils.group_designs import JERSEY_LOGO_MESSAGE, detach, jersey_logo_ids
    collection = Collection.query.get_or_404(collection_id)
    if design_id in jersey_logo_ids(collection):
        flash(JERSEY_LOGO_MESSAGE, 'error')
        return redirect(url_for('admin.edit_collection', collection_id=collection_id))
    detach(collection, design_id)
    db.session.commit()
    flash('Taken off this group order. It is still on file and in any other group that uses it.', 'success')
    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


@admin_bp.route('/collections/<int:collection_id>/designs/<int:design_id>/copy-to', methods=['POST'])
@admin_required
def collection_design_copy_to(collection_id, design_id):
    """Also offer this design in another group."""
    from utils.group_designs import attach
    Collection.query.get_or_404(collection_id)
    target = Collection.query.get(request.form.get('target_id', type=int) or 0)
    if target is None:
        flash('Choose a group first.', 'error')
    else:
        attach(target, [design_id])
        db.session.commit()
        flash(f'Now also offered in {target.name}.', 'success')
    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


@admin_bp.route('/collections/<int:collection_id>/designs/link-colors', methods=['POST'])
@admin_required
def collection_designs_link(collection_id):
    """Make the ticked designs color options of one main design (the gallery's color families)."""
    import json as _json
    collection = Collection.query.get_or_404(collection_id)
    allowed = _json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    picked = []
    for raw in request.form.getlist('design_ids'):
        try:
            did = int(raw)
        except (TypeError, ValueError):
            continue
        if did in allowed and did not in picked:
            picked.append(did)
    picked.sort(key=allowed.index)                       # the one listed first becomes the main design
    designs = [Design.query.get(i) for i in picked]
    designs = [d for d in designs if d is not None]
    back = redirect(url_for('admin.edit_collection', collection_id=collection_id))
    if len(designs) < 2:
        flash('Tick two or more designs that are the same layout in different colors.', 'error')
        return back
    main = designs[0]
    if main.parent_design_id:
        flash('Pick a main design that is not already a color of another design.', 'error')
        return back
    from utils.group_designs import link_as_colors
    linked = link_as_colors(designs)
    if linked:                                          # a "Show at top" tick on any of them now belongs to the main design
        shown = _json.loads(collection.showcase_design_ids) if collection.showcase_design_ids else []
        children = {d.id for d in designs[1:] if d.parent_design_id == main.id}
        if children & set(shown) and main.id not in shown:
            shown.append(main.id)
        shown = [i for i in shown if i not in children]
        collection.showcase_design_ids = _json.dumps(shown) if shown else None
    try:
        db.session.commit()
        flash(f'Linked {linked} color{"s" if linked != 1 else ""} to "{main.title or "the main design"}". Shoppers now see one design with a color choice.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('collection_designs_link failed: %s', e)
        flash('Could not link those designs. Please try again.', 'error')
    return back


@admin_bp.route('/collections/<int:collection_id>/back-designs/link', methods=['POST'])
@admin_required
def collection_back_designs_link(collection_id):
    """Make the ticked back images color versions of one main back image."""
    from utils.group_designs import back_ids, link_as_colors
    collection = Collection.query.get_or_404(collection_id)
    have = back_ids(collection)
    picked = sorted({int(r) for r in request.form.getlist('back_pick') if str(r).isdigit() and int(r) in have}, key=have.index)
    designs = [d for d in (db.session.get(Design, i) for i in picked) if d is not None]
    back = redirect(url_for('admin.edit_collection', collection_id=collection_id))
    if len(designs) < 2:
        flash('Tick two or more back images that are the same layout in different colors.', 'error')
        return back
    if designs[0].parent_design_id:
        flash('Pick a main back image that is not already a color of another one.', 'error')
        return back
    linked = link_as_colors(designs)
    db.session.commit()
    flash(f'Linked {linked} color{"s" if linked != 1 else ""} to "{designs[0].title or "the main back image"}".', 'success')
    return back


@admin_bp.route('/collections/<int:collection_id>/back-designs/<int:design_id>/unlink', methods=['POST'])
@admin_required
def collection_back_design_unlink(collection_id, design_id):
    """Make a linked back color its own back image again (it stays on the back list)."""
    Collection.query.get_or_404(collection_id)
    design = Design.query.get_or_404(design_id)
    if design.parent_design_id:
        design.parent_design_id = None
        db.session.commit()
        flash('That color is its own back image again.', 'success')
    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


@admin_bp.route('/collections/<int:collection_id>/designs/<int:design_id>/unlink', methods=['POST'])
@admin_required
def collection_design_unlink(collection_id, design_id):
    """Make a linked color a separate design again."""
    import json as _json
    collection = Collection.query.get_or_404(collection_id)
    design = Design.query.get_or_404(design_id)
    if design.parent_design_id:
        design.parent_design_id = None
        ids = _json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
        if design.id not in ids:
            ids.append(design.id)
            collection.allowed_design_ids = _json.dumps(ids)
        db.session.commit()
        flash('That color is its own design again.', 'success')
    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


@admin_bp.route('/collections/<int:collection_id>/designs/<int:design_id>/make-main', methods=['POST'])
@admin_required
def collection_design_make_main(collection_id, design_id):
    """Pick which color is the main picture shoppers see first for a design."""
    from utils.group_designs import make_main
    collection = Collection.query.get_or_404(collection_id)
    design = Design.query.get_or_404(design_id)
    if make_main(collection, design):
        db.session.commit()
        flash('That color is now the main picture.', 'success')
    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


@admin_bp.route('/collections/<int:collection_id>/designs/<int:design_id>/remove-color', methods=['POST'])
@admin_required
def collection_design_remove_color(collection_id, design_id):
    """Delete one color of a design. The main picture and the other colors stay."""
    pass
    from utils.group_designs import detach, uses
    collection = Collection.query.get_or_404(collection_id)
    design = Design.query.get_or_404(design_id)
    if not design.parent_design_id:
        flash('Use the red x on the design to delete the whole design.', 'error')
        return redirect(url_for('admin.edit_collection', collection_id=collection_id))
    design.parent_design_id = None
    detach(collection, design.id)
    db.session.flush()
    try:
        in_orders = design.order_items.count() > 0
    except Exception:
        in_orders = False
    if not in_orders and not uses(design.id):
        try:
            _delete_design_file(design)
        except Exception as e:
            current_app.logger.warning('Could not delete color file %s: %s', design.id, e)
        db.session.delete(design)
    db.session.commit()
    flash('That color was deleted.', 'success')
    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


@admin_bp.route('/collections/<int:collection_id>/designs/<int:design_id>/remove', methods=['POST'])
@admin_required
def collection_design_remove(collection_id, design_id):
    """Remove a design from a collection's approved list and permanently delete it."""
    import json as _json
    collection = Collection.query.get_or_404(collection_id)
    design = Design.query.get_or_404(design_id)
    from utils.group_designs import JERSEY_LOGO_MESSAGE, jersey_logo_ids
    if design_id in jersey_logo_ids(collection):
        flash(JERSEY_LOGO_MESSAGE, 'error')
        return redirect(url_for('admin.edit_collection', collection_id=collection_id))

    # Remove from allowed_design_ids
    ids = _json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    ids = [i for i in ids if i != design_id]
    collection.allowed_design_ids = _json.dumps(ids) if ids else None
    from utils.group_designs import forget_back_design
    forget_back_design(collection, design_id)

    # Delete the design record and its file
    try:
        _delete_design_file(design)
    except Exception as e:
        current_app.logger.warning('Could not delete design file for design %s: %s', design_id, e)
    db.session.delete(design)

    try:
        db.session.commit()
        flash('Design removed from group order.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('collection_design_remove failed: %s', e)
        flash('Could not remove design. Please try again.', 'error')

    return redirect(url_for('admin.edit_collection', collection_id=collection_id))


@admin_bp.route('/collections/<int:collection_id>/designs/bulk', methods=['POST'])
@admin_required
def collection_designs_bulk(collection_id):
    """Take every ticked design off this group order, or delete them all, in one step."""
    import json as _json
    from utils.group_designs import detach, forget_back_design
    collection = Collection.query.get_or_404(collection_id)
    ids = [int(i) for i in request.form.getlist('pick') if str(i).isdigit()]
    from utils.group_designs import JERSEY_LOGO_MESSAGE, jersey_logo_ids
    protected = [i for i in ids if i in jersey_logo_ids(collection)]
    if protected:
        flash(JERSEY_LOGO_MESSAGE, 'error')          # the jersey logo stays; everything else ticked still goes
        ids = [i for i in ids if i not in protected]
    action = request.form.get('action')
    if not ids and protected:
        return redirect(url_for('admin.edit_collection', collection_id=collection_id))
    if not ids or action not in ('detach', 'delete'):
        flash('Tick the designs you want to change first.', 'error')
        return redirect(url_for('admin.edit_collection', collection_id=collection_id))
    try:
        if action == 'detach':
            for design_id in ids:
                detach(collection, design_id)
            flash(f'Took {len(ids)} design{"s" if len(ids) != 1 else ""} off this group order. The artwork is still on file.', 'success')
        else:
            kept = [i for i in (_json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []) if i not in ids]
            collection.allowed_design_ids = _json.dumps(kept) if kept else None
            gone = 0
            for design in Design.query.filter(Design.id.in_(ids)).all():
                forget_back_design(collection, design.id)
                try:
                    _delete_design_file(design)
                except Exception as e:
                    current_app.logger.warning('Could not delete design file for design %s: %s', design.id, e)
                db.session.delete(design)
                gone += 1
            flash(f'Deleted {gone} design{"s" if gone != 1 else ""}.', 'success')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('collection_designs_bulk failed: %s', e)
        flash('Could not change those designs. Please try again.', 'error')
    return redirect(url_for('admin.edit_collection', collection_id=collection_id))
