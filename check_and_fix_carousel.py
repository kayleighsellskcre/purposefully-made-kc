"""
Check if ProductColorVariant data exists and populate if needed
"""
from app import create_app
from models import db, Product, ProductColorVariant
from utils.mockups import ensure_variant_mockup_urls

app = create_app()

with app.app_context():
    print("="*80)
    print("CHECKING PRODUCT COLOR VARIANTS")
    print("="*80)
    print()
    
    # Count products and variants
    total_products = Product.query.filter_by(is_active=True).count()
    total_variants = ProductColorVariant.query.count()
    
    print(f"Active Products: {total_products}")
    print(f"Color Variants: {total_variants}")
    print()
    
    if total_variants == 0:
        print("NO COLOR VARIANTS FOUND!")
        print("This is why carousel images aren't showing.")
        print()
        print("Creating variants from mockup folders...")
        print()
        
        # Create variants from mockup folders
        ensure_variant_mockup_urls(app)
        
        # Count again
        total_variants = ProductColorVariant.query.count()
        print(f"\nCreated {total_variants} color variants!")
    else:
        print("Color variants exist. Checking products without variants...")
        print()
        
        products_without_variants = []
        for product in Product.query.filter_by(is_active=True).all():
            variant_count = ProductColorVariant.query.filter_by(product_id=product.id).count()
            if variant_count == 0:
                products_without_variants.append(product.style_number)
        
        if products_without_variants:
            print(f"Found {len(products_without_variants)} products without variants:")
            for style in products_without_variants:
                print(f"  - {style}")
            print()
            print("Regenerating all variants from mockup folders...")
            ensure_variant_mockup_urls(app)
        else:
            print("All products have color variants!")
    
    print()
    print("="*80)
    print("FINAL STATUS")
    print("="*80)
    
    # Show breakdown
    for product in Product.query.filter_by(is_active=True).all():
        variant_count = ProductColorVariant.query.filter_by(product_id=product.id).count()
        print(f"{product.style_number}: {variant_count} colors")
    
    print()
    print(f"Total: {ProductColorVariant.query.count()} color variants across {total_products} products")
