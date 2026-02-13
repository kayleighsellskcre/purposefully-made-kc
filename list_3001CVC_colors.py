"""
List all colors for 3001CVC to help with naming your image files
"""
from app import create_app
from models import db, Product, ProductColorVariant

app = create_app()

with app.app_context():
    product = Product.query.filter_by(style_number='3001CVC').first()
    
    if not product:
        print("Product 3001CVC not found!")
    else:
        variants = ProductColorVariant.query.filter_by(product_id=product.id).order_by(ProductColorVariant.color_name).all()
        
        print(f"\n{'='*80}")
        print(f"COLOR NAMES FOR: {product.name} (Style: 3001CVC)")
        print(f"{'='*80}\n")
        print(f"Total Colors: {len(variants)}\n")
        print("Use these EXACT names when naming your files:\n")
        
        for i, v in enumerate(variants, 1):
            # Show both the database name and the filename format
            filename_format = v.color_name.replace(' ', '_')
            print(f"{i:2}. {v.color_name:30} -> 3001CVC_{filename_format}_front.png")
        
        print(f"\n{'='*80}")
        print("FILENAME EXAMPLES:")
        print(f"{'='*80}")
        print("3001CVC_Athletic_Heather_front.png")
        print("3001CVC_Athletic_Heather_back.png")
        print("3001CVC_Black_Heather_front.png")
        print("3001CVC_Black_Heather_back.png")
        print("3001CVC_Heather_Columbia_Blue_front.png")
        print("3001CVC_Heather_Columbia_Blue_back.png")
        print(f"\n{'='*80}\n")
