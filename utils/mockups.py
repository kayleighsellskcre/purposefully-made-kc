"""
Resolve product mockup image URLs from DB (color variants) or from uploads/mockups folder.
All mockups under uploads/mockups/{style_number}/ are used so each product shows its uploaded mockups.
"""
import os
from pathlib import Path


def _mockup_dirs(app):
    """Return list of directories to search for mockup files (most preferred first)."""
    # App uploads: static/uploads/mockups (UPLOAD_FOLDER is typically static/uploads)
    basedir = app.config.get('UPLOAD_FOLDER')
    if not basedir:
        basedir = os.path.join(app.root_path, 'static', 'uploads')
    if not os.path.isabs(basedir):
        basedir = os.path.join(app.root_path, basedir)
    app_mockups = os.path.join(basedir, 'mockups')
    # Project root uploads/mockups (where bulk-uploaded mockups live)
    root_mockups = os.path.join(app.root_path, 'uploads', 'mockups')
    return [app_mockups, root_mockups]


def _find_mockup_file(app, style_number, color_name, view):
    """
    Look for a mockup file in uploads/mockups for the given style, color, and view.
    Filename format: {style_number}_{Color_Name}_front.jpg or _back.jpg (underscores in color).
    Returns the relative path for URL (e.g. 3001/3001_Aqua_front.jpg) if found, else None.
    """
    safe_color = (color_name or '').replace(' ', '_').strip()
    if not safe_color:
        return None
    base_name = f"{style_number}_{safe_color}_{view}"
    for ext in ('.jpg', '.jpeg', '.png', '.webp'):
        filename = base_name + ext
        for mockup_dir in _mockup_dirs(app):
            if not mockup_dir or not os.path.isdir(mockup_dir):
                continue
            style_dir = os.path.join(mockup_dir, str(style_number))
            filepath = os.path.join(style_dir, filename)
            if os.path.isfile(filepath):
                return f"{style_number}/{filename}"
    return None


def get_mockup_url_for_variant(product, variant, view, app):
    """
    Return the best available mockup URL for a product color variant and view (front/back).
    Prefers local uploads/mockups so customer-uploaded images always show for design preview.
    """
    rel = _find_mockup_file(app, product.style_number, getattr(variant, 'color_name', None), view)
    if rel:
        from flask import url_for
        return url_for('main.serve_mockup', path=rel)
    if view == 'front' and getattr(variant, 'front_image_url', None):
        return variant.front_image_url
    if view == 'back' and getattr(variant, 'back_image_url', None):
        return variant.back_image_url
    return None


def discover_colors_from_mockup_folder(app, style_number):
    """
    Scan uploads/mockups/{style_number}/ for image files and return unique colors with their mockup URLs.
    Filename format: {style_number}_{Color_Name}_front.jpg (or _back). Returns list of dicts:
    [{'color_name': 'Aqua', 'front_image': url or None, 'back_image': url or None, 'inventory': {}}, ...]
    so that ALL mockups in the folder show up with the product even if there's no DB variant yet.
    """
    from flask import url_for
    # Parse filenames like 3001_Aqua_front.jpg -> color "Aqua", view "front"
    colors_seen = {}
    for mockup_dir in _mockup_dirs(app):
        if not mockup_dir or not os.path.isdir(mockup_dir):
            continue
        style_dir = os.path.join(mockup_dir, str(style_number))
        if not os.path.isdir(style_dir):
            continue
        for ext in ('.jpg', '.jpeg', '.png', '.webp'):
            for f in Path(style_dir).glob('*' + ext):
                name = f.stem
                parts = name.split('_')
                if len(parts) < 3:
                    continue
                if parts[0] != str(style_number):
                    continue
                view = parts[-1].lower()
                if view not in ('front', 'back', 'side'):
                    continue
                color_parts = parts[1:-1]
                color_name = ' '.join(color_parts).title()
                if not color_name:
                    continue
                rel = f"{style_number}/{f.name}"
                url = url_for('main.serve_mockup', path=rel)
                if color_name not in colors_seen:
                    colors_seen[color_name] = {'color_name': color_name, 'color_hex': None, 'front_image': None, 'back_image': None, 'front_image_url': None, 'back_image_url': None, 'inventory': {}}
                if view == 'front':
                    colors_seen[color_name]['front_image'] = url
                    colors_seen[color_name]['front_image_url'] = url
                elif view == 'back':
                    colors_seen[color_name]['back_image'] = url
                    colors_seen[color_name]['back_image_url'] = url
    return list(colors_seen.values())


def get_color_variants_data_for_product(product, app):
    """
    Build color_variants_data for product detail/customize pages.
    Merges DB variants with mockup folder, no duplicates.
    Returns list of dicts: color_name, color_hex, front_image, back_image, inventory.
    """
    import json
    color_variants_data = []
    seen_colors = set()
    for variant in getattr(product, 'color_variants', []) or []:
        inventory = json.loads(variant.size_inventory) if variant.size_inventory else {}
        front_image = get_mockup_url_for_variant(product, variant, 'front', app) or variant.front_image_url
        back_image = get_mockup_url_for_variant(product, variant, 'back', app) or variant.back_image_url
        color_variants_data.append({
            'color_name': variant.color_name,
            'color_hex': variant.color_hex,
            'front_image': front_image,
            'back_image': back_image,
            'inventory': inventory
        })
        seen_colors.add(variant.color_name)
    for extra in discover_colors_from_mockup_folder(app, product.style_number):
        if extra['color_name'] in seen_colors or not (extra.get('front_image') or extra.get('back_image')):
            continue
        seen_colors.add(extra['color_name'])
        color_variants_data.append({
            'color_name': extra['color_name'],
            'color_hex': extra.get('color_hex'),
            'front_image': extra.get('front_image_url') or extra.get('front_image'),
            'back_image': extra.get('back_image_url') or extra.get('back_image'),
            'inventory': extra.get('inventory', {})
        })
    return color_variants_data


def ensure_variant_mockup_urls(app):
    """
    Fill missing front_image_url/back_image_url on ProductColorVariant from mockup folder.
    Also CREATE variants for colors that exist in mockup folder but not in DB.
    Call after sync so customers see mockup images when selecting colors.
    """
    from models import Product, ProductColorVariant, db
    from flask import url_for
    import json

    for product in Product.query.filter_by(is_active=True).all():
        existing_colors = {v.color_name for v in ProductColorVariant.query.filter_by(product_id=product.id).all()}
        # 1. Fill missing URLs on existing variants
        for v in ProductColorVariant.query.filter_by(product_id=product.id).all():
            if not v.front_image_url:
                rel = _find_mockup_file(app, product.style_number, v.color_name, 'front')
                if rel:
                    v.front_image_url = url_for('main.serve_mockup', path=rel)
            if not v.back_image_url:
                rel = _find_mockup_file(app, product.style_number, v.color_name, 'back')
                if rel:
                    v.back_image_url = url_for('main.serve_mockup', path=rel)

        # 2. Create variants for mockup folder colors not yet in DB
        for c in discover_colors_from_mockup_folder(app, product.style_number):
            if c['color_name'] in existing_colors or not (c.get('front_image') or c.get('back_image')):
                continue
            existing_colors.add(c['color_name'])
            sizes = []
            try:
                sizes = json.loads(product.available_sizes) if product.available_sizes else ['S', 'M', 'L', 'XL']
            except (TypeError, ValueError):
                sizes = ['S', 'M', 'L', 'XL']
            inv = json.dumps({s: 0 for s in sizes})
            db.session.add(ProductColorVariant(
                product_id=product.id,
                color_name=c['color_name'],
                front_image_url=c.get('front_image_url') or c.get('front_image'),
                back_image_url=c.get('back_image_url') or c.get('back_image'),
                size_inventory=inv
            ))


def get_carousel_colors_for_product(product, app, allowed_colors=None):
    """
    Build carousel color list for a product, merging DB variants with mockup folder.
    Returns list of dicts with color_name and front_image_url for shop carousel.
    Ensures ALL colors from uploads/mockups show in carousel with correct images.
    allowed_colors: optional set to filter (e.g. for collection restrictions)
    """
    from flask import url_for
    result = []
    seen = set()

    # 1. DB variants with front_image_url
    for v in getattr(product, 'color_variants', []) or []:
        if v.color_name in seen:
            continue
        if allowed_colors and v.color_name not in allowed_colors:
            continue
        seen.add(v.color_name)
        url = v.front_image_url
        if not url:
            rel = _find_mockup_file(app, product.style_number, v.color_name, 'front')
            url = url_for('main.serve_mockup', path=rel) if rel else None
        if url:
            result.append({'color_name': v.color_name, 'front_image_url': url})

    # 2. Colors from mockup folder not yet in result
    for c in discover_colors_from_mockup_folder(app, product.style_number):
        if c['color_name'] in seen:
            continue
        if allowed_colors and c['color_name'] not in allowed_colors:
            continue
        if not c.get('front_image') and not c.get('front_image_url'):
            continue
        seen.add(c['color_name'])
        url = c.get('front_image_url') or c.get('front_image')
        result.append({'color_name': c['color_name'], 'front_image_url': url})

    return result


def create_products_from_mockup_folders(app):
    """
    Create Product + ProductColorVariant for each style folder in uploads/mockups
    that doesn't have a product yet. Returns count of products created.
    """
    from pathlib import Path
    from models import db, Product, ProductColorVariant
    import json
    import os

    mockup_styles = set()
    for mockup_dir in _mockup_dirs(app):
        if not mockup_dir or not os.path.isdir(mockup_dir):
            continue
        for p in Path(mockup_dir).iterdir():
            if p.is_dir() and not p.name.startswith('.'):
                mockup_styles.add(p.name)

    created = 0
    for style_num in sorted(mockup_styles):
        if Product.query.filter_by(style_number=style_num).first():
            continue
        colors_data = discover_colors_from_mockup_folder(app, style_num)
        if not colors_data:
            continue
        color_names = [c['color_name'] for c in colors_data]
        product = Product(
            style_number=style_num,
            name=f"Bella+Canvas Style {style_num}",
            category="Tee",
            description="",
            base_price=25.00,
            wholesale_cost=10.00,
            is_active=True,
            available_sizes=json.dumps(["XS", "S", "M", "L", "XL", "2XL", "3XL"]),
            available_colors=json.dumps(color_names),
            brand="Bella+Canvas"
        )
        db.session.add(product)
        db.session.flush()
        for c in colors_data:
            inv = json.dumps({s: 0 for s in ["XS", "S", "M", "L", "XL", "2XL", "3XL"]})
            db.session.add(ProductColorVariant(
                product_id=product.id,
                color_name=c['color_name'],
                front_image_url=c.get('front_image_url') or c.get('front_image'),
                back_image_url=c.get('back_image_url') or c.get('back_image'),
                size_inventory=inv
            ))
        created += 1
    return created
