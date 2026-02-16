"""
Import Bella+Canvas standard descriptions and size charts
Run this to populate all products with proper descriptions
"""
from app import create_app
from models import db, Product
import json

# Import spec data from extracted Bella+Canvas PDFs
from bella_canvas_spec_data import BELLA_CANVAS_SPECS

app = create_app()

# Bella+Canvas Standard Descriptions (legacy + spec sheet data)
DESCRIPTIONS = {
    '3001': {
        'description': 'The Bella+Canvas 3001 is the essential unisex jersey short sleeve tee. Made from 100% combed and ring-spun cotton (Heather colors contain polyester), this 4.2 oz fabric offers exceptional softness and durability. Features include side-seamed construction, shoulder-to-shoulder taping, and a retail fit. Pre-shrunk fabric ensures consistent sizing wash after wash.',
        'fabric': '100% Airlume combed and ring-spun cotton, 32 singles (Ash - 99% cotton, 1% poly; Heathers - 52% cotton, 48% poly; Athletic/Black Heather - 90% cotton, 10% poly)',
        'fit_guide': 'Unisex sizing, retail fit, side-seamed, 4.2 oz',
        'size_chart': {
            'XS': {'chest': '16.5', 'length': '27'},
            'S': {'chest': '18', 'length': '28'},
            'M': {'chest': '20', 'length': '29'},
            'L': {'chest': '22', 'length': '30'},
            'XL': {'chest': '24', 'length': '31'},
            '2XL': {'chest': '26', 'length': '32'},
            '3XL': {'chest': '28', 'length': '33'},
            '4XL': {'chest': '30', 'length': '34'},
            '5XL': {'chest': '32', 'length': '35'}
        }
    },
    '3001CVC': {
        'description': 'The Bella+Canvas 3001CVC takes the classic 3001 fit and blends it with CVC fabric for enhanced durability. This 4.2 oz tee features 52% combed and ring-spun cotton, 48% polyester for the perfect balance of softness and performance. Side-seamed with shoulder taping and a modern retail fit.',
        'fabric': '52% Airlume combed and ring-spun cotton, 48% polyester, 32 singles',
        'fit_guide': 'Unisex sizing, retail fit, side-seamed, 4.2 oz',
        'size_chart': {
            'XS': {'chest': '16.5', 'length': '27'},
            'S': {'chest': '18', 'length': '28'},
            'M': {'chest': '20', 'length': '29'},
            'L': {'chest': '22', 'length': '30'},
            'XL': {'chest': '24', 'length': '31'},
            '2XL': {'chest': '26', 'length': '32'},
            '3XL': {'chest': '28', 'length': '33'}
        }
    },
    '3001Y': {
        'description': 'The youth version of the popular 3001, sized and fitted for kids. Made with the same quality Airlume combed and ring-spun cotton for exceptional softness. Features side-seamed construction and shoulder-to-shoulder taping for durability. Perfect for youth programs, schools, and sports teams.',
        'fabric': '100% Airlume combed and ring-spun cotton (Heather colors contain polyester)',
        'fit_guide': 'Youth sizing, side-seamed, 4.2 oz',
        'size_chart': {
            'XS': {'chest': '14', 'length': '18.5'},
            'S': {'chest': '15', 'length': '20'},
            'M': {'chest': '16', 'length': '21.5'},
            'L': {'chest': '17', 'length': '23'},
            'XL': {'chest': '18', 'length': '24.5'}
        }
    }
}

# Add more styles as needed
DESCRIPTIONS['3001YCVC'] = {
    'description': 'Youth CVC version combining the comfort of cotton with the durability of polyester. Perfect blend for active kids.',
    'fabric': '52% Airlume combed and ring-spun cotton, 48% polyester',
    'fit_guide': 'Youth sizing, side-seamed, 4.2 oz',
    'size_chart': DESCRIPTIONS['3001Y']['size_chart']
}

# Merge in spec sheet data (3413, 3413Y, 3501, 3501CVC, 3501Y, 3501YCVC, 3513, 3513Y, 3719, 3719Y, 3729, 3901, 3901Y, 3945, 4711, 4719, 6400)
for style, data in BELLA_CANVAS_SPECS.items():
    DESCRIPTIONS[style] = {
        'description': data['description'],
        'fabric': data['fabric'],
        'fit_guide': data['fit_guide'],
        'size_chart': data['size_chart']
    }

with app.app_context():
    products = Product.query.filter_by(is_active=True).all()
    updated = 0
    
    print(f"Updating {len(products)} products with Bella+Canvas descriptions...")
    print("="*80)
    
    for product in products:
        style = product.style_number
        
        if style in DESCRIPTIONS:
            data = DESCRIPTIONS[style]
            product.description = data['description']
            product.fabric_details = data['fabric']
            product.fit_guide = data['fit_guide']
            product.size_chart = json.dumps(data['size_chart'])
            updated += 1
            print(f"OK {style} - {product.name}")
        else:
            print(f"  {style} - No description available (add to DESCRIPTIONS dict)")
    
    if updated > 0:
        db.session.commit()
        print("\n" + "="*80)
        print(f"SUCCESS: Updated {updated} products with descriptions and sizing!")
    else:
        print("\nNo products updated - add more styles to DESCRIPTIONS dict")
