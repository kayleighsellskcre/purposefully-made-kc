"""Admin Products: the product list, add and edit, colors, images, sync and bulk actions.

Split out of routes/admin.py. Everything here is still on the admin blueprint, so every URL and every
url_for('admin.something') name is exactly as before (see the import at the bottom of routes/admin.py).
"""
import json

from flask import render_template, request, redirect, url_for, flash, current_app
from models import db, Product, ProductColorVariant

from routes.admin import _form_money, admin_bp, admin_required  # noqa: E402


# ===== PRODUCTS =====

@admin_bp.route('/products')
@admin_required
def products():
    """Manage products"""
    try:
        import os
        # Optional filter/sort by Customer Favorite status
        fav_filter = request.args.get('favorites') == '1'
        query = Product.query
        if fav_filter:
            query = query.filter(Product.is_customer_favorite.is_(True))
        # Always surface favorites first, then by style number
        products = query.order_by(Product.is_customer_favorite.desc(),
                                  Product.style_number).all()
        favorite_count = Product.query.filter(Product.is_customer_favorite.is_(True)).count()

        # Size/color counts + lightest-color thumbnail in one variant pass
        from collections import defaultdict
        from utils.mockups import sorted_front_mockup_urls, get_first_shop_image_url, get_carousel_colors_for_product

        variants_by_pid = defaultdict(list)
        if products:
            for variant in ProductColorVariant.query.filter(
                ProductColorVariant.product_id.in_([p.id for p in products])
            ).all():
                variants_by_pid[variant.product_id].append(variant)

        for p in products:
            try:
                p.size_count = len(json.loads(p.available_sizes)) if p.available_sizes else 0
            except (TypeError, ValueError):
                p.size_count = 0
            variants = variants_by_pid.get(p.id, [])
            variant_count = len(variants)
            try:
                parsed = json.loads(p.available_colors) if p.available_colors else []
                json_count = len(parsed) if isinstance(parsed, list) else 0
            except (TypeError, ValueError):
                json_count = 0
            p.color_count = variant_count if variant_count > 0 else min(json_count, 200)
            # Build ordered fallback list: local files first (guaranteed to exist),
            # then DB/CDN urls (may 404), then template url
            local_url = get_first_shop_image_url(p, current_app, carousel=get_carousel_colors_for_product(p, current_app, variants=variants))
            db_urls = sorted_front_mockup_urls(variants)
            seen = set()
            all_urls = []
            for u in ([local_url] if local_url else []) + db_urls:
                if u and u not in seen:
                    seen.add(u)
                    all_urls.append(u)
            template_url = (p.front_mockup_template or '').strip()
            if template_url and template_url not in seen:
                all_urls.append(template_url)
            p.thumb_url = all_urls[0] if all_urls else None
            p.thumb_fallbacks = all_urls[1:]  # remaining URLs for JS cascade

        # Check if S&S API is configured - check environment variable directly
        api_key = os.getenv('SSACTIVEWEAR_API_KEY')
        api_configured = bool(api_key) and api_key != 'your_ss_activewear_api_key_here'
        
        # Get last sync time
        last_sync = ProductColorVariant.query.order_by(ProductColorVariant.last_synced.desc()).first()
        last_sync_time = last_sync.last_synced if last_sync else None
        try:
            from datetime import datetime as _dt
            from services.color_availability import SYNC_OK_KEY
            from utils.site_settings import get_setting
            last_sync_time = _dt.fromisoformat(get_setting(SYNC_OK_KEY, '')) or last_sync_time
        except (TypeError, ValueError):
            pass  # no supplier stock sync recorded yet: fall back to the newest color row

        return render_template('admin/products.html',
                             products=products,
                             api_configured=api_configured,
                             last_sync_time=last_sync_time,
                             fav_filter=fav_filter,
                             favorite_count=favorite_count)
    
    except Exception as e:
        # Comprehensive error handling for admin products page
        import sys
        import traceback
        print(f"ERROR in admin products: {e}", file=sys.stderr)
        traceback.print_exc()
        
        # Try to determine if it's a schema issue
        error_msg = str(e).lower()
        if 'no such column' in error_msg or 'column' in error_msg and 'does not exist' in error_msg:
            flash('Database schema is updating. Please wait 30 seconds and refresh the page.', 'warning')
        else:
            flash(f'Error loading products page: {str(e)}', 'error')
        
        # Return empty page with API configured check
        import os
        api_key = os.getenv('SSACTIVEWEAR_API_KEY')
        api_configured = bool(api_key) and api_key != 'your_ss_activewear_api_key_here'
        
        return render_template('admin/products.html',
                             products=[],
                             api_configured=api_configured,
                             last_sync_time=None)


@admin_bp.route('/products/fetch-ss-images', methods=['POST'])
@admin_required
def fetch_ss_images():
    """
    Get Product Images — two-phase:
      Phase 1: S&S Activewear API — create/update color variants with ghost images
      Phase 2: Local static/sanmar/ files — link any already-on-disk images
    Phase 2 always runs, even if Phase 1 fails or S&S is unavailable.
    """
    import os, re
    pass
    from pathlib import Path
    from models import db, Product, ProductColorVariant

    api_key = os.getenv('SSACTIVEWEAR_API_KEY', '').strip()
    account_number = os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER', '').strip()

    # ── Shared state ───────────────────────────────────────────────────────────
    created_variants = 0
    updated_variants = 0
    updated_products = 0
    skipped = 0
    local_linked = 0
    errors = []
    ss_status = ''

    # ── Phase 1: Local static/sanmar/ images (fast, synchronous) ──────────────
    try:
        sanmar_dir = Path(current_app.root_path) / 'static' / 'sanmar'
        if sanmar_dir.is_dir():
            for style_folder in sanmar_dir.iterdir():
                if not style_folder.is_dir():
                    continue
                folder_name = style_folder.name
                bc_style    = 'BC' + folder_name
                cc_style    = 'CC' + folder_name
                product = Product.query.filter(
                    db.or_(
                        Product.style_number == bc_style,
                        Product.style_number == cc_style,
                        Product.style_number == folder_name,
                    )
                ).first()
                if not product:
                    continue

                file_map: dict = {}
                for f in style_folder.iterdir():
                    if not f.is_file():
                        continue
                    m = re.match(rf'^{re.escape(folder_name)}_(.+?)_(front|back)\.jpe?g$', f.name, re.IGNORECASE)
                    if not m:
                        continue
                    key = m.group(1).replace('_', ' ').lower()
                    side = m.group(2).lower()
                    if key not in file_map:
                        file_map[key] = {}
                    file_map[key][side] = f'/static/sanmar/{folder_name}/{f.name}'

                existing = {
                    (v.color_name or '').lower(): v
                    for v in ProductColorVariant.query.filter_by(product_id=product.id).all()
                }

                for color_key, paths in file_map.items():
                    color_name_display = color_key.title()
                    if color_key in existing:
                        v = existing[color_key]
                        changed = False
                        if not v.front_image_url and paths.get('front'):
                            v.front_image_url = paths['front']; changed = True
                        if not v.back_image_url and paths.get('back'):
                            v.back_image_url = paths['back']; changed = True
                        if changed:
                            local_linked += 1
                    else:
                        db.session.add(ProductColorVariant(
                            product_id=product.id,
                            color_name=color_name_display,
                            front_image_url=paths.get('front'),
                            back_image_url=paths.get('back'),
                        ))
                        local_linked += 1

                if not product.front_mockup_template and file_map:
                    ff = next((v['front'] for v in file_map.values() if 'front' in v), None)
                    if ff: product.front_mockup_template = ff
                if not product.back_mockup_template and file_map:
                    fb = next((v['back'] for v in file_map.values() if 'back' in v), None)
                    if fb: product.back_mockup_template = fb

            db.session.commit()
    except Exception as e:
        db.session.rollback()
        errors.append(f'Local link error: {e}')

    # ── Phase 2: S&S Activewear API in background thread (no 30s timeout) ─────
    if api_key and account_number:
        import threading
        app_ref = current_app._get_current_object()

        def _fetch_ss_background():
            import sys
            from datetime import datetime as _dt
            with app_ref.app_context():
                try:
                    from services.ssactivewear_api import SSActivewearAPI
                    from models import db as _db, Product as _P, ProductColorVariant as _PCV
                    _api = SSActivewearAPI(api_key=api_key, account_number=account_number)
                    cdn = 'https://cdn.ssactivewear.com/'

                    def _img(url):
                        if not url: return None
                        return url if url.startswith('http') else cdn + url.lstrip('/')

                    for product in _P.query.filter(_P.style_number.ilike('BC%')).all():
                        ss_style = product.style_number[2:] if product.style_number.upper().startswith('BC') else product.style_number
                        try:
                            ss_rows = _api.get_products_by_style_number(ss_style) or _api.get_products_by_style_number(product.style_number)
                            if not ss_rows:
                                continue

                            color_map: dict = {}
                            for row in ss_rows:
                                cname = (row.get('colorName') or '').strip()
                                if not cname: continue
                                k = cname.lower()
                                if k in color_map: continue
                                front = _img(row.get('ghostFrontImage') or row.get('colorFrontImage') or row.get('frontImage'))
                                back  = _img(row.get('ghostBackImage')  or row.get('colorBackImage')  or row.get('backImage'))
                                if front or back:
                                    color_map[k] = {'name': cname, 'front': front, 'back': back,
                                                    'hex': row.get('colorHex') or row.get('hex')}
                            if not color_map:
                                continue

                            existing = {(v.color_name or '').lower(): v for v in _PCV.query.filter_by(product_id=product.id).all()}
                            changed = False
                            for k, imgs in color_map.items():
                                if k in existing:
                                    v = existing[k]
                                    if imgs['front'] and not v.front_image_url:
                                        v.front_image_url = imgs['front']; changed = True
                                    if imgs['back'] and not v.back_image_url:
                                        v.back_image_url = imgs['back']; changed = True
                                else:
                                    _db.session.add(_PCV(
                                        product_id=product.id,
                                        color_name=imgs['name'], color_hex=imgs.get('hex'),
                                        front_image_url=imgs['front'], back_image_url=imgs['back'],
                                        last_synced=_dt.utcnow(),
                                    ))
                                    changed = True

                            if changed:
                                if not product.front_mockup_template:
                                    ff = next((v['front'] for v in color_map.values() if v.get('front')), None)
                                    if ff: product.front_mockup_template = ff
                                _db.session.commit()

                        except Exception as e:
                            _db.session.rollback()
                            print(f'SS bg [{product.style_number}]: {e}', file=sys.stderr)

                    print('SS background image fetch complete.', file=sys.stderr)
                except Exception as e:
                    print(f'SS background fetch failed: {e}', file=sys.stderr)

        threading.Thread(target=_fetch_ss_background, daemon=True).start()
        ss_msg = ' S&S images are fetching in the background for all other styles — they\'ll appear within a few minutes.'
    else:
        ss_msg = ''

    # ── Flash ──────────────────────────────────────────────────────────────────
    msg = f'Done! Created/linked {local_linked} color variants from your uploaded images.' if local_linked else 'Local images processed.'
    msg += ss_msg
    if errors:
        msg += f' Errors: {", ".join(errors[:3])}'
    flash(msg, 'success' if not errors else 'warning')

    return redirect(url_for('admin.products'))


@admin_bp.route('/products/sync-sanmar-inventory', methods=['POST'])
@admin_required
def sync_sanmar_inventory():
    """Sync live warehouse quantities from SanMar and S&S into every active style."""
    from services.inventory_sync import start_inventory_sync_thread

    start_inventory_sync_thread(current_app._get_current_object())
    flash(
        'Live inventory sync started for SanMar and S&S. '
        'In-stock / out-of-stock quantities will refresh over the next few minutes.',
        'success',
    )
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/fill-size-charts', methods=['POST'])
@admin_required
def fill_size_charts():
    """Fill each product's own size chart from the manufacturer's measurements. Never replaces a chart already there."""
    from utils.size_charts import start_fill_thread

    start_fill_thread(current_app._get_current_object())
    flash('Filling in size charts from the manufacturer measurements. Styles that already have a chart are left alone. '
          'A note will appear in your inbox in a minute or two with the result.', 'success')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/import-bella-canvas-csv', methods=['POST'])
@admin_required
def import_bella_canvas_csv():
    """Import products from a BellaCanvas SDL CSV file upload."""
    import sys
    from services.bella_canvas_csv import parse_csv
    from models import ProductColorVariant
    from datetime import datetime

    uploaded = request.files.get('csv_file')
    if not uploaded or not uploaded.filename:
        flash('No file selected. Please choose a CSV file to upload.', 'error')
        return redirect(url_for('admin.products'))

    if not uploaded.filename.lower().endswith('.csv'):
        flash('Please upload a .csv file (the BellaCanvasData file from SanMar).', 'error')
        return redirect(url_for('admin.products'))

    try:
        products_data = parse_csv(uploaded)
    except Exception as exc:
        flash(f'Could not parse CSV: {exc}', 'error')
        return redirect(url_for('admin.products'))

    if not products_data:
        flash('No products found in the CSV file.', 'warning')
        return redirect(url_for('admin.products'))

    from models import Product, db
    added = updated = variants_added = variants_updated = 0

    for product_data in products_data:
        color_variants_data = product_data.pop('color_variants', [])
        style_num = product_data.get('style_number', '')
        if not style_num:
            continue

        # Match existing products whether they were stored with or without the BC prefix.
        # e.g. CSV style "BC3001C" should update the old S&S product stored as "3001C".
        style_no_prefix = style_num.lstrip('BC').lstrip('bc') if style_num.upper().startswith('BC') else style_num
        existing = (
            Product.query.filter_by(style_number=style_num).first()
            or Product.query.filter_by(style_number=style_no_prefix).first()
        )

        if existing:
            for key, value in product_data.items():
                # Never overwrite admin-set price
                if key == 'base_price':
                    continue
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            existing.is_active = product_data.get('is_active', True)
            product = existing
            updated += 1
        else:
            product = Product(**product_data)
            db.session.add(product)
            db.session.flush()
            added += 1

        for cv_data in color_variants_data:
            color_name = cv_data.get('color_name', '')
            if not color_name:
                continue
            existing_cv = ProductColorVariant.query.filter_by(
                product_id=product.id, color_name=color_name
            ).first()
            if existing_cv:
                if cv_data.get('front_image_url'):
                    existing_cv.front_image_url = cv_data['front_image_url']
                if cv_data.get('back_image_url'):
                    existing_cv.back_image_url = cv_data['back_image_url']
                if cv_data.get('color_swatch_url'):
                    existing_cv.color_swatch_url = cv_data['color_swatch_url']
                existing_cv.last_synced = datetime.utcnow()
                variants_updated += 1
            else:
                new_cv = ProductColorVariant(
                    product_id=product.id,
                    color_name=color_name,
                    front_image_url=cv_data.get('front_image_url', ''),
                    back_image_url=cv_data.get('back_image_url', ''),
                    color_swatch_url=cv_data.get('color_swatch_url', ''),
                    size_inventory=json.dumps({}),
                )
                db.session.add(new_cv)
                variants_added += 1

    db.session.commit()

    flash(
        f'CSV import complete: {added} new products, {updated} updated, '
        f'{variants_added} new color variants, {variants_updated} updated.',
        'success'
    )
    print(
        f'[CSV Import] {added} added, {updated} updated, '
        f'{variants_added} variants added, {variants_updated} variants updated.',
        file=sys.stderr, flush=True,
    )
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/add', methods=['GET', 'POST'])
@admin_required
def add_product():
    """Add new product"""
    if request.method == 'POST':
        from utils.json_fields import store_json_list
        base_price = _form_money('base_price')
        if base_price is None or base_price < 0:
            flash('Enter a base price (a number, 0 or higher) before saving.', 'error')
            return render_template('admin/add_product.html')
        product = Product(
            style_number=request.form.get('style_number'),
            name=request.form.get('name'),
            category=request.form.get('category'),
            description=request.form.get('description'),
            base_price=base_price,
            wholesale_cost=_form_money('wholesale_cost', 0.0),
            is_active=False,
            is_customer_favorite=request.form.get('is_customer_favorite') == 'on',
            available_sizes=store_json_list(request.form.get('available_sizes')),
            available_colors=store_json_list(request.form.get('available_colors')),
            print_area_config=request.form.get('print_area_config')
        )
        
        db.session.add(product)
        db.session.commit()

        if request.form.get('is_active') == 'on':
            flash('Product added. Add a product photo before making this active.', 'error')
        else:
            flash('Product added successfully', 'success')
        return redirect(url_for('admin.products'))
    
    return render_template('admin/add_product.html')


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    """Edit product"""
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        from werkzeug.utils import secure_filename
        pass

        # Validate the price before touching the row, so a bad value cannot
        # leave the product half-updated.
        base_price = _form_money('base_price')
        if base_price is None or base_price < 0:
            flash('Enter a base price (a number, 0 or higher) before saving.', 'error')
            return render_template('admin/edit_product.html', product=product)

        product.style_number = request.form.get('style_number')
        product.name = request.form.get('name')
        product.brand = request.form.get('brand')
        product.category = request.form.get('category')
        product.age_group = request.form.get('age_group')
        product.fit_type = request.form.get('fit_type')
        product.neck_style = request.form.get('neck_style')
        product.sleeve_length = request.form.get('sleeve_length')
        product.family_key = request.form.get('family_key', '').strip() or None
        product.description = request.form.get('description')
        product.base_price = base_price
        product.wholesale_cost = _form_money('wholesale_cost', 0.0)
        want_active = request.form.get('is_active') == 'on'
        product.is_customer_favorite = request.form.get('is_customer_favorite') == 'on'
        from utils.json_fields import store_json_list
        product.available_sizes = store_json_list(request.form.get('available_sizes'))
        product.available_colors = store_json_list(request.form.get('available_colors'))
        product.print_area_config = request.form.get('print_area_config')
        
        # Sizing and fabric details
        product.fit_guide = request.form.get('fit_guide')
        product.fabric_details = request.form.get('fabric_details')
        
        # Handle front image upload
        if 'front_image' in request.files:
            front_file = request.files['front_image']
            if front_file and front_file.filename:
                from utils.cloud_storage import store_upload
                product.front_mockup_template = store_upload(
                    front_file, 'products', secure_filename(f"{product.style_number}_front"))
        
        # Handle back image upload
        if 'back_image' in request.files:
            back_file = request.files['back_image']
            if back_file and back_file.filename:
                from utils.cloud_storage import store_upload
                product.back_mockup_template = store_upload(
                    back_file, 'products', secure_filename(f"{product.style_number}_back"))

        from utils.mockups import product_has_shop_image
        if want_active and not product_has_shop_image(product):
            product.is_active = False
            flash('Add a product photo before making this active.', 'error')
        else:
            product.is_active = want_active
        
        db.session.commit()
        flash('Product updated successfully', 'success')
        return redirect(url_for('admin.products'))
    
    return render_template('admin/edit_product.html', product=product)


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product(product_id):
    """Remove a product from the catalog.

    OrderItem.product_id is a non-nullable foreign key, so a style that
    appears in any past order cannot be removed without leaving that order
    pointing at nothing. Those are hidden from the shop instead. Styles
    nobody has ever bought — the unbuyable ones with no sizes, for example —
    are deleted outright, including colour variants, favorites, and group-order
    memberships.
    """
    from sqlalchemy.exc import IntegrityError
    from models import Favorite, collection_products

    product = Product.query.get_or_404(product_id)
    name = product.name
    style = product.style_number

    if product.order_items.count():
        product.is_active = False
        db.session.commit()
        flash(
            f'"{name}" appears in past orders, so it was hidden from the shop '
            f'instead of deleted. Order history stays readable.',
            'success',
        )
        return redirect(url_for('admin.products'))

    Favorite.query.filter_by(product_id=product.id).delete(synchronize_session=False)
    db.session.execute(
        collection_products.delete().where(
            collection_products.c.product_id == product.id
        )
    )
    db.session.delete(product)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        leftover = Product.query.get(product_id)
        if leftover:
            leftover.is_active = False
            db.session.commit()
            flash(
                f'"{name}" could not be deleted because something still points '
                f'at it. It was hidden from the shop instead.',
                'warning',
            )
        return redirect(url_for('admin.products'))

    flash(f'"{name}" ({style}) was removed from the catalog.', 'success')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/<int:product_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_product_active(product_id):
    """Toggle a product's is_active flag and return the new state as JSON."""
    from flask import request as flask_request, jsonify
    product = Product.query.get_or_404(product_id)
    turning_on = not product.is_active
    if turning_on:
        from utils.mockups import product_has_shop_image
        if not product_has_shop_image(product):
            message = 'Add a product photo before making this active.'
            if flask_request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'ok': False,
                    'is_active': product.is_active,
                    'label': 'Inactive',
                    'message': message,
                }), 400
            flash(message, 'error')
            return redirect(url_for('admin.products'))
    product.is_active = not product.is_active
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('toggle_product_active failed: %s', e)
        if flask_request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'message': 'Could not update product. Please try again.'}), 500
        flash('Could not update product. Please try again.', 'error')
        return redirect(url_for('admin.products'))

    label   = 'Active' if product.is_active else 'Inactive'
    message = f'"{product.name}" is now {label.lower()}'

    if flask_request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'is_active': product.is_active, 'label': label, 'message': message})

    flash(message, 'success')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/<int:product_id>/toggle-favorite', methods=['POST'])
@admin_required
def toggle_product_favorite(product_id):
    """Toggle a product's Customer Favorite flag and return the new state as JSON."""
    from flask import request as flask_request, jsonify
    product = Product.query.get_or_404(product_id)
    product.is_customer_favorite = not product.is_customer_favorite
    db.session.commit()

    label = 'Customer Favorite' if product.is_customer_favorite else 'Not featured'
    message = (f'"{product.name}" is now a Customer Favorite'
               if product.is_customer_favorite
               else f'"{product.name}" removed from Customer Favorites')

    if flask_request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'is_favorite': product.is_customer_favorite,
                        'label': label, 'message': message})

    flash(message, 'success')
    return redirect(request.referrer or url_for('admin.products'))
