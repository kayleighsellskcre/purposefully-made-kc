"""
Check which products have mockup images
"""
from app import create_app
from models import Product, ProductColorVariant

app = create_app()

with app.app_context():
    print("="*80)
    print("CHECKING PRODUCT MOCKUP IMAGES")
    print("="*80)
    
    products = Product.query.all()
    
    products_with_images = []
    products_without_images = []
    
    for product in products:
        variants = product.color_variants.all()
        
        if not variants:
            products_without_images.append(product)
            continue
        
        has_images = any(v.front_image_url for v in variants)
        
        if has_images:
            products_with_images.append((product, variants))
        else:
            products_without_images.append(product)
    
    print(f"\nPRODUCTS WITH MOCKUP IMAGES: {len(products_with_images)}")
    print("="*80)
    for product, variants in products_with_images:
        print(f"\n{product.style_number} - {product.name}")
        print(f"  Colors: {len(variants)}")
        for v in variants[:3]:
            img_status = "HAS IMAGE" if v.front_image_url else "NO IMAGE"
            print(f"    {v.color_name}: {img_status}")
            if v.front_image_url:
                print(f"      URL: {v.front_image_url[:70]}...")
    
    print(f"\n\nPRODUCTS WITHOUT MOCKUP IMAGES: {len(products_without_images)}")
    print("="*80)
    for product in products_without_images:
        print(f"{product.style_number} - {product.name}")
    
    if products_with_images:
        print("\n" + "="*80)
        print("RECOMMENDATION:")
        print("="*80)
        best_product = products_with_images[0][0]
        print(f"\nTry this product (it HAS mockup images):")
        print(f"  Style: {best_product.style_number}")
        print(f"  Name: {best_product.name}")
        print(f"  URL: http://localhost:5000/shop/customize/{best_product.id}")
    else:
        print("\n" + "="*80)
        print("NO PRODUCTS HAVE MOCKUP IMAGES FROM S&S")
        print("="*80)
        print("\nThis means S&S Activewear doesn't provide mockup images for")
        print("the products we synced. You'll need to:")
        print("1. Upload your own mockup images via Admin panel")
        print("2. OR sync different products (popular t-shirts usually have images)")
