from flask import Blueprint, render_template, request, jsonify, url_for, session, redirect, flash, current_app
from models import db, Product, Design, Collection
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
from utils.color_names import color_match_key, unique_display_colors, grouped_colors_by_family
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
    try:
        category = canonical_category_param(request.args.get('category'))
        age_group = (request.args.get('age_group') or '').strip().lower() or None
        fit_type = request.args.get('fit_type')
        neck_style = request.args.get('neck_style')
        sleeve_length = request.args.get('sleeve_length')
        color = request.args.get('color')
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

        products = sellable
        if search_q:
            needle = search_q.lower()
            products = [
                p for p in products
                if needle in (p.name or '').lower()
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
        if color:
            wanted = color_match_key(color)
            matching_ids = {
                pid for pid, variants in variants_by_product.items()
                if wanted and any(color_match_key(v.color_name) == wanted for v in variants)
            }
            products = [p for p in products if p.id in matching_ids]

        # Adult → Youth → Toddler → Baby, then garment type within each age
        products = sort_catalog(products)
        product_sections = group_catalog_by_age(products)
        categories = [row['key'] for row in filter_opts['categories']]
        fit_types = filter_opts['fits']
        neck_styles = []
        sleeve_lengths = []
        shop_brands = filter_opts['brands']
        
        design_id = request.args.get('design_id', type=int)

        # Daily affirmation: same message for every visitor on the same calendar date
        daily_affirmation = None
        try:
            from datetime import date
            today = date.today()
            day_index = (today - date(today.year, 1, 1)).days

            # Try DB first (admin-managed list)
            try:
                from models import Affirmation
                db_affirmations = (
                    Affirmation.query
                    .filter_by(is_active=True)
                    .order_by(Affirmation.sort_order, Affirmation.id)
                    .all()
                )
                if db_affirmations:
                    from affirmations_seed import normalize_affirmation_text
                    daily_affirmation = normalize_affirmation_text(
                        db_affirmations[day_index % len(db_affirmations)].text
                    )
            except Exception:
                pass

            # Fallback: use seed list directly if DB had nothing
            if not daily_affirmation:
                from affirmations_seed import AFFIRMATIONS, normalize_affirmation_text
                daily_affirmation = normalize_affirmation_text(
                    AFFIRMATIONS[day_index % len(AFFIRMATIONS)]
                )
        except Exception:
            pass

        return render_template('shop/index.html', 
                             products=products,
                             product_sections=product_sections,
                             categories=categories,
                             fit_types=fit_types,
                             neck_styles=neck_styles,
                             sleeve_lengths=sleeve_lengths,
                             colors=colors,
                             grouped_colors=grouped_colors_by_family(colors),
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
                             categories=[],
                             fit_types=[],
                             neck_styles=[],
                             sleeve_lengths=[],
                             colors=[],
                             grouped_colors=[],
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


@shop_bp.route('/group-orders')
def group_orders():
    """Group order landing page + public directory of open collections"""
    from flask_login import current_user
    from models import Collection
    from utils.group_orders import (
        is_deadline_passed,
        is_not_yet_open,
        publicly_listed_collections,
        visible_store_product_count,
    )

    directory = (
        publicly_listed_collections()
        .order_by(Collection.created_at.desc())
        .all()
    )
    open_collections = []
    for c in directory:
        if is_deadline_passed(c):
            continue
        open_collections.append({
            'collection': c,
            'product_count': visible_store_product_count(c),
            'not_yet_open': is_not_yet_open(c),
        })

    return render_template(
        'shop/group_orders.html',
        is_admin=current_user.is_authenticated and getattr(current_user, 'is_admin', False),
        open_collections=open_collections,
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
                tax_rate=float(current_app.config['KS_SALES_TAX_PERCENT']),
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
            collection.back_design_font = request.form.get('back_design_font') or None
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

            from utils.group_orders import apply_collection_card, apply_schedule_from_form, apply_group_kind, set_collection_products_from_form
            apply_collection_card(collection)
            ok, kind_error = apply_group_kind(collection, required=True)
            if not ok:
                flash(kind_error, 'error')
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
            showcase_ids = resolve_showcase_design_ids(
                allowed_design_ids,
                form_showcase=request.form.getlist('showcase_designs'),
                new_upload_ids=new_upload_ids,
                showcase_new_uploads=request.form.get('showcase_new_uploads') == 'on',
            )
            collection.showcase_design_ids = json.dumps(showcase_ids) if showcase_ids else None
            if upload_count or showcase_ids:
                db.session.commit()

            # ── 7. Verify it saved with a valid, accessible ID ──────────────
            if not collection.id:
                raise SQLAlchemyError('Collection was not assigned an ID after commit')

            msg = 'Group order created successfully'
            if upload_count:
                msg += f' with {upload_count} design(s) uploaded'
            flash(msg + '. Share your link below!', 'success')
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
    catalog = load_group_order_form_catalog()
    return render_template('admin/add_collection.html',
                         products=catalog['products'],
                         gallery_designs=catalog['gallery_designs'],
                         all_colors=catalog.get('colors_by_brand') or catalog['all_colors'],
                         uniform_colors_by_product=catalog['uniform_colors_by_product'],
                         team_store={'configured': True, 'uniform': {'enabled': False}, 'fan_product_ids': []},
                         back_design_fonts=GROUP_ORDER_FONTS,
                         catalog_filter_opts=catalog['catalog_filter_opts'],
                         catalog_filter_picker=True,
                         is_user_create=True)


_GROUP_ORDER_FONTS = GROUP_ORDER_FONTS


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
    from utils.group_orders import allowed_color_form_keys, team_store_config
    allowed_color_keys = allowed_color_form_keys(collection)
    try:
        _raw_colors = json.loads(collection.allowed_colors) if collection.allowed_colors else []
        allowed_colors_list = _raw_colors if isinstance(_raw_colors, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        allowed_colors_list = []
    allowed_design_ids_list = json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    showcase_design_ids_list = json.loads(collection.showcase_design_ids) if getattr(collection, 'showcase_design_ids', None) else []
    allowed_placements_list = json.loads(collection.allowed_placements) if collection.allowed_placements else ['center_chest', 'left_chest', 'right_chest', 'center_back']
    return render_template(
        'shop/edit_group_order.html',
        collection=collection,
        products=catalog['products'],
        gallery_designs=designs_for_group_order_form(collection),
        collection_colors=catalog.get('colors_by_brand') or catalog['all_colors'],
        uniform_colors_by_product=catalog['uniform_colors_by_product'],
        team_store=team_store_config(collection),
        allowed_colors_list=allowed_colors_list,
        allowed_color_keys=allowed_color_keys,
        allowed_design_ids_list=allowed_design_ids_list,
        showcase_design_ids_list=showcase_design_ids_list,
        allowed_placements_list=allowed_placements_list,
        back_design_fonts=_GROUP_ORDER_FONTS,
        collection_product_ids=[p.id for p in collection.products],
        catalog_filter_opts=catalog['catalog_filter_opts'],
        catalog_filter_picker=True,
        is_user_edit=True,
    )


@shop_bp.route('/designs')
def design_gallery():
    """Browse designs by folder, then pick a design (grouped color variants)."""
    from utils.design_categories import GALLERY_CATEGORY_LABELS, normalize_category
    from utils.design_variants import (
        filter_gallery_cards,
        gallery_cards_for_public,
        gallery_folder_cards,
    )
    try:
        all_cards = gallery_cards_for_public(Design, resolve_url=_resolve_image_url)
    except Exception:
        all_cards = []

    product_id = request.args.get('product_id', type=int)
    search_query = (request.args.get('q') or '').strip()
    category = normalize_category(request.args.get('category'))
    folders = gallery_folder_cards(all_cards)

    active_folder = None
    if not all_cards:
        gallery_view = 'empty'
        designs = []
    elif search_query:
        gallery_view = 'search'
        designs = filter_gallery_cards(
            all_cards, category=category or None, query=search_query,
        )
        if category:
            active_folder = next(
                (folder for folder in folders if folder['key'] == category),
                {
                    'key': category,
                    'label': GALLERY_CATEGORY_LABELS.get(category, category),
                    'count': 0,
                    'covers': [],
                },
            )
    elif category:
        gallery_view = 'folder'
        designs = filter_gallery_cards(all_cards, category=category)
        active_folder = next(
            (folder for folder in folders if folder['key'] == category),
            {
                'key': category,
                'label': GALLERY_CATEGORY_LABELS.get(category, category),
                'count': 0,
                'covers': [],
            },
        )
    else:
        gallery_view = 'folders'
        designs = []

    return render_template(
        'shop/design_gallery.html',
        designs=designs,
        folders=folders,
        gallery_view=gallery_view,
        active_folder=active_folder,
        search_query=search_query,
        product_id=product_id,
    )


def _require_sellable_product(product):
    """Products without a photo stay in the catalog but cannot be sold."""
    if product and product.is_active and product_has_shop_image(product, current_app):
        return None
    flash('This product is not available to order yet.', 'error')
    return redirect(url_for('shop.index'))


@shop_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    """Product detail page with customizer"""
    product = Product.query.get_or_404(product_id)
    blocked = _require_sellable_product(product)
    if blocked:
        return blocked
    product.display_brand = infer_brand(product)
    available_sizes = shop_sizes_for_product(product)
    available_colors = parse_json_list(product.available_colors)
    print_area_config = parse_json_object(product.print_area_config)
    color_variants_data = get_color_variants_data_for_product(product, current_app)
    return render_template('shop/product_detail.html',
                         product=product,
                         available_sizes=available_sizes,
                         available_colors=available_colors,
                         color_variants=color_variants_data,
                         print_area_config=print_area_config)


@shop_bp.route('/customize/<int:product_id>')
def customize(product_id):
    """Product customizer interface"""
    from flask_login import current_user
    from utils.group_orders import (
        allowed_colors_for_product,
        allowed_design_ids as collection_design_id_list,
        collection_has_color_restrictions,
        get_active_collection,
        load_collection_designs,
        load_design_dict,
        ordering_blocked,
        resolve_uniform_design_id,
        team_store_config,
        team_store_choice,
    )

    product = Product.query.get_or_404(product_id)
    blocked = _require_sellable_product(product)
    if blocked:
        return blocked
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
    back_design_text_color = None
    back_design_outline = None   # None = use customer's choice
    back_design_outline_color = None
    lock_back_design_style = False
    allowed_design_ids = None
    back_design_type = 'both'   # 'none' | 'name_number' | 'image' | 'both'
    allow_back_design = True
    back_design_name_part = 'last'
    catalog_section = None
    uniform_kit = None
    uniform_locked_color = None
    uniform_logo_locked = False
    coll = get_active_collection()
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
            allowed_design_ids = set(collection_design_id_list(coll))
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
    
    # Check for pre-selected design from gallery
    design_id = request.args.get('design_id', type=int)
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
    
    # Gallery designs for inline "choose logo" section (mains + color variants)
    gallery_designs = []
    try:
        if coll:
            # Group orders only offer artwork uploaded/approved for that
            # specific store. Never fall back to the general design gallery.
            if uniform_logo_locked:
                gallery_designs = []
            else:
                gallery_designs = (
                    load_collection_designs(coll) if allowed_design_ids else []
                )
        else:
            from utils.design_variants import gallery_cards_for_public
            gallery_designs = gallery_cards_for_public(
                Design, resolve_url=_resolve_image_url, limit=200
            )
    except Exception:
        pass
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
    if preset_design:
        _measure_artwork_fits([preset_design], current_app)
    return render_template('shop/customize.html',
                         product=product,
                         available_sizes=available_sizes,
                         available_colors=available_colors,
                         color_variants=color_variants_data,
                         print_area_config=print_area_config,
                         preset_design=preset_design,
                         gallery_designs=gallery_designs,
                         my_designs=my_designs,
                         customize_back_fonts=CUSTOMIZE_BACK_FONTS,
                         current_user=current_user,
                         collection_restricted=collection_restricted,
                         in_group_order=bool(coll),
                         allow_custom_upload=allow_custom_upload,
                         allowed_placements=allowed_placements,
                         back_design_font=back_design_font,
                         back_design_text_color=back_design_text_color,
                         back_design_outline=back_design_outline,
                         back_design_outline_color=back_design_outline_color,
                         lock_back_design_style=lock_back_design_style,
                         back_design_type=back_design_type,
                         allow_back_design=allow_back_design,
                         back_design_name_part=back_design_name_part,
                         allowed_design_ids=allowed_design_ids,
                         is_adult=is_adult,
                         transfer_sizing=transfer_sizing,
                         ordering_not_yet_open=ordering_not_yet_open,
                         collection_opens_label=collection_opens_label,
                         catalog_section=catalog_section,
                         uniform_kit=uniform_kit,
                         uniform_locked_color=uniform_locked_color,
                         uniform_logo_locked=uniform_logo_locked,
                         garment_metrics_seed=garment_metrics_seed)
