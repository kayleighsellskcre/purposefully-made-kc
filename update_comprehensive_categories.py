"""
Comprehensive product categorization update
Adds detailed attributes to all existing products
"""
from app import create_app
from models import db, Product

app = create_app()

# Bella+Canvas style mapping with comprehensive attributes
STYLE_ATTRIBUTES = {
    # Standard Tees
    '3001': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3001CVC': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3001Y': {'category': 'Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3001YCVC': {'category': 'Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    
    # Tri-Blend
    '3413': {'category': 'Tri-Blend Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3413Y': {'category': 'Tri-Blend Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    
    # Long Sleeve
    '3501': {'category': 'Long Sleeve', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3501CVC': {'category': 'Long Sleeve', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3501Y': {'category': 'Long Sleeve', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3501YCVC': {'category': 'Long Sleeve', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    
    # V-Neck
    '3005': {'category': 'V-Neck Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'V-Neck', 'sleeve_length': 'Short Sleeve'},
    
    # Tank
    '3480': {'category': 'Tank', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Tank', 'sleeve_length': 'Sleeveless'},
    
    # Raglan
    '3719': {'category': 'Raglan', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    '3719Y': {'category': 'Raglan', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    
    # Tees (more styles)
    '3513': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3513Y': {'category': 'Tee', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '3729': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '4711': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    '4719': {'category': 'Tee', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Short Sleeve'},
    
    # Hoodies
    '3901': {'category': 'Hoodie', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Hooded', 'sleeve_length': 'Long Sleeve'},
    '3901Y': {'category': 'Hoodie', 'age_group': 'youth', 'fit_type': 'Unisex', 'neck_style': 'Hooded', 'sleeve_length': 'Long Sleeve'},
    
    # Sweatshirts
    '3945': {'category': 'Sweatshirt', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Crew Neck', 'sleeve_length': 'Long Sleeve'},
    
    # Polo
    '6400': {'category': 'Polo', 'age_group': 'adult', 'fit_type': 'Unisex', 'neck_style': 'Collar', 'sleeve_length': 'Short Sleeve'},
}

with app.app_context():
    print("="*60)
    print("COMPREHENSIVE PRODUCT CATEGORIZATION")
    print("="*60)
    
    products = Product.query.filter_by(is_active=True).all()
    updated_count = 0
    
    for product in products:
        if product.style_number in STYLE_ATTRIBUTES:
            attrs = STYLE_ATTRIBUTES[product.style_number]
            
            # Update all attributes
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
                print(f"\n{product.style_number} - {product.name}")
                for change in changes:
                    print(f"  {change}")
                updated_count += 1
    
    db.session.commit()
    
    print("\n" + "="*60)
    print(f"Updated {updated_count} products with detailed attributes")
    print("="*60)
    
    # Print summary
    print("\nProduct Breakdown:")
    
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
    
    print("\nBy Category:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    
    print("\nBy Age Group:")
    for age, count in sorted(age_groups.items()):
        print(f"  {age}: {count}")
    
    print("\nBy Fit Type:")
    for fit, count in sorted(fit_types.items()):
        print(f"  {fit}: {count}")
    
    print("\nBy Neck Style:")
    for neck, count in sorted(neck_styles.items()):
        print(f"  {neck}: {count}")
    
    print("\nBy Sleeve Length:")
    for sleeve, count in sorted(sleeve_lengths.items()):
        print(f"  {sleeve}: {count}")
