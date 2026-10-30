from flask import Blueprint, render_template, request, jsonify, url_for, session, redirect, flash, current_app, abort
from models import db, Product, Design, Collection
from utils import sales_tax
from flask_login import login_required, current_user
from utils.mockups import (
    get_carousel_colors_for_product,
    get_color_variants_data_for_product,
    get_first_shop_image_url,
    product_has_shop_image,
)
from utils.cloud_storage import image_url as _resolve_image_url
from utils.json_fields import parse_json_list, parse_json_object
from utils.product_filters import (
    canonical_category_param,
    catalog_filter_options,
    group_catalog_by_age,
    group_products_by_family,
    infer_age,
    infer_brand,
    infer_category,
    infer_fit,
    matches_filters,
    prepare_catalog,
    shop_filter_options,
    sort_catalog,
)
from utils.sizes import shop_sizes_for_product
from utils.product_slugs import assign_product_slug
from utils.color_names import (
    color_matches_any_filter,
    family_short_label,
    family_swatch_hex,
    filter_carousel_to_color_filters,
    grouped_colors_by_family,
    parse_color_filters,
    selected_color_families,
    unique_display_colors,
)
from utils.fonts import CUSTOMIZE_BACK_FONTS, GROUP_ORDER_FONTS
import json

shop_bp = Blueprint('shop', __name__, url_prefix='/shop')


def _peek_garment_metrics(color_variants):
    """Already-measured shirt boxes for this product's mockups, keyed by image URL."""
    try:
        from services.garment_metrics import peek_cached
    except Exception:
        return {}
    seed = {}
    for variant in color_variants or []:
        for key in ('front_image', 'back_image'):
            src = (variant.get(key) or '').strip()
            if not src or src in seed:
                continue
            try:
                cached = peek_cached(src)
            except Exception:
                cached = None
            if cached and cached.get('ok'):
                seed[src] = cached
    return seed


def _measure_garment_metrics(color_variants, app=None):
    """Measure jersey mockups now so a locked logo paints at the final size."""
    try:
        from services.garment_metrics import measure
    except Exception:
        return _peek_garment_metrics(color_variants)
    seed = {}
    for variant in color_variants or []:
        for key in ('front_image', 'back_image'):
            src = (variant.get(key) or '').strip()
            if not src or src in seed:
                continue
            try:
                result = measure(src, app)
            except Exception:
                result = None
            if result and result.get('ok'):
                seed[src] = result
    return seed


def _stamp_artwork_fits(cards):
    """Attach cached visible-width ratios so the first click can paint at final size."""
    if not cards:
        return cards
    try:
        from services.artwork_metrics import peek_cached
    except Exception:
        return cards
    ids = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        if card.get('id') is not None:
            ids.append(card['id'])
        for variant in card.get('variants') or []:
            if variant.get('id') is not None:
                ids.append(variant['id'])
    if not ids:
        return cards
    try:
        clean_ids = []
        for value in ids:
            clean_ids.append(int(value))
    except (TypeError, ValueError):
        return cards
    designs = Design.query.filter(Design.id.in_(clean_ids)).all()
    by_id = {design.id: design for design in designs}

    def _fit(design_id):
        design = by_id.get(int(design_id)) if design_id is not None else None
        if design is None:
            return None
        try:
            return peek_cached(design)
        except Exception:
            return None

    for card in cards:
        if not isinstance(card, dict):
            continue
        fit = _fit(card.get('id'))
        if fit is not None:
            card['artwork_fit'] = fit
        for variant in card.get('variants') or []:
            variant_fit = _fit(variant.get('id'))
            if variant_fit is not None:
                variant['artwork_fit'] = variant_fit
    return cards


def _measure_artwork_fits(cards, app=None):
    """Measure artwork now so a locked uniform logo paints at the final size."""
    if not cards:
        return cards
    try:
        from services.artwork_metrics import measure_design
    except Exception:
        return cards
    ids = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        if card.get('id') is not None:
            ids.append(card['id'])
    if not ids:
        return cards
    try:
        clean_ids = [int(value) for value in ids]
    except (TypeError, ValueError):
        return cards
    designs = Design.query.filter(Design.id.in_(clean_ids)).all()
    by_id = {design.id: design for design in designs}
    for card in cards:
        if not isinstance(card, dict) or card.get('id') is None:
            continue
        design = by_id.get(int(card['id']))
        if design is None:
            continue
        try:
            card['artwork_fit'] = measure_design(design, app)
        except Exception:
            continue
    return cards

@shop_bp.route('/')
def index():
    """Shop page - browse all products. Products come from S&S Activewear sync (Admin → Products)."""
    # The regular shop is never part of a group order: opening it leaves any group store,
    # so nothing added from here is tied to a team (a cart's group items are not touched).
    from utils.group_orders import leave_group_order
    leave_group_order()
    try:
        category = canonical_category_param(request.args.get('category'))
        age_group = (request.args.get('age_group') or '').strip().lower() or None
        fit_type = request.args.get('fit_type')
        neck_style = request.args.get('neck_style')
        sleeve_length = request.args.get('sleeve_length')
        color_filters = parse_color_filters(request.args.getlist('color'))
        color = color_filters[0] if color_filters else None
        brand = (request.args.get('brand') or '').strip() or None
        search_q = (request.args.get('q') or '').strip()

        from models import ProductColorVariant

        catalog = Product.query.filter_by(is_active=True).all()
        variants_by_product = {}
        if catalog:
            for variant in ProductColorVariant.query.filter(
                ProductColorVariant.product_id.in_([p.id for p in catalog])
            ).all():
                variants_by_product.setdefault(variant.product_id, []).append(variant)

        sellable = []
        for product in catalog:
            product.carousel_colors = get_carousel_colors_for_product(
                product, current_app,
                variants=variants_by_product.get(product.id, []))
            product.fallback_image_url = get_first_shop_image_url(
                product, current_app, carousel=product.carousel_colors)
            product.display_category = infer_category(product)
            product.display_age = infer_age(product)
            product.display_fit = infer_fit(product)
            product.display_brand = infer_brand(product)
            if product_has_shop_image(
                product, current_app,
                carousel=product.carousel_colors,
                image_url=product.fallback_image_url,
            ):
                sellable.append(product)

        filter_opts = shop_filter_options(sellable)
        colors = unique_display_colors(
            (variant.color_name or '').strip()
            for pid in {p.id for p in sellable}
            for variant in variants_by_product.get(pid, [])
        )

        # Cotton and CVC versions of one shirt show as ONE tile with every color; the color
        # a shopper picks decides which vendor style they buy (see utils/style_pairs.py).
        from utils.style_pairs import blend_pairs
        partner_of = {}
        for cotton, blend in blend_pairs(sellable):
            seen_colors = {(c.get('color_name') or '').strip().lower() for c in cotton.carousel_colors}
            for c in blend.carousel_colors:
                if (c.get('color_name') or '').strip().lower() not in seen_colors:
                    cotton.carousel_colors.append(c)
            cotton.merged_partner = blend
            partner_of[cotton.id] = blend
        hidden_partner_ids = {b.id for b in partner_of.values()}
        sellable = [p for p in sellable if p.id not in hidden_partner_ids]

        products = sellable
        if search_q:
            needle = search_q.lower()
            products = [
                p for p in products
                if needle in ' '.join([(partner_of[p.id].name or '') if p.id in partner_of else '', p.name or '']).lower()
                or needle in (p.style_number or '').lower()
                or needle in (p.description or '').lower()
                or needle in (p.category or '').lower()
                or needle in (p.brand or '').lower()
            ]
        products = [
            p for p in products
            if matches_filters(p, age_group=age_group, category=category, fit_type=fit_type)
        ]
        if brand:
            wanted = ''.join(ch for ch in brand.lower() if ch.isalnum())
            products = [
                p for p in products
                if wanted and wanted in ''.join(
                    ch for ch in (p.display_brand or infer_brand(p) or '').lower() if ch.isalnum()
                )
            ]
        if color_filters:
            matching_ids = {
                pid for pid, variants in variants_by_product.items()
                if any(color_matches_any_filter(v.color_name, color_filters) for v in variants)
            }
            for cotton_id, blend in partner_of.items():      # a heather match counts for the combined shirt
                if blend.id in matching_ids:
                    matching_ids.add(cotton_id)
            products = [p for p in products if p.id in matching_ids]
            for product in products:
                product.carousel_colors = filter_carousel_to_color_filters(
                    product.carousel_colors, color_filters)
                if product.carousel_colors:
                    first_url = product.carousel_colors[0].get('front_image_url')
                    if first_url:
                        product.fallback_image_url = first_url

        # Adult → Youth → Toddler → Baby, then garment type within each age
        products = sort_catalog(products)
        product_sections = group_catalog_by_age(products)
        product_families = group_products_by_family(products)
        # Sort. "Featured" puts customer favorites first and otherwise keeps the catalog order.
        sort = (request.args.get('sort') or 'featured').strip().lower()
        if sort not in ('featured', 'price_asc', 'price_desc', 'newest', 'popular'):
            sort = 'featured'
        if sort in ('price_asc', 'price_desc'):
            product_families = sorted(product_families, key=lambda f: float(f['primary'].base_price or 0),
                                      reverse=(sort == 'price_desc'))
        elif sort == 'newest':
            from datetime import datetime as _dt
            product_families = sorted(
                product_families,
                key=lambda f: max((m.created_at or _dt.min) for m in f['members']), reverse=True)
        elif sort == 'popular':
            from sqlalchemy import func
            from models import OrderItem
            sold = dict(db.session.query(OrderItem.product_id, func.sum(OrderItem.quantity))
                        .group_by(OrderItem.product_id).all())
            product_families = sorted(
                product_families, key=lambda f: sum(int(sold.get(m.id) or 0) for m in f['members']), reverse=True)
        else:
            product_families = sorted(
                product_families, key=lambda f: 0 if any(m.is_customer_favorite for m in f['members']) else 1)
        categories = [row['key'] for row in filter_opts['categories']]
        fit_types = filter_opts['fits']
        neck_styles = []
        sleeve_lengths = []
        shop_brands = filter_opts['brands']
        
        grouped_colors = grouped_colors_by_family(colors)
        color_families = [
            {
                'name': family,
                'short': family_short_label(family),
                'swatch': family_swatch_hex(family),
            }
            for family, _ in grouped_colors
        ]
        highlighted_families = selected_color_families(color_filters)
        design_id = request.args.get('design_id', type=int)

        from utils.daily_quote import todays_quote
        daily_affirmation = todays_quote()

        return render_template('shop/index.html',
                             products=products,
                             product_sections=product_sections,
                             product_families=product_families,
                             selected_sort=sort,
                             categories=categories,
                             fit_types=fit_types,
                             neck_styles=neck_styles,
                             sleeve_lengths=sleeve_lengths,
                             colors=colors,
                             grouped_colors=grouped_colors,
                             color_families=color_families,
                             selected_colors=color_filters,
                             selected_color_families=highlighted_families,
                             selected_color_family=(highlighted_families[0] if highlighted_families else ''),
                             shop_brands=shop_brands,
                             filter_ages=filter_opts['ages'],
                             filter_categories=filter_opts['categories'],
                             filter_fits=filter_opts['fits'],
                             selected_brand=brand,
                             selected_category=category,
                             selected_age_group=age_group,
                             selected_fit_type=fit_type,
                             selected_neck_style=neck_style,
                             selected_sleeve_length=sleeve_length,
                             selected_color=color,
                             design_id=design_id,
                             daily_affirmation=daily_affirmation)
    except Exception as e:
        # If there's a database error, log it and show empty shop
        import sys
        print(f"ERROR in shop index: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return render_template('shop/index.html',
                             products=[],
                             product_sections=[],
                             product_families=[],
                             categories=[],
                             fit_types=[],
                             neck_styles=[],
                             sleeve_lengths=[],
                             colors=[],
                             grouped_colors=[],
                             color_families=[],
                             selected_colors=[],
                             selected_color_families=[],
                             selected_color_family='',
                             shop_brands=[],
                             filter_ages=[],
                             filter_categories=[],
                             filter_fits=[],
                             selected_brand=None,
                             selected_category=None,
                             selected_age_group=None,
                             selected_fit_type=None,
                             selected_neck_style=None,
                             selected_sleeve_length=None,
                             selected_color=None,
                             design_id=None)


@shop_bp.route('/company-apparel')
def company_apparel():
    """For a business that wants to buy shirts for its team. Leads into the normal group-order setup."""
    return render_template('shop/company_apparel.html')


@shop_bp.route('/group-orders')
def group_orders():
    """Group order landing page + public directory of open collections"""
    from flask_login import current_user
    from models import Collection, OrgSection
    from utils.group_orders import (
        is_deadline_passed,
        is_not_yet_open,
        public_group_directory,
    )

    open_orgs, open_collections = public_group_directory()

    return render_template(
        'shop/group_orders.html',
        is_admin=current_user.is_authenticated and getattr(current_user, 'is_admin', False),
        open_collections=open_collections,
        open_orgs=open_orgs,
    )


@shop_bp.route('/group-orders/create', methods=['GET', 'POST'])
@login_required
def create_group_order():
    """Create a group order - any logged-in user with a profile"""
    from datetime import datetime
    
    if request.method == 'POST':
        from routes.admin import _save_collection_design
        from slugify import slugify
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        # ── 1. Validate required fields up front (clear, user-facing messages) ──
        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Please enter a name for your group order.', 'error')
            return redirect(url_for('shop.create_group_order'))

        try:
            # ── 2. Build a unique slug ──────────────────────────────────────
            requested_slug = (request.form.get('slug') or '').strip()
            base_slug = slugify(requested_slug) or slugify(name) or 'group-order'
            slug = base_slug
            n = 1
            while Collection.query.filter_by(slug=slug).first():
                slug = f"{base_slug}-{n}"
                n += 1
            if slug != base_slug:
                flash(f'URL slug adjusted to "{slug}" (original was already in use).', 'info')

            # ── 3. Create the collection (tax is fixed at KS 9.5%) ───────────
            collection = Collection(
                name=name,
                slug=slug,
                description=request.form.get('description'),
                # New group orders are always created live so the share link
                # works immediately (the share page only serves active orders).
                is_active=True,
                pickup_address=request.form.get('pickup_address'),
                pickup_instructions=request.form.get('pickup_instructions'),
                shipping_enabled=request.form.get('shipping_enabled') == 'on',
                allow_cash_pickup=request.form.get('allow_cash_pickup') == 'on',
                tax_rate=sales_tax.rate_percent(),
            )
            from utils.group_orders import apply_collection_visibility
            apply_collection_visibility(collection)
            collection.restrict_options = request.form.get('restrict_options') == 'on'
            collection.allow_custom_upload = True
            from utils.group_orders import serialize_allowed_colors_from_form
            allowed_colors_json = serialize_allowed_colors_from_form(request.form.getlist('allowed_colors'))
            collection.allowed_colors = allowed_colors_json
            allowed_placements = request.form.getlist('allowed_placements')
            collection.allowed_placements = json.dumps(allowed_placements) if allowed_placements else None

            # Collect chosen gallery designs now. File uploads wait until the
            # group order is saved — background-cut used to freeze this page
            # for minutes before anything was written.
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
            from utils.group_orders import apply_locked_back_design
            apply_locked_back_design(collection, current_user)

            from utils.group_orders import apply_collection_card, apply_schedule_from_form, apply_group_kind, set_collection_products_from_form
            apply_collection_card(collection)
            ok, kind_error = apply_group_kind(collection, required=True)
            if not ok:
                flash(kind_error, 'error')
                return redirect(url_for('shop.create_group_order'))
            from utils.group_roster import apply_payment_mode_from_form
            ok, payment_error = apply_payment_mode_from_form(collection)
            if not ok:
                flash(payment_error, 'error')
                return redirect(url_for('shop.create_group_order'))

            password = request.form.get('password')
            if password:
                collection.set_password(password)
            ok, schedule_error = apply_schedule_from_form(collection)
            if not ok:
                flash(schedule_error, 'error')
                return redirect(url_for('shop.create_group_order'))

            # Track who created this group order (for permission checks)
            collection.created_by_user_id = current_user.id
            from utils.group_orders import apply_organizer_from_form
            ok, organizer_error, organizer_notice = apply_organizer_from_form(collection)
            if not ok:
                flash(organizer_error, 'error')
                organizer_notice = None

            db.session.add(collection)
            db.session.flush()

            # ── 5. Link selected products ───────────────────────────────────
            selected_products, product_error = set_collection_products_from_form(collection)
            if product_error:
                db.session.rollback()
                flash(product_error, 'error')
                return redirect(url_for('shop.create_group_order'))
            if not selected_products:
                db.session.rollback()
                flash('Please choose a uniform or at least one shirt style for fan wear.', 'error')
                return redirect(url_for('shop.create_group_order'))
            from utils.group_roster import roster_item_error
            roster_error = roster_item_error(collection)
            if roster_error:
                db.session.rollback()
                flash(roster_error, 'error')
                return redirect(url_for('shop.create_group_order'))

            # ── 6. Commit the store first so a slow logo upload cannot
            #     hold the whole create on "Creating…" with nothing saved.
            db.session.commit()

            upload_count = 0
            new_upload_ids = []
            if pending_uploads:
                for f in pending_uploads:
                    try:
                        design = _save_collection_design(f, current_user.id)
                    except Exception as e:
                        current_app.logger.exception('Group order artwork upload failed: %s', e)
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
            if upload_count or showcase_ids:
                db.session.commit()

            # ── 7. Verify it saved with a valid, accessible ID ──────────────
            if not collection.id:
                raise SQLAlchemyError('Collection was not assigned an ID after commit')

            # Tell the admin a group was just set up (not for groups the admin makes themself).
            if not getattr(current_user, 'is_admin', False):
                from utils.group_org import team_names_from_form
                from utils.group_notifications import notify_group_created
                teams = team_names_from_form(request.form) if request.form.get('org_action') == 'new' else []
                notify_group_created(current_app._get_current_object(), collection, current_user,
                                     teams if len(teams) > 1 else [])

            # ── 8. Multi-team organization (optional) ───────────────────────
            # Mirrors admin logic: create an org + one store per team in the
            # same transaction, then commit once so nothing is left half-built.
            org_flash = None
            org_action = request.form.get('org_action', '')
            if org_action == 'new':
                try:
                    from utils.group_org import OrgSetupError, create_org_from_wizard
                    org, stores = create_org_from_wizard(collection, request.form, current_user)
                    db.session.commit()
                    if len(stores) > 1:
                        org_flash = (
                            f'Created {len(stores)} team stores for {org.name}. '
                            f'Share this link with your families: '
                            f'purposefullymadekc.com/org/{org.slug}'
                        )
                        return redirect(url_for('org.manage', slug=org.slug))
                    else:
                        org_flash = (
                            f'Organization page created for {org.name}. '
                            f'Share purposefullymadekc.com/org/{org.slug}'
                        )
                        flash(org_flash, 'success')
                        return redirect(url_for('org.manage', slug=org.slug))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.exception('Org creation error during user group order: %s', e)
                    flash('Your group order was saved but we could not set up the multi-team organization. Please contact us.', 'warning')
                    return redirect(url_for('collection.share', slug=collection.slug))
            elif org_action == 'existing':
                try:
                    from utils.group_org import add_store_to_org
                    org = add_store_to_org(collection, request.form)
                    db.session.commit()
                    if org:
                        org_flash = f'Added to the {org.name} organization page.'
                        flash(org_flash, 'success')
                except Exception as e:
                    current_app.logger.exception('Add-to-org error during user group order: %s', e)

            msg = 'Group order created successfully'
            if upload_count:
                msg += f' with {upload_count} design(s) uploaded'
            flash(msg + '. Share your link below!', 'success')
            if organizer_notice:
                flash(organizer_notice, 'success')
            return redirect(url_for('collection.share', slug=collection.slug))

        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.warning('Group order create IntegrityError for user %s: %s', current_user.id, e)
            flash('A group order with that name or URL already exists. Try a different name.', 'error')
            return redirect(url_for('shop.create_group_order'))
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('Group order create database error for user %s: %s', current_user.id, e)
            flash('We could not save your group order due to a server issue. Please try again, '
                  'and contact us if it keeps happening.', 'error')
            return redirect(url_for('shop.create_group_order'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Unexpected error creating group order for user %s: %s', current_user.id, e)
            flash('Something went wrong while creating your group order. Please review your '
                  'details and try again.', 'error')
            return redirect(url_for('shop.create_group_order'))
    
    from utils.product_filters import load_group_order_form_catalog
    from utils.group_order_templates import TEMPLATE_KEYS, group_order_templates
    from utils.group_defaults import default_fan_color_keys
    catalog = load_group_order_form_catalog()
    selected_template = request.args.get('type')
    return render_template('admin/add_collection.html',
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
                         is_user_create=True)


_GROUP_ORDER_FONTS = GROUP_ORDER_FONTS


@shop_bp.route('/group-orders/<slug>/teams/add', methods=['POST'])
@login_required
def group_order_add_teams(slug):
    """Organizer version of adding teams: turn this group order into a multi-team group."""
    from utils.group_orders import user_can_manage_collection
    from utils.group_org import OrgSetupError, add_teams_to_group
    collection = Collection.query.filter_by(slug=slug).first_or_404()
    if not user_can_manage_collection(collection):
        flash('You can only edit group orders you created.', 'error')
        return redirect(url_for('account.my_group_orders'))
    try:
        org, stores = add_teams_to_group(collection, request.form.getlist('org_team_names[]'),
                                         request.form.get('first_team_name'), current_user, request.form)
        db.session.commit()
        flash(f'Added {len(stores)} team{"s" if len(stores) != 1 else ""} to {org.name}. Each has its own store and link.', 'success')
    except OrgSetupError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('group_order_add_teams failed: %s', e)
        flash('Could not add those teams. Please try again.', 'error')
    return redirect(url_for('shop.edit_group_order', slug=collection.slug))


@shop_bp.route('/group-orders/<slug>/edit', methods=['GET', 'POST'])
@login_required
def edit_group_order(slug):
    """Let the organizer (or admin) change an existing group order."""
    import json
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
    from utils.group_orders import (
        apply_collection_form,
        designs_for_group_order_form,
        user_can_manage_collection,
    )
    from utils.product_filters import load_group_order_form_catalog

    collection = Collection.query.filter_by(slug=slug).first_or_404()
    if not user_can_manage_collection(collection):
        flash('You can only edit group orders you created.', 'error')
        return redirect(url_for('account.my_group_orders'))

    if request.method == 'POST':
        try:
            ok, error, upload_count = apply_collection_form(
                collection, current_user, allow_slug=False, require_products=True
            )
            if not ok:
                db.session.rollback()
                flash(error, 'error')
                return redirect(url_for('shop.edit_group_order', slug=collection.slug))
            db.session.commit()
            msg = 'Group order updated'
            if upload_count:
                msg += f' with {upload_count} new design(s) uploaded'
            flash(msg + '.', 'success')
            if collection.is_active:
                return redirect(url_for('collection.share', slug=collection.slug))
            return redirect(url_for('account.my_group_orders'))
        except IntegrityError:
            db.session.rollback()
            flash('Could not save those changes. Please try again.', 'error')
            return redirect(url_for('shop.edit_group_order', slug=slug))
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception('Organizer edit_group_order database error: %s', e)
            flash('Could not save the group order due to a server issue. Please try again.', 'error')
            return redirect(url_for('shop.edit_group_order', slug=slug))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Organizer edit_group_order unexpected error: %s', e)
            flash('Something went wrong while saving. Please try again.', 'error')
            return redirect(url_for('shop.edit_group_order', slug=slug))

    catalog = load_group_order_form_catalog()
    from utils.group_orders import fan_color_checked_keys, fanwear_excluded_ids, org_sync_info, team_store_config
    from utils.group_designs import section_names, sections_map
    fan_color_checked = fan_color_checked_keys(
        collection, collection.products, catalog['uniform_colors_by_product']
    )
    allowed_design_ids_list = json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    showcase_design_ids_list = json.loads(collection.showcase_design_ids) if getattr(collection, 'showcase_design_ids', None) else []
    allowed_placements_list = json.loads(collection.allowed_placements) if collection.allowed_placements else ['center_chest', 'left_chest', 'right_chest', 'center_back']
    return render_template(
        'shop/edit_group_order.html',
        collection=collection,
        products=catalog['products'],
        gallery_designs=designs_for_group_order_form(collection),
        fan_color_picker=catalog['fan_color_picker'],
        fan_color_checked=fan_color_checked,
        uniform_colors_by_product=catalog['uniform_colors_by_product'],
        team_store=team_store_config(collection),
        allowed_design_ids_list=allowed_design_ids_list,
        showcase_design_ids_list=showcase_design_ids_list,
        design_sections_map=sections_map(collection),
        design_section_list=section_names(collection),
        allowed_placements_list=allowed_placements_list,
        fanwear_excluded_ids_list=fanwear_excluded_ids(collection),
        sync_org=org_sync_info(collection),
        back_design_fonts=_GROUP_ORDER_FONTS,
        collection_product_ids=[p.id for p in collection.products],
        catalog_filter_opts=catalog['catalog_filter_opts'],
        catalog_filter_picker=True,
        is_user_edit=True,
    )


MAX_GALLERY_CARDS = 300


@shop_bp.route('/designs')
def design_gallery():
    """Browse designs: collection, then subcategory, then the designs. Everything finer is a filter or a search."""
    from utils.group_orders import leave_group_order
    leave_group_order()          # the gallery is not part of a group order
    from utils.design_categories import normalize_category
    from utils.design_taxonomy import COLLECTION_BY_KEY, label_for
    from utils import design_gallery as dg
    from utils.design_variants import gallery_cards_for_public
    try:
        all_cards = dg.enrich_cards(gallery_cards_for_public(Design, resolve_url=_resolve_image_url))
    except Exception:
        current_app.logger.exception('design gallery could not load')
        all_cards = []

    product_id = request.args.get('product_id', type=int)
    gallery_product = Product.query.get(product_id) if product_id else None
    search_query = (request.args.get('q') or '').strip()

    # Which collection? New links use ?collection=; links that already exist use ?category= (still honored).
    key = (request.args.get('collection') or '').strip().lower()
    legacy = normalize_category(request.args.get('category'))
    if not key and legacy:
        key = 'fan-favorites' if legacy == 'favorites' else dg.LEGACY_TO_COLLECTION.get(legacy, '')
    automatic = key in dg.AUTOMATIC_KEYS
    if key and not automatic and key not in COLLECTION_BY_KEY:
        key = ''
    sub = (request.args.get('sub') or '').strip().lower() if key and not automatic else ''
    autos = dg.automatic_collections(all_cards) if all_cards and (automatic or not key) else {}

    active_folder, designs, truncated = None, [], 0
    subs, filters, chosen = [], {}, {}
    if key:
        if automatic:
            label = next(l for k, l, _b in dg.AUTOMATIC if k == key)
            members = autos.get(key, [])
        else:
            label = COLLECTION_BY_KEY[key].label
            subs = dg.subcategory_options(all_cards, key)
            if sub and sub not in {s_['key'] for s_ in subs}:
                sub = ''
            members = dg.collection_members(all_cards, key, sub or None)
        active_folder = {'key': key, 'label': label, 'count': len(members), 'covers': [],
                         'sub': sub, 'sub_label': label_for(key, sub) if sub else ''}
        pool = members
    else:
        pool = all_cards

    if not all_cards:
        gallery_view = 'empty'
    elif search_query:
        gallery_view = 'search'
        designs = dg.search_cards(all_cards, search_query, pool=pool)
    elif key:
        gallery_view = 'folder'
        designs = list(pool)
    else:
        gallery_view = 'folders'

    if gallery_view in ('folder', 'search'):
        filters = dg.filter_options(designs)
        designs, chosen = dg.apply_filters(designs, request.args)
        dg.attach_related(all_cards)
        if len(designs) > MAX_GALLERY_CARDS:          # thousands of designs: narrow by collection, subcategory or search
            truncated, designs = len(designs), designs[:MAX_GALLERY_CARDS]
    folders = dg.landing_tiles(all_cards, autos) if gallery_view == 'folders' else []

    return render_template(
        'shop/design_gallery.html',
        designs=designs,
        folders=folders,
        gallery_view=gallery_view,
        active_folder=active_folder,
        subs=subs,
        filters=filters,
        chosen=chosen,
        collection_labels={**{k: c.label for k, c in COLLECTION_BY_KEY.items()}, **{k: l for k, l, _b in dg.AUTOMATIC}},
        truncated=truncated,
        grouped=bool(key and not automatic and not search_query and not chosen),
        search_query=search_query,
        product_id=product_id,
        product_slug=gallery_product.slug if gallery_product else None,
    )


def _require_sellable_product(product):
    """Products without a photo stay in the catalog but cannot be sold."""
    if product and product.is_active and product_has_shop_image(product, current_app):
        return None
    flash('This product is not available to order yet.', 'error')
    return redirect(url_for('shop.index'))


def _canonical_product_redirect(product, endpoint):
    """Send leftover numeric URLs to the slug URL Google should index."""
    if not product.slug:
        assign_product_slug(product)
        db.session.commit()
    target = url_for(endpoint, product_slug=product.slug)
    if request.query_string:
        target = f'{target}?{request.query_string.decode()}'
    return redirect(target, code=301)


def _product_from_url(product_slug):
    """Resolve /shop/product/<slug> (or a leftover numeric id) to a Product."""
    product = Product.query.filter_by(slug=product_slug).first()
    if product:
        return product, None
    if str(product_slug).isdigit():
        product = Product.query.get(int(product_slug))
        if product:
            return product, True
    abort(404)


@shop_bp.route('/product/<product_slug>')
def product_detail(product_slug):
    """Product detail page with customizer"""
    product, stale_numeric = _product_from_url(product_slug)
    blocked = _require_sellable_product(product)
    if blocked:
        return blocked
    if stale_numeric:
        return _canonical_product_redirect(product, 'shop.product_detail')
    product.display_brand = infer_brand(product)
    available_sizes = shop_sizes_for_product(product)
    available_colors = parse_json_list(product.available_colors)
    print_area_config = parse_json_object(product.print_area_config)
    color_variants_data = get_color_variants_data_for_product(product, current_app)
    from utils.group_orders import get_active_collection, group_fulfillment_customer_note
    return render_template('shop/product_detail.html',
                         product=product,
                         available_sizes=available_sizes,
                         available_colors=available_colors,
                         color_variants=color_variants_data,
                         print_area_config=print_area_config,
                         fulfillment_note=group_fulfillment_customer_note(get_active_collection()))


def _cart_line_for_edit(product):
    """What the customizer needs to reopen a cart line (?edit=<line number>): None unless it is a line of this very product."""
    index = request.args.get('edit', type=int)
    if index is None:
        return None
    from utils.cart_store import get_cart
    cart = get_cart()
    if not (0 <= index < len(cart)) or not isinstance(cart[index], dict):
        return None
    line = cart[index]
    if str(line.get('product_id')) != str(product.id):
        return None
    meta = line.get('back_design_meta')
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = None
    try:
        design_id = int(line.get('design_id')) if line.get('design_id') not in (None, '') else None
    except (TypeError, ValueError):
        design_id = None
    return {'index': index, 'color': line.get('color'), 'size': line.get('size'), 'quantity': line.get('quantity') or 1,
            'placement': line.get('placement'), 'design_id': design_id, 'design_url': line.get('design_url'),
            'back_url': line.get('back_design_url'), 'back_kind': line.get('back_design_kind'),
            'back_meta': meta if isinstance(meta, dict) else None}


@shop_bp.route('/customize/<product_slug>')
def customize(product_slug):
    """Product customizer interface"""
    from flask_login import current_user
    from utils.group_orders import (
        allowed_colors_for_product,
        allowed_design_ids as collection_design_id_list,
        collection_has_color_restrictions,
        get_active_collection,
        group_fulfillment_customer_note,
        load_collection_designs,
        load_design_dict,
        ordering_blocked,
        resolve_uniform_design_id,
        team_store_config,
        team_store_choice,
    )

    product, stale_numeric = _product_from_url(product_slug)
    blocked = _require_sellable_product(product)
    if blocked:
        return blocked
    if stale_numeric:
        return _canonical_product_redirect(product, 'shop.customize')
    product.display_brand = infer_brand(product)
    available_sizes = shop_sizes_for_product(product)
    available_colors = parse_json_list(product.available_colors)
    print_area_config = parse_json_object(product.print_area_config)
    color_variants_data = get_color_variants_data_for_product(product, current_app)

    # Collection restrictions: organizer chose specific colors/designs/placements - filter options
    collection_restricted = False
    allow_custom_upload = True  # default: show upload area
    allowed_placements = None  # None = all allowed
    back_design_font = None
    back_fonts_allowed = []     # several fonts the organizer offers: the shopper picks among these
    back_design_text_color = None
    back_design_outline = None   # None = use customer's choice
    back_design_outline_color = None
    lock_back_design_style = False
    allowed_design_ids = None
    back_design_type = 'both'   # 'none' | 'name_number' | 'image' | 'both'
    allow_back_design = True
    back_design_name_part = 'last'
    allow_stacked_name = True
    preset_back_design = None
    back_options = []
    catalog_section = None
    uniform_kit = None
    uniform_locked_color = None
    uniform_logo_locked = False
    coll = get_active_collection()
    from utils.group_orders import leave_group_order, shopping_outside_group
    if coll and shopping_outside_group(coll, product.id):
        leave_group_order()          # a style the group does not sell: this is regular shopping
        coll = None
    if coll:
        from utils.group_orders import is_not_yet_open
        blocked = ordering_blocked(coll, product.id)
        if blocked and not is_not_yet_open(coll):
            # Order is closed/past deadline — redirect away entirely
            flash(blocked, 'error')
            return redirect(url_for('collection.view', slug=coll.slug))
        catalog_section, uniform_kit, uniform_locked_color, choice_error = (
            team_store_choice(
                coll,
                product.id,
                request.args.get('catalog_section'),
                request.args.get('uniform_kit'),
            )
        )
        if choice_error:
            flash(choice_error, 'warning')
            return redirect(url_for('collection.view', slug=coll.slug))
        if uniform_locked_color:
            color_variants_data = [
                v for v in color_variants_data
                if v['color_name'] == uniform_locked_color
            ]
            if not color_variants_data:
                flash('That uniform color is temporarily unavailable.', 'warning')
                return redirect(url_for('collection.view', slug=coll.slug))
        has_colors = (
            catalog_section == 'fan'
            and collection_has_color_restrictions(coll)
        )
        has_designs = bool(collection_design_id_list(coll))
        has_placements = bool(parse_json_list(coll.allowed_placements or ''))
        collection_restricted = bool(
            coll.restrict_options
            or has_colors
            or has_designs
            or catalog_section == 'uniform'
        )
        allow_custom_upload = getattr(coll, 'allow_custom_upload', True)
        back_design_font = getattr(coll, 'back_design_font', None)
        _picked_fonts = coll.back_fonts_list if hasattr(coll, 'back_fonts_list') else []
        back_fonts_allowed = _picked_fonts if len(_picked_fonts) > 1 else []
        back_design_text_color = getattr(coll, 'back_design_text_color', None)
        _outline = getattr(coll, 'back_design_outline', None)
        back_design_outline = _outline if _outline is not None else True
        back_design_outline_color = getattr(coll, 'back_design_outline_color', None)
        lock_back_design_style = bool(getattr(coll, 'lock_back_design_style', False))
        back_design_type = getattr(coll, 'back_design_type', 'both') or 'both'
        _allow = getattr(coll, 'allow_back_design', None)
        allow_back_design = bool(_allow) if _allow is not None else True
        name_part = (getattr(coll, 'back_design_name_part', None) or 'last').strip().lower()
        back_design_name_part = name_part if name_part in ('first', 'last') else 'last'
        allow_stacked_name = getattr(coll, 'allow_stacked_name', None) is not False
        if has_colors:
            allowed = allowed_colors_for_product(product, coll)
            if allowed is not None:
                color_variants_data = [v for v in color_variants_data if v['color_name'] in allowed]
            if not color_variants_data:
                flash(
                    f'"{product.name}" is not available in the colors chosen for this order. Please select a different style.',
                    'warning'
                )
                return redirect(url_for('collection.view', slug=coll.slug))
        if has_designs:
            from utils.group_orders import with_linked_colors
            allowed_design_ids = with_linked_colors(collection_design_id_list(coll))
        if has_placements:
            allowed_placements = parse_json_list(coll.allowed_placements)
        lane_config = team_store_config(coll)
        if (
            catalog_section == 'fan'
            and lane_config['uniform']['enabled']
            and not lane_config['fan_personalization_enabled']
        ):
            allow_back_design = False
            back_design_type = 'none'
        if allow_back_design and back_design_type in ('image', 'both'):
            preset_back_design = load_design_dict(getattr(coll, 'back_design_id', None))
            if back_design_type in ('image', 'both'):       # the shopper picks from every back image of the group
                from utils.group_designs import back_options as _back_options
                back_options = _back_options(coll)
    
    # Cotton + CVC versions of this shirt are one item: add the other fabric's colors, each
    # color remembering its own vendor style (the page switches style/price when one is picked).
    style_note = None
    merged_partner = None
    try:
        from utils.style_pairs import fabric_label, find_partner
        partner = find_partner(product)
        if partner is not None and product_has_shop_image(partner, current_app) and catalog_section != 'uniform':
            partner_ok = True
            if coll:
                from utils.group_orders import product_in_collection
                partner_ok = (product_in_collection(coll, partner.id)
                              and not team_store_choice(coll, partner.id, catalog_section, None)[3])
            if partner_ok:
                partner_variants = get_color_variants_data_for_product(partner, current_app)
                if coll and catalog_section == 'fan' and collection_has_color_restrictions(coll):
                    allowed_partner = allowed_colors_for_product(partner, coll)
                    if allowed_partner is not None:
                        partner_variants = [v for v in partner_variants if v['color_name'] in allowed_partner]
                known = {(v['color_name'] or '').strip().lower() for v in color_variants_data}
                extra = [v for v in partner_variants if (v['color_name'] or '').strip().lower() not in known]
                if extra:
                    merged_partner = partner
                    for v in color_variants_data:
                        v.update(product_id=product.id, style=product.style_number,
                                 price=float(product.base_price or 0), fabric=fabric_label(product))
                    for v in extra:
                        v.update(product_id=partner.id, style=partner.style_number,
                                 price=float(partner.base_price or 0), fabric=fabric_label(partner))
                    color_variants_data = color_variants_data + extra
                    available_sizes = list(dict.fromkeys(list(available_sizes) + list(shop_sizes_for_product(partner))))
    except Exception:
        current_app.logger.exception('Could not merge the cotton/CVC colors for product %s', product.id)
        merged_partner = None

    # Check for pre-selected design from gallery
    # Editing something already in the cart: the customizer opens with that item's choices filled in.
    edit_line = _cart_line_for_edit(product)
    design_id = request.args.get('design_id', type=int) or (edit_line or {}).get('design_id')
    preset_design = None
    if coll and catalog_section == 'uniform':
        locked_logo = load_design_dict(resolve_uniform_design_id(coll, uniform_kit))
        if locked_logo:
            preset_design = locked_logo
            uniform_logo_locked = True
            allow_custom_upload = False
    if design_id and not uniform_logo_locked:
        from utils.privacy import user_can_use_design
        from utils.group_orders import design_allowed_for_collection
        d = Design.query.get(design_id)
        permitted = (
            design_allowed_for_collection(d, coll)
            if coll else user_can_use_design(d)
        )
        if d and permitted:
            preset_design = {
                'id': d.id,
                'url': _resolve_image_url(d.file_path),
                'title': (d.title or d.original_filename or 'Design')
            }
    
    if edit_line and not preset_design and not uniform_logo_locked and edit_line.get('design_url'):
        preset_design = {'id': None, 'url': edit_line['design_url'], 'title': 'Your design'}     # a logo the customer uploaded

    # Gallery designs for inline "choose logo" section (mains + color variants)
    gallery_designs = []
    try:
        if coll:
            # ── Org Fan Wear: same org-wide designs on every Fan Wear path ──
            from utils.group_orders import org_for_collection, org_fanwear_design_ids
            _org, _fw_sec = org_for_collection(coll)
            _is_org_fanwear = bool(_org) and (
                catalog_section == 'fan' or 'fan' in (_fw_sec.label or '').lower()
            )
            if _is_org_fanwear:
                _merged = org_fanwear_design_ids(coll)
                if _merged:
                    from models import Design as _FWDesign
                    from utils.group_orders import design_cards, with_linked_colors
                    gallery_designs = design_cards(_merged)
                    allowed_design_ids = with_linked_colors(_merged)
                    collection_restricted = collection_restricted or bool(_merged)
            elif uniform_logo_locked:
                gallery_designs = []
            elif catalog_section == 'fan':
                # Fan wear: show only the designs the organizer uploaded for this
                # group (allowed_design_ids). The jersey logo toggle controls whether
                # the jersey-locked design is included or excluded from that set.
                fan_show_jersey = lane_config.get('fan_show_jersey_logo', True)
                if allowed_design_ids:
                    all_coll_designs = load_collection_designs(coll)
                    if not fan_show_jersey:
                        # Exclude the jersey logo design(s) when the organizer has
                        # opted to hide them from fan wear.
                        jersey_id = lane_config.get('uniform', {}).get('home_design_id')
                        away_id   = lane_config.get('uniform', {}).get('away_design_id')
                        excluded  = {int(x) for x in [jersey_id, away_id] if x}
                        gallery_designs = [d for d in all_coll_designs
                                           if d['id'] not in excluded]
                    else:
                        gallery_designs = all_coll_designs
                else:
                    gallery_designs = []
            else:
                # Uniform and general group-order section: only organizer-approved artwork.
                gallery_designs = (
                    load_collection_designs(coll) if allowed_design_ids else []
                )
        else:
            from utils.design_variants import gallery_cards_for_public
            gallery_designs = gallery_cards_for_public(
                Design, resolve_url=_resolve_image_url, limit=200
            )
            from utils.design_gallery import enrich_cards
            enrich_cards(gallery_designs)
    except Exception:
        pass
    # Category tabs use the same collections (and names) as the Design Gallery page.
    design_collections = []
    try:
        from utils.design_taxonomy import COLLECTIONS as _GALLERY_COLLECTIONS
        from utils.design_gallery import ALWAYS_SHOW
        for _col in _GALLERY_COLLECTIONS:
            _n = sum(1 for _d in gallery_designs if _col.key in (_d.get('collections') or []))
            if _n or _col.key in ALWAYS_SHOW:      # music stays visible even when empty, as in the gallery
                design_collections.append({'key': _col.key, 'label': _col.label, 'count': _n})
        _fav = sum(1 for _d in gallery_designs if _d.get('curated_favorite'))
        if _fav:
            design_collections.append({'key': 'fan-favorites', 'label': 'Fan Favorites', 'count': _fav})
    except Exception:
        design_collections = []
    # User's own designs — hidden in group orders so only organizer-approved designs show
    my_designs = []
    if current_user.is_authenticated and not collection_restricted:
        try:
            my_designs = Design.query.filter(
                Design.uploaded_by_user_id == current_user.id,
                Design.is_gallery == False
            ).order_by(Design.uploaded_at.desc()).limit(24).all()
            my_designs = [{'id': d.id, 'url': _resolve_image_url(d.file_path), 'title': (d.title or d.original_filename or 'Design')} for d in my_designs]
        except Exception:
            pass
    
    # Adult items get size upcharge for 2XL+ (youth items do not)
    from utils.print_sizes import classify_age, client_config
    is_adult = classify_age(product) == 'adult'
    transfer_sizing = client_config(product)
    
    from utils.group_orders import is_not_yet_open as _is_not_yet_open, format_schedule_date
    ordering_not_yet_open = bool(coll and _is_not_yet_open(coll))
    collection_opens_label = format_schedule_date(coll.order_opens_at, '%B %-d') if (ordering_not_yet_open and coll) else ''
    if catalog_section == 'uniform':
        garment_metrics_seed = _measure_garment_metrics(color_variants_data, current_app)
    else:
        garment_metrics_seed = _peek_garment_metrics(color_variants_data)
        first = next(
            (variant for variant in color_variants_data if (variant.get('front_image') or '').strip()),
            None,
        )
        # Widen flats were blocked from silhouette measurement, so those
        # styles locked a 50% stand-in and stayed tiny. Measure the first
        # color here so the logo paints at shirt size on the first click.
        if (
            first
            and first['front_image'] not in garment_metrics_seed
            and 'widencdn' in first['front_image']
        ):
            garment_metrics_seed.update(_measure_garment_metrics([first], current_app))
    _stamp_artwork_fits(gallery_designs)
    _stamp_artwork_fits(my_designs)
    if coll and not preset_design and len(gallery_designs) == 1 and gallery_designs[0].get('url'):
        preset_design = gallery_designs[0]
    if preset_design:
        _measure_artwork_fits([preset_design], current_app)
    if preset_back_design:
        _measure_artwork_fits([preset_back_design], current_app)
    age_switch = []
    if coll and catalog_section != 'uniform':
        from utils.group_orders import store_age_family
        from utils.product_filters import age_label
        try:
            age_switch = [
                {
                    'label': age_label(member),
                    'url': url_for('shop.customize', product_slug=member.slug, catalog_section=catalog_section),
                    'active': member.id == product.id,
                }
                for member in store_age_family(coll, product)
            ]
        except Exception:
            current_app.logger.exception('Could not build age switch for product %s', product.id)
            age_switch = []
    return render_template('shop/customize.html',
                         age_switch=age_switch,
                         merged_partner=merged_partner,
                         group_color_key=f'pmkc-group-color-{coll.id}' if coll else '',
                         product=product,
                         available_sizes=available_sizes,
                         available_colors=available_colors,
                         color_variants=color_variants_data,
                         print_area_config=print_area_config,
                         preset_design=preset_design,
                         gallery_designs=gallery_designs,
                         design_collections=design_collections,
                         my_designs=my_designs,
                         customize_back_fonts=([(v, l) for v, l in GROUP_ORDER_FONTS if v in back_fonts_allowed] or CUSTOMIZE_BACK_FONTS),
                         current_user=current_user,
                         collection_restricted=collection_restricted,
                         in_group_order=bool(coll),
                         allow_custom_upload=allow_custom_upload,
                         allowed_placements=allowed_placements,
                         back_design_font=back_design_font,
                         back_fonts_allowed=back_fonts_allowed,
                         back_design_text_color=back_design_text_color,
                         back_design_outline=back_design_outline,
                         back_design_outline_color=back_design_outline_color,
                         lock_back_design_style=lock_back_design_style,
                         back_design_type=back_design_type,
                         allow_back_design=allow_back_design,
                         back_design_name_part=back_design_name_part,
                         allow_stacked_name=allow_stacked_name,
                         allowed_design_ids=allowed_design_ids,
                         is_adult=is_adult,
                         transfer_sizing=transfer_sizing,
                         ordering_not_yet_open=ordering_not_yet_open,
                         collection_opens_label=collection_opens_label,
                         catalog_section=catalog_section,
                         uniform_kit=uniform_kit,
                         uniform_locked_color=uniform_locked_color,
                         uniform_logo_locked=uniform_logo_locked,
                         garment_metrics_seed=garment_metrics_seed,
                         preset_back_design=preset_back_design,
                         edit_line=edit_line,
                         back_options=back_options,
                         fulfillment_note=group_fulfillment_customer_note(coll))
