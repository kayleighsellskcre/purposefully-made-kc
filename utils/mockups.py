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
    Uses: (1) variant.front_image_url or back_image_url if set, (2) file in uploads/mockups.
    """
    if view == 'front' and getattr(variant, 'front_image_url', None):
        return variant.front_image_url
    if view == 'back' and getattr(variant, 'back_image_url', None):
        return variant.back_image_url
    rel = _find_mockup_file(app, product.style_number, getattr(variant, 'color_name', None), view)
    if rel:
        from flask import url_for
        return url_for('main.serve_mockup', path=rel)
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
                    colors_seen[color_name] = {'color_name': color_name, 'color_hex': None, 'front_image': None, 'back_image': None, 'inventory': {}}
                if view == 'front':
                    colors_seen[color_name]['front_image'] = url
                elif view == 'back':
                    colors_seen[color_name]['back_image'] = url
    return list(colors_seen.values())
