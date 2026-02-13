# Quick Start Guide - Purposefully Made KC

Get your luxury custom apparel platform running in 5 minutes!

## Quick Setup (Windows)

```powershell
# 1. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy environment file
copy .env.example .env

# 4. Edit .env and set SECRET_KEY (minimum)
# Generate one with: python -c "import secrets; print(secrets.token_hex(32))"

# 5. Initialize database
flask init-db

# 6. Create admin user
flask create-admin
# Enter: admin@example.com / password

# 7. Run the server
python app.py
```

Visit: http://localhost:5000

## Quick Setup (macOS/Linux)

```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy environment file
cp .env.example .env

# 4. Edit .env and set SECRET_KEY (minimum)
# Generate one with: python -c "import secrets; print(secrets.token_hex(32))"

# 5. Initialize database
flask init-db

# 6. Create admin user
flask create-admin
# Enter: admin@example.com / password

# 7. Run the server
python app.py
```

Visit: http://localhost:5000

## Essential Configuration

### Minimum Required (.env file)
```
SECRET_KEY=your-generated-secret-key-here
```

### For Full Functionality (.env file)
```
SECRET_KEY=your-generated-secret-key-here
STRIPE_PUBLIC_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_MODE=sandbox
```

## First Steps After Setup

### 1. Login as Admin
- Go to http://localhost:5000/auth/login
- Use credentials you created during setup
- You'll see "Admin" link in navigation

### 2. Add Your First Product
- Click "Admin" → "Products" → "Add Product"
- Example Bella+Canvas 3001 (Unisex Tee):
  ```
  Style Number: 3001
  Name: Bella+Canvas Unisex Jersey Tee
  Category: Tee
  Base Price: 25.00
  Available Sizes: ["XS", "S", "M", "L", "XL", "2XL"]
  Available Colors: ["White", "Black", "Navy", "Red", "Heather Gray"]
  ```

### 3. Create a Collection (Optional)
- Click "Admin" → "Collections" → "Add Collection"
- Example:
  ```
  Name: Sample Team Store
  Slug: sample-team
  Description: Test team store
  Select products: Check the products you added
  ```
- Collection URL: http://localhost:5000/c/sample-team

### 4. Test the Customer Flow
- Logout (or use incognito window)
- Browse shop → Select product
- Customize → Upload a test image
- Add to cart → Checkout
- (Without payment keys, checkout won't process, but you can see the flow)

## Sample Data Script

Want to populate with sample products quickly? Create `seed_data.py`:

```python
from app import create_app
from models import db, Product
import json

app = create_app()

with app.app_context():
    products = [
        {
            "style_number": "3001",
            "name": "Bella+Canvas Unisex Jersey Tee",
            "category": "Tee",
            "base_price": 25.00,
            "available_sizes": json.dumps(["XS", "S", "M", "L", "XL", "2XL", "3XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy", "Red", "Heather Gray"]),
            "is_active": True
        },
        {
            "style_number": "3719",
            "name": "Bella+Canvas Unisex Sponge Fleece Pullover Hoodie",
            "category": "Hoodie",
            "base_price": 45.00,
            "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
            "available_colors": json.dumps(["Black", "Navy", "Heather Gray"]),
            "is_active": True
        },
        {
            "style_number": "8800",
            "name": "Bella+Canvas Unisex Crewneck Sweatshirt",
            "category": "Crew",
            "base_price": 38.00,
            "available_sizes": json.dumps(["S", "M", "L", "XL", "2XL"]),
            "available_colors": json.dumps(["White", "Black", "Navy"]),
            "is_active": True
        }
    ]
    
    for p_data in products:
        if not Product.query.filter_by(style_number=p_data["style_number"]).first():
            product = Product(**p_data)
            db.session.add(product)
    
    db.session.commit()
    print("✓ Sample products added!")
```

Run with: `python seed_data.py`

## Common Issues

### "No module named 'flask'"
```bash
# Make sure virtual environment is activated
# You should see (venv) in your terminal prompt
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux
```

### "Table doesn't exist" errors
```bash
flask init-db
```

### Can't access admin panel
```bash
# Make sure you created admin user
flask create-admin
```

### Checkout not working
- You need to configure Stripe keys in `.env` for payments
- Get test keys from https://stripe.com (free account)

## Next Steps

1. **Add Real Products**: Enter your Bella+Canvas catalog
2. **Configure Payments**: Add Stripe/PayPal credentials
3. **Customize Branding**: Edit `static/css/main.css`
4. **Add Product Images**: Place images in `static/img/products/`
5. **Test Full Flow**: Create order, manage in admin, export production lists

## Development Tips

### View Database (Optional)
```bash
pip install sqlite-web
sqlite_web apparel.db
# Opens browser at http://localhost:8080
```

### Reset Everything
```bash
# Delete database and start fresh
rm apparel.db  # macOS/Linux
del apparel.db  # Windows
flask init-db
flask create-admin
```

### Enable Debug Mode
Already enabled by default in `app.py`:
```python
app.run(debug=True)
```

## Need Help?

1. Check the full README.md
2. Review error messages carefully
3. Check Flask docs: https://flask.palletsprojects.com
4. Verify all dependencies installed: `pip list`

## Ready for Production?

See README.md section "Deployment" for production checklist and hosting options.

---

**You're ready to go!** Start by logging in as admin and adding your first product.
