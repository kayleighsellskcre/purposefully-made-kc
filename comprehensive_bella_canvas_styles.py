"""
Comprehensive Bella+Canvas style mapping for S&S Activewear
Auto-categorizes all common Bella+Canvas styles with detailed attributes
"""
from app import create_app
from models import db, Product

app = create_app()

# Complete Bella+Canvas product catalog with attributes
BELLA_CANVAS_STYLES = {
    # ADULT TEES
    '3001': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3001CVC': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3001C': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3413': {'category': 'Tri-Blend Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3005': {'category': 'V-Neck Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'V-Neck', 'sleeve_length': 'Short Sleeve'},
    '3513': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3650': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3719': {'category': 'Raglan', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3729': {'category': 'Raglan', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '4711': {'category': 'Tri-Blend Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '4719': {'category': 'Tri-Blend Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    
    # WOMEN'S TEES
    '6004': {'category': 'Tee', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '6400': {'category': 'Tee', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '6405': {'category': 'V-Neck Tee', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'V-Neck', 'sleeve_length': 'Short Sleeve'},
    '6035': {'category': 'Tee', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '8413': {'category': 'Tri-Blend Tee', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    
    # MEN'S TEES
    '3006': {'category': 'V-Neck Tee', 'age_group': 'adult', 'fit_type': "Men's", 'neck_style': 'V-Neck', 'sleeve_length': 'Short Sleeve'},
    
    # LONG SLEEVE
    '3501': {'category': 'Long Sleeve', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3501CVC': {'category': 'Long Sleeve', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3007': {'category': 'Long Sleeve', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '8852': {'category': 'Long Sleeve', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    
    # TANKS
    '3480': {'category': 'Tank', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Tank', 'sleeve_length': 'Sleeveless'},
    '3633': {'category': 'Tank', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Tank', 'sleeve_length': 'Sleeveless'},
    '3091': {'category': 'Tank', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Tank', 'sleeve_length': 'Sleeveless'},
    '8803': {'category': 'Tank', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'Tank', 'sleeve_length': 'Sleeveless'},
    '6488': {'category': 'Tank', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'Tank', 'sleeve_length': 'Sleeveless'},
    '8800': {'category': 'Tank', 'age_group': 'adult', 'fit_type': "Women's", 'neck_style': 'Tank', 'sleeve_length': 'Sleeveless'},
    
    # HOODIES
    '3719': {'category': 'Hoodie', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Hooded', 'sleeve_length': 'Long Sleeve'},
    '3901': {'category': 'Hoodie', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Hooded', 'sleeve_length': 'Long Sleeve'},
    '3719': {'category': 'Hoodie', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Hooded', 'sleeve_length': 'Long Sleeve'},
    
    # SWEATSHIRTS
    '3945': {'category': 'Sweatshirt', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3902': {'category': 'Sweatshirt', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    
    # POLO
    '6400': {'category': 'Polo', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Collar', 'sleeve_length': 'Short Sleeve'},
    
    # ZIP-UPS
    '3739': {'category': 'Zip-Up', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Zip-Up', 'sleeve_length': 'Long Sleeve'},
    '3909': {'category': 'Zip-Up', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Zip-Up', 'sleeve_length': 'Long Sleeve'},
    
    # YOUTH TEES
    '3001Y': {'category': 'Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3001YCVC': {'category': 'Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3413Y': {'category': 'Tri-Blend Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3005Y': {'category': 'V-Neck Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'V-Neck', 'sleeve_length': 'Short Sleeve'},
    '3513Y': {'category': 'Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    
    # YOUTH LONG SLEEVE
    '3501Y': {'category': 'Long Sleeve', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3501YCVC': {'category': 'Long Sleeve', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    
    # YOUTH RAGLANS
    '3719Y': {'category': 'Raglan', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3729Y': {'category': 'Raglan', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    
    # YOUTH HOODIES
    '3901Y': {'category': 'Hoodie', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Hooded', 'sleeve_length': 'Long Sleeve'},
    
    # YOUTH SWEATSHIRTS
    '3945Y': {'category': 'Sweatshirt', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    
    # TODDLER
    '3001T': {'category': 'Tee', 'age_group': 'toddler', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3413T': {'category': 'Tri-Blend Tee', 'age_group': 'toddler', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3501T': {'category': 'Long Sleeve', 'age_group': 'toddler', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    
    # INFANT/BABY
    '100B': {'category': 'Tee', 'age_group': 'baby', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3001C': {'category': 'Tee', 'age_group': 'baby', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '100': {'category': 'Tee', 'age_group': 'baby', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
}

def update_all_products():
    """Update all products in database with comprehensive attributes"""
    with app.app_context():
        print("="*80)
        print("COMPREHENSIVE BELLA+CANVAS CATEGORIZATION")
        print("="*80)
        print()
        
        # Get all active products
        products = Product.query.filter_by(is_active=True).all()
        updated_count = 0
        not_found_count = 0
        not_found_styles = []
        
        for product in products:
            style = product.style_number
            
            # Try exact match first
            if style in BELLA_CANVAS_STYLES:
                attrs = BELLA_CANVAS_STYLES[style]
                changed = False
                changes = []
                
                if product.category != attrs['category']:
                    changes.append(f"Category: {product.category} -> {attrs['category']}")
                    product.category = attrs['category']
                    changed = True
                
                if product.age_group != attrs['age_group']:
                    changes.append(f"Age: {product.age_group} -> {attrs['age_group']}")
                    product.age_group = attrs['age_group']
                    changed = True
                
                if product.fit_type != attrs['fit_type']:
                    changes.append(f"Fit: {product.fit_type} -> {attrs['fit_type']}")
                    product.fit_type = attrs['fit_type']
                    changed = True
                
                if product.neck_style != attrs['neck_style']:
                    changes.append(f"Neck: {product.neck_style} -> {attrs['neck_style']}")
                    product.neck_style = attrs['neck_style']
                    changed = True
                
                if product.sleeve_length != attrs['sleeve_length']:
                    changes.append(f"Sleeve: {product.sleeve_length} -> {attrs['sleeve_length']}")
                    product.sleeve_length = attrs['sleeve_length']
                    changed = True
                
                if changed:
                    print(f"UPDATED: {style} - {product.name}")
                    for change in changes:
                        print(f"  {change}")
                    print()
                    updated_count += 1
                else:
                    print(f"OK: {style} - already categorized")
            else:
                # Style not in our mapping
                not_found_count += 1
                not_found_styles.append(style)
                print(f"UNKNOWN: {style} - {product.name} (not in mapping)")
        
        db.session.commit()
        
        print()
        print("="*80)
        print("SUMMARY")
        print("="*80)
        print(f"Total Products: {len(products)}")
        print(f"Updated: {updated_count}")
        print(f"Already Correct: {len(products) - updated_count - not_found_count}")
        print(f"Unknown Styles: {not_found_count}")
        
        if not_found_styles:
            print()
            print("Unknown style numbers (need manual categorization):")
            for style in not_found_styles:
                print(f"  - {style}")
        
        print()
        print("="*80)
        
        # Print final breakdown
        print("\nFINAL PRODUCT BREAKDOWN:")
        print()
        
        categories = {}
        age_groups = {}
        fit_types = {}
        neck_styles = {}
        sleeve_lengths = {}
        
        for product in Product.query.filter_by(is_active=True).all():
            categories[product.category or 'Unknown'] = categories.get(product.category or 'Unknown', 0) + 1
            age_groups[product.age_group or 'Unknown'] = age_groups.get(product.age_group or 'Unknown', 0) + 1
            fit_types[product.fit_type or 'Unknown'] = fit_types.get(product.fit_type or 'Unknown', 0) + 1
            neck_styles[product.neck_style or 'Unknown'] = neck_styles.get(product.neck_style or 'Unknown', 0) + 1
            sleeve_lengths[product.sleeve_length or 'Unknown'] = sleeve_lengths.get(product.sleeve_length or 'Unknown', 0) + 1
        
        print("By Category:")
        for cat, count in sorted(categories.items()):
            print(f"  {cat}: {count}")
        
        print("\nBy Age Group:")
        for age, count in sorted(age_groups.items()):
            print(f"  {age.title()}: {count}")
        
        print("\nBy Fit Type:")
        for fit, count in sorted(fit_types.items()):
            print(f"  {fit}: {count}")
        
        print("\nBy Neck Style:")
        for neck, count in sorted(neck_styles.items()):
            print(f"  {neck}: {count}")
        
        print("\nBy Sleeve Length:")
        for sleeve, count in sorted(sleeve_lengths.items()):
            print(f"  {sleeve}: {count}")

if __name__ == '__main__':
    update_all_products()
