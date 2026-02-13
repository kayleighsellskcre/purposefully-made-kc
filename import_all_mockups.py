"""
Import mockup images for ALL product styles.
Run this after uploading images to each style's folder in uploads/mockups/
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from models import Product
from import_mockup_images import import_images_for_style

# All style numbers from our product catalog
STYLES = [
    '3001', '3001CVC', '3001Y', '3001YCVC',
    '3413', '3413Y',
    '3501', '3501CVC', '3501Y', '3501YCVC',
    '3513', '3513Y',
    '3719', '3719Y', '3729',
    '3901', '3901Y', '3945',
    '4711', '4719',
    '6400'
]

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        print("\n" + "="*80)
        print("IMPORTING MOCKUP IMAGES FOR ALL STYLES")
        print("="*80)
        
        for style in STYLES:
            # Check if product exists
            if Product.query.filter_by(style_number=style).first():
                import_images_for_style(style)
            else:
                print(f"\n[SKIP] {style} - No product in database\n")
        
        print("\n" + "="*80)
        print("ALL IMPORTS COMPLETE!")
        print("="*80 + "\n")
