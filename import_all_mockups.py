"""
Import mockup images for ALL product styles.
Run this after uploading images to each style's folder in uploads/mockups/
Discovers style folders automatically from uploads/mockups/ and static/uploads/mockups/.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from models import Product
from import_mockup_images import import_images_for_style
from pathlib import Path

UPLOAD_MOCKUPS = Path('uploads/mockups')
STATIC_MOCKUPS = Path('static/uploads/mockups')

def discover_style_folders():
    """Find all style numbers that have mockup folders (uploads/mockups or static/uploads/mockups)."""
    styles = set()
    for base in (UPLOAD_MOCKUPS, STATIC_MOCKUPS):
        if not base.is_dir():
            continue
        for p in base.iterdir():
            if p.is_dir() and p.name not in ('.', '..') and not p.name.startswith('.'):
                styles.add(p.name)
    return sorted(styles)

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        styles = discover_style_folders()
        print("\n" + "="*80)
        print("IMPORTING MOCKUP IMAGES FOR ALL STYLES")
        print("="*80)
        print(f"Discovered style folders: {styles or '(none)'}\n")
        
        for style in styles:
            if Product.query.filter_by(style_number=style).first():
                import_images_for_style(style)
            else:
                print(f"\n[SKIP] {style} - No product in database (sync from S&S first)\n")
        
        print("\n" + "="*80)
        print("ALL IMPORTS COMPLETE!")
        print("="*80 + "\n")
