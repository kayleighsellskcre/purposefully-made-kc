"""
Bulk import mockup images for products
Automatically matches images to color variants based on filename

FILENAME FORMAT:
  3001CVC_Athletic_Heather_front.png
  3001CVC_Athletic_Heather_back.png
  3001CVC_Black_Heather_front.png
  3001CVC_Black_Heather_back.png

Rules:
- Use underscores (_) to separate parts
- Color names should match database (use spaces → underscores)
- Views: front, back, side
- Supported formats: .png, .jpg, .jpeg, .webp
"""
from app import create_app
from models import db, Product, ProductColorVariant
import json
import os
import shutil
from pathlib import Path
import re

app = create_app()

# Directories
UPLOAD_DIR = Path('uploads/mockups')
STATIC_DIR = Path('static/images/products')

def normalize_color_name(name):
    """Normalize color name for matching"""
    # Convert underscores to spaces
    name = name.replace('_', ' ')
    # Title case for consistency
    return name.title()

def parse_filename(filename, style_number=None):
    """
    Extract style, color, and view from filename.
    Supports two formats:
    
    Format 1: 3001CVC_Athletic_Heather_front.png
    Format 2: BELLA_+_CANVAS_3001Y_Forest_Front_High.jpg
    """
    name = Path(filename).stem
    parts = name.split('_')
    
    if len(parts) < 3:
        return None, None, None
    
    # Try Format 2 first: BELLA_+_CANVAS_3001Y_Color_Front_High.jpg
    if style_number and style_number in parts:
        try:
            style_idx = parts.index(style_number)
            # Find Front or Back (view)
            view_idx = None
            for i, p in enumerate(parts[style_idx + 1:], start=style_idx + 1):
                if p.lower() == 'front':
                    view_idx = i
                    view = 'front'
                    break
                if p.lower() == 'back':
                    view_idx = i
                    view = 'back'
                    break
            if view_idx is not None:
                color_parts = parts[style_idx + 1:view_idx]
                if color_parts:
                    color_name = ' '.join(color_parts).title()
                    return style_number, color_name, view
        except (ValueError, IndexError):
            pass
    
    # Format 1: style_color_view (e.g. 3001_Aqua_front.jpg)
    style = parts[0]
    view = parts[-1].lower()
    if view not in ['front', 'back', 'side']:
        return None, None, None
    color_parts = parts[1:-1]
    color_name = ' '.join(color_parts).title()
    return style, color_name, view

def import_images_for_style(style_number):
    """Import all images for a specific style"""
    
    print(f"\n{'='*80}")
    print(f"IMPORTING MOCKUP IMAGES FOR STYLE: {style_number}")
    print(f"{'='*80}\n")
    
    # Find the product
    product = Product.query.filter_by(style_number=style_number).first()
    
    if not product:
        print(f"[ERROR] Product with style {style_number} not found in database!")
        return
    
    print(f"[OK] Found product: {product.name} (ID: {product.id})")
    
    # Get upload directory for this style
    style_upload_dir = UPLOAD_DIR / style_number
    
    if not style_upload_dir.exists():
        print(f"[ERROR] Upload directory not found: {style_upload_dir}")
        print(f"   Please create it and add your images!")
        return
    
    # Get all image files
    image_files = []
    for ext in ['*.png', '*.jpg', '*.jpeg', '*.webp']:
        image_files.extend(style_upload_dir.glob(ext))
    
    if not image_files:
        print(f"[SKIP] No image files found in {style_upload_dir}")
        print(f"   Supported formats: .png, .jpg, .jpeg, .webp")
        return
    
    print(f"\n[OK] Found {len(image_files)} image files")
    print(f"\n{'='*80}")
    print("PROCESSING IMAGES...")
    print(f"{'='*80}\n")
    
    # Create product directory in static
    product_static_dir = STATIC_DIR / style_number
    product_static_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each image
    imported_count = 0
    skipped_count = 0
    error_count = 0
    
    for image_file in sorted(image_files):
        filename = image_file.name
        
        # Parse filename (pass style_number for Bella+Canvas format support)
        parsed_style, color_name, view = parse_filename(filename, style_number)
        
        if not parsed_style or not color_name or not view:
            print(f"[SKIP] {filename}")
            print(f"   Invalid filename format. Use: {style_number}_Color_Name_view.ext or BELLA_+_CANVAS_{style_number}_Color_Front_High.jpg")
            skipped_count += 1
            continue
        
        if parsed_style != style_number:
            print(f"[SKIP] {filename}")
            print(f"   Style mismatch: {parsed_style} != {style_number}")
            skipped_count += 1
            continue
        
        # Find or create matching color variant
        variant = ProductColorVariant.query.filter_by(
            product_id=product.id,
            color_name=color_name
        ).first()
        
        if not variant:
            # Create variant from uploaded image (enables carousel on shop page)
            size_inventory = "{}"
            if product.available_sizes:
                try:
                    sizes = json.loads(product.available_sizes)
                    size_inventory = json.dumps({s: 0 for s in sizes})
                except Exception:
                    pass
            variant = ProductColorVariant(
                product_id=product.id,
                color_name=color_name,
                size_inventory=size_inventory
            )
            db.session.add(variant)
            db.session.flush()  # Get variant.id
            print(f"[NEW] Created variant for '{color_name}'")
        
        # Copy image to static directory
        dest_filename = f"{style_number}_{color_name.replace(' ', '_')}_{view}{image_file.suffix}"
        dest_path = product_static_dir / dest_filename
        
        try:
            shutil.copy2(image_file, dest_path)
            
            # Generate URL for database
            image_url = f"/static/images/products/{style_number}/{dest_filename}"
            
            # Update database
            if view == 'front':
                variant.front_image_url = image_url
            elif view == 'back':
                variant.back_image_url = image_url
            elif view == 'side':
                variant.side_image_url = image_url
            
            db.session.commit()
            
            print(f"[OK] IMPORTED: {filename}")
            print(f"   -> {color_name} ({view})")
            print(f"   -> {image_url}")
            imported_count += 1
            
        except Exception as e:
            print(f"[ERROR] {filename}")
            print(f"   {str(e)}")
            error_count += 1
            db.session.rollback()
    
    # Summary
    print(f"\n{'='*80}")
    print("IMPORT COMPLETE!")
    print(f"{'='*80}")
    print(f"[OK] Imported: {imported_count} images")
    print(f"[SKIP] Skipped: {skipped_count} files")
    print(f"[ERROR] Errors: {error_count} files")
    print(f"\nImages saved to: {product_static_dir}")
    print(f"{'='*80}\n")

if __name__ == '__main__':
    with app.app_context():
        import sys
        
        if len(sys.argv) > 1:
            style_number = sys.argv[1]
        else:
            # Default to 3001CVC
            style_number = '3001CVC'
        
        import_images_for_style(style_number)
