from flask import Blueprint, render_template, request, jsonify, url_for, session, redirect, flash, current_app
from models import db, Product, Design, Collection
from flask_login import login_required, current_user
from utils.mockups import get_carousel_colors_for_product, get_color_variants_data_for_product, get_first_shop_image_url
from utils.cloud_storage import image_url as _resolve_image_url
from utils.json_fields import parse_json_list, parse_json_object
from utils.product_filters import (
    canonical_category_param,
    catalog_filter_options,
    infer_age,
    infer_category,
    infer_fit,
    matches_filters,
    prepare_catalog,
)
from utils.sizes import sort_sizes
import json

shop_bp = Blueprint('shop', __name__, url_prefix='/shop')

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

        query = Product.query.filter_by(is_active=True)

        if search_q:
            _kw = f'%{search_q}%'
            query = query.filter(
                db.or_(
                    Product.name.ilike(_kw),
                    Product.style_number.ilike(_kw),
                    Product.description.ilike(_kw),
                    Product.category.ilike(_kw),
                    Product.brand.ilike(_kw),
                )
            )
        
        products = query.order_by(Product.style_number).all()
        products = [
            p for p in products
            if matches_filters(p, age_group=age_group, category=category, fit_type=fit_type)
        ]
        if brand:
            wanted = ''.join(ch for ch in brand.lower() if ch.isalnum())
            products = [
                p for p in products
                if wanted and wanted in ''.join(ch for ch in (p.brand or '').lower() if ch.isalnum())
            ]

        if color:
            from models import ProductColorVariant
            wanted = color.strip().lower()
            product_ids = [
                pid for (pid,) in db.session.query(ProductColorVariant.product_id).filter(
                    db.func.lower(ProductColorVariant.color_name) == wanted
                ).distinct().all()
            ]
            products = [p for p in products if p.id in product_ids]

        for product in products:
            product.carousel_colors = get_carousel_colors_for_product(product, current_app)
            product.fallback_image_url = get_first_shop_image_url(product, current_app)
            product.display_category = infer_category(product)
            product.display_age = infer_age(product)
            product.display_fit = infer_fit(product)
        
        categories = db.session.query(Product.category).filter(
            Product.is_active == True
        ).distinct().order_by(Product.category).all()
        categories = [c[0] for c in categories if c[0]]
        
        fit_types = db.session.query(Product.fit_type).filter(
            Product.is_active == True, Product.fit_type != None
        ).distinct().order_by(Product.fit_type).all()
        fit_types = [f[0] for f in fit_types if f[0]]
        
        neck_styles = db.session.query(Product.neck_style).filter(
            Product.is_active == True, Product.neck_style != None
        ).distinct().order_by(Product.neck_style).all()
        neck_styles = [n[0] for n in neck_styles if n[0]]
        
        sleeve_lengths = db.session.query(Product.sleeve_length).filter(
            Product.is_active == True, Product.sleeve_length != None
        ).distinct().order_by(Product.sleeve_length).all()
        sleeve_lengths = [s[0] for s in sleeve_lengths if s[0]]
        
        from models import ProductColorVariant
        colors = db.session.query(ProductColorVariant.color_name).distinct().order_by(ProductColorVariant.color_name).all()
        colors = [c[0] for c in colors if c[0]]
        # Deduplicate case-insensitively (e.g. "DTG Black" and "Dtg Black" → one entry)
        _seen = set()
        colors = [c for c in colors if not (c.lower() in _seen or _seen.add(c.lower()))]
        
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
                    daily_affirmation = db_affirmations[day_index % len(db_affirmations)].text
            except Exception:
                pass

            # Fallback: use seed list directly if DB had nothing
            if not daily_affirmation:
                from affirmations_seed import AFFIRMATIONS
                daily_affirmation = AFFIRMATIONS[day_index % len(AFFIRMATIONS)]
        except Exception:
            pass

        from services.sanmar_catalog import shop_brand_names
        shop_brands = shop_brand_names()
        db_brands = [
            row[0] for row in db.session.query(Product.brand)
            .filter(Product.is_active == True, Product.brand.isnot(None))
            .distinct().all()
            if row[0]
        ]
        for extra in db_brands:
            if extra not in shop_brands:
                shop_brands.append(extra)

        return render_template('shop/index.html', 
                             products=products,
                             categories=categories,
                             fit_types=fit_types,
                             neck_styles=neck_styles,
                             sleeve_lengths=sleeve_lengths,
                             colors=colors,
                             shop_brands=shop_brands,
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
                             categories=[],
                             fit_types=[],
                             neck_styles=[],
                             sleeve_lengths=[],
                             colors=[],
                             shop_brands=[],
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
    """Group order landing page - teams, schools, organizations"""
    from flask_login import current_user
    return render_template('shop/group_orders.html', is_admin=current_user.is_authenticated and getattr(current_user, 'is_admin', False))


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

            # ── 3. Parse + validate optional settings with specific errors ──
            try:
                tax_rate = float(request.form.get('tax_rate') or 0)
            except (TypeError, ValueError):
                flash('Tax rate must be a number (e.g. 8.5). Please correct it and try again.', 'error')
                return redirect(url_for('shop.create_group_order'))

            order_deadline = None
            deadline_str = (request.form.get('order_deadline') or '').strip()
            if deadline_str:
                try:
                    from utils.group_orders import parse_order_deadline
                    order_deadline = parse_order_deadline(deadline_str)
                except ValueError:
                    flash('The order deadline date is invalid. Please pick a valid date.', 'error')
                    return redirect(url_for('shop.create_group_order'))

            # ── 4. Create the collection ────────────────────────────────────
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
                tax_rate=tax_rate,
            )
            collection.restrict_options = request.form.get('restrict_options') == 'on'
            collection.allow_custom_upload = True
            allowed_colors = request.form.getlist('allowed_colors')
            collection.allowed_colors = json.dumps(allowed_colors) if allowed_colors else None
            allowed_placements = request.form.getlist('allowed_placements')
            collection.allowed_placements = json.dumps(allowed_placements) if allowed_placements else None

            # Collect chosen gallery / own designs + any newly uploaded artwork
            from utils.privacy import selectable_group_order_design_ids
            allowed_design_ids = selectable_group_order_design_ids(
                request.form.getlist('allowed_designs'), current_user
            )
            upload_count = 0
            for f in request.files.getlist('design_uploads'):
                if f and f.filename:
                    try:
                        design = _save_collection_design(f, current_user.id)
                    except Exception as e:
                        current_app.logger.exception('Group order artwork upload failed: %s', e)
                        design = None
                    if design:
                        allowed_design_ids.append(design.id)
                        upload_count += 1
            if allowed_design_ids:
                collection.allowed_design_ids = json.dumps(allowed_design_ids)
            if allowed_design_ids or allowed_colors:
                collection.restrict_options = True
            collection.back_design_font = request.form.get('back_design_font') or None
            # Uniform back-design style controls
            collection.back_design_text_color = request.form.get('back_design_text_color') or None
            collection.back_design_outline = request.form.get('back_design_outline') != 'off'
            collection.back_design_outline_color = request.form.get('back_design_outline_color') or None
            collection.lock_back_design_style = request.form.get('lock_back_design_style') == 'on'

            password = request.form.get('password')
            if password:
                collection.set_password(password)
            if order_deadline:
                collection.order_deadline = order_deadline

            # Track who created this group order (for permission checks)
            collection.created_by_user_id = current_user.id

            db.session.add(collection)
            db.session.flush()

            # ── 5. Link selected products ───────────────────────────────────
            selected_products = []
            for product_id in request.form.getlist('products'):
                try:
                    pid = int(product_id)
                except (TypeError, ValueError):
                    continue
                product = Product.query.get(pid)
                if product:
                    selected_products.append(product)
                    collection.products.append(product)
            if not selected_products:
                db.session.rollback()
                flash('Please pick at least one shirt style so your team has something to order.', 'error')
                return redirect(url_for('shop.create_group_order'))

            # ── 6. Commit ───────────────────────────────────────────────────
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
    back_design_fonts = [
        ('Freshman', 'Freshman — Classic college jersey'),
        ('Black Ops One', 'Black Ops One — Bold varsity block'),
        ('Graduate', 'Graduate — Collegiate style'),
        ('Squada One', 'Squada One — Modern athletic numbers'),
        ('Bebas Neue', 'Bebas Neue — Clean jersey'),
        ('Oswald', 'Oswald — Bold athletic'),
        ('Anton', 'Anton — Strong block'),
        ('Teko', 'Teko — College jersey'),
        ('Jersey M54', 'Jersey M54 — Classic sports jersey'),
    ]
    return render_template('admin/add_collection.html',
                         products=catalog['products'],
                         gallery_designs=catalog['gallery_designs'],
                         all_colors=catalog['all_colors'],
                         back_design_fonts=back_design_fonts,
                         catalog_filter_opts=catalog['catalog_filter_opts'],
                         catalog_filter_picker=True,
                         is_user_create=True)


_GROUP_ORDER_FONTS = [
    ('Freshman', 'Freshman — Classic college jersey'),
    ('Black Ops One', 'Black Ops One — Bold varsity block'),
    ('Graduate', 'Graduate — Collegiate style'),
    ('Squada One', 'Squada One — Modern athletic numbers'),
    ('Bebas Neue', 'Bebas Neue — Clean jersey'),
    ('Oswald', 'Oswald — Bold athletic'),
    ('Anton', 'Anton — Strong block'),
    ('Teko', 'Teko — College jersey'),
    ('Jersey M54', 'Jersey M54 — Classic sports jersey'),
]


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
    allowed_colors_list = json.loads(collection.allowed_colors) if collection.allowed_colors else []
    allowed_design_ids_list = json.loads(collection.allowed_design_ids) if collection.allowed_design_ids else []
    allowed_placements_list = json.loads(collection.allowed_placements) if collection.allowed_placements else ['center_chest', 'left_chest', 'right_chest', 'center_back']
    return render_template(
        'shop/edit_group_order.html',
        collection=collection,
        products=catalog['products'],
        gallery_designs=designs_for_group_order_form(collection),
        collection_colors=catalog['all_colors'],
        allowed_colors_list=allowed_colors_list,
        allowed_design_ids_list=allowed_design_ids_list,
        allowed_placements_list=allowed_placements_list,
        back_design_fonts=_GROUP_ORDER_FONTS,
        collection_product_ids=[p.id for p in collection.products],
        catalog_filter_opts=catalog['catalog_filter_opts'],
        catalog_filter_picker=True,
        is_user_edit=True,
    )


@shop_bp.route('/designs')
def design_gallery():
    """Browse designs available for custom apparel"""
    try:
        designs = Design.query.filter_by(is_gallery=True).order_by(Design.uploaded_at.desc()).all()
    except Exception:
        designs = []
    product_id = request.args.get('product_id', type=int)
    return render_template('shop/design_gallery.html', designs=designs, product_id=product_id)


@shop_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    """Product detail page with customizer"""
    product = Product.query.get_or_404(product_id)
    available_sizes = sort_sizes(parse_json_list(product.available_sizes))
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
        allowed_design_ids as collection_design_id_list,
        get_active_collection,
        load_collection_designs,
        ordering_blocked,
    )

    product = Product.query.get_or_404(product_id)
    available_sizes = sort_sizes(parse_json_list(product.available_sizes))
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
    coll = get_active_collection()
    if coll:
        blocked = ordering_blocked(coll, product.id)
        if blocked:
            flash(blocked, 'error')
            return redirect(url_for('collection.view', slug=coll.slug))
        has_colors = bool(parse_json_list(coll.allowed_colors or ''))
        has_designs = bool(collection_design_id_list(coll))
        has_placements = bool(parse_json_list(coll.allowed_placements or ''))
        collection_restricted = bool(coll.restrict_options or has_colors or has_designs)
        allow_custom_upload = getattr(coll, 'allow_custom_upload', True)
        back_design_font = getattr(coll, 'back_design_font', None)
        back_design_text_color = getattr(coll, 'back_design_text_color', None)
        _outline = getattr(coll, 'back_design_outline', None)
        back_design_outline = _outline if _outline is not None else True
        back_design_outline_color = getattr(coll, 'back_design_outline_color', None)
        lock_back_design_style = bool(getattr(coll, 'lock_back_design_style', False))
        if has_colors:
            allowed = parse_json_list(coll.allowed_colors)
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
    
    # Check for pre-selected design from gallery
    design_id = request.args.get('design_id', type=int)
    preset_design = None
    if design_id:
        from utils.privacy import user_can_use_design
        d = Design.query.get(design_id)
        if d and user_can_use_design(d, collection=coll):
            preset_design = {
                'id': d.id,
                'url': _resolve_image_url(d.file_path),
                'title': (d.title or d.original_filename or 'Design')
            }
    
    # Gallery designs for inline "choose logo" section
    gallery_designs = []
    try:
        if coll and allowed_design_ids:
            gallery_designs = load_collection_designs(coll)
        else:
            designs = Design.query.filter_by(is_gallery=True).order_by(Design.uploaded_at.desc()).limit(24).all()
            gallery_designs = [{'id': d.id, 'url': _resolve_image_url(d.file_path), 'title': (d.title or d.original_filename or 'Design')} for d in designs]
    except Exception:
        pass
    if not preset_design and gallery_designs and len(gallery_designs) == 1:
        preset_design = gallery_designs[0]
    
    # User's own designs (profile-only, for logged-in users) — skip when the organizer locked logos
    my_designs = []
    if current_user.is_authenticated and not (collection_restricted and allowed_design_ids and not allow_custom_upload):
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
    
    return render_template('shop/customize.html',
                         product=product,
                         available_sizes=available_sizes,
                         available_colors=available_colors,
                         color_variants=color_variants_data,
                         print_area_config=print_area_config,
                         preset_design=preset_design,
                         gallery_designs=gallery_designs,
                         my_designs=my_designs,
                         current_user=current_user,
                         collection_restricted=collection_restricted,
                         allow_custom_upload=allow_custom_upload,
                         allowed_placements=allowed_placements,
                         back_design_font=back_design_font,
                         back_design_text_color=back_design_text_color,
                         back_design_outline=back_design_outline,
                         back_design_outline_color=back_design_outline_color,
                         lock_back_design_style=lock_back_design_style,
                         allowed_design_ids=allowed_design_ids,
                         is_adult=is_adult,
                         transfer_sizing=transfer_sizing)
