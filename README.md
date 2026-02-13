# Purposefully Made KC - Custom Apparel Platform

A professional custom apparel ordering platform built with Flask. Features live preview customization, team collections, production management, and integrated payments.

## Features

### Customer Features
- **Live Product Customizer**: Upload designs and see them on actual garments in real-time
- **Bella+Canvas Exclusive**: Premium quality apparel catalog
- **Easy Checkout**: Stripe (Card + Apple Pay) and PayPal/Venmo payments
- **Team Collections**: Shareable links for group orders (schools, teams, events)
- **User Accounts**: Save addresses, view order history, reorder with one click
- **Local Pickup or Shipping**: Choose pickup (free) or shipping ($11 flat rate)

### Admin Features
- **Order Management**: Track orders from new → paid → production → shipped
- **Production Center**: 
  - Blank apparel purchase lists (by style/color/size)
  - DTF transfer batch sheets (grouped by design)
  - Packing slips and labels
- **Product Catalog**: Manage Bella+Canvas products
- **Collections Management**: Create team stores with shareable links
- **Artwork Library**: Centralized design storage with metadata
- **Status Tracking**: Update order status and notify customers

## Tech Stack

- **Backend**: Flask 3.0, SQLAlchemy
- **Database**: SQLite (dev) / PostgreSQL (production ready)
- **Payments**: Stripe, PayPal SDK
- **Image Processing**: Pillow (PIL)
- **Frontend**: Vanilla JavaScript, modern CSS
- **Authentication**: Flask-Login

## Installation

### Prerequisites
- Python 3.9+
- pip (Python package manager)
- Virtual environment (recommended)

### Setup Instructions

1. **Clone or navigate to the project directory**
```bash
cd kb_apparel_site
```

2. **Create and activate virtual environment**
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables**
```bash
# Copy the example env file
copy .env.example .env

# Edit .env and add your credentials:
# - SECRET_KEY (generate with: python -c "import secrets; print(secrets.token_hex(32))")
# - STRIPE_PUBLIC_KEY and STRIPE_SECRET_KEY (from Stripe dashboard)
# - PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (from PayPal developer)
# - MAIL settings for email notifications
```

5. **Initialize the database**
```bash
flask init-db
```

6. **Create admin user**
```bash
flask create-admin
# Enter your admin email and password when prompted
```

7. **Run the development server**
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | Flask secret key for sessions | Yes |
| `DATABASE_URL` | Database connection string | No (defaults to SQLite) |
| `STRIPE_PUBLIC_KEY` | Stripe publishable key | Yes |
| `STRIPE_SECRET_KEY` | Stripe secret key | Yes |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | For webhooks |
| `PAYPAL_CLIENT_ID` | PayPal client ID | Yes |
| `PAYPAL_CLIENT_SECRET` | PayPal client secret | Yes |
| `PAYPAL_MODE` | `sandbox` or `live` | Yes |
| `MAIL_SERVER` | SMTP server | For emails |
| `MAIL_PORT` | SMTP port (587) | For emails |
| `MAIL_USERNAME` | SMTP username | For emails |
| `MAIL_PASSWORD` | SMTP password | For emails |
| `SHIPPING_FLAT_RATE` | Shipping cost (default: 11.00) | No |

### Stripe Setup

1. Create a Stripe account at https://stripe.com
2. Get API keys from Dashboard → Developers → API keys
3. Add keys to `.env` file
4. Test with test mode keys first

### PayPal Setup

1. Create a PayPal Business account
2. Go to https://developer.paypal.com
3. Create an app and get credentials
4. Add to `.env` file
5. Use `sandbox` mode for testing

## Usage

### For Customers

1. **Browse Products**: Visit the shop to see available Bella+Canvas products
2. **Customize**: 
   - Select a product
   - Choose color and size
   - Upload your design (PNG, JPG, SVG, PDF)
   - Position design with placement presets
3. **Checkout**: 
   - Choose local pickup (free) or shipping (+$11)
   - Pay with card, Apple Pay, PayPal, or Venmo
4. **Track Orders**: View order status in your account dashboard

### For Teams/Schools (Collections)

1. Admin creates a Collection with:
   - Name (e.g., "Silver Lake Elementary Spirit Wear")
   - Products available
   - Optional order deadline
   - Pickup instructions
2. Collection gets a shareable URL: `/c/silverlake-spiritwear`
3. Share link with team members
4. All orders grouped together for easy production

### For Admins

1. **Access Admin Panel**: `/admin` (requires admin account)
2. **Manage Orders**:
   - View all orders by status
   - Update order status
   - Add tracking information
3. **Production Center**:
   - **Blank Apparel List**: Shows exactly what blanks to order
     - Example: "Bella+Canvas 3001, White, Medium: 15 units"
   - **DTF Batch Sheets**: Groups designs for printing
     - Example: "Logo A, 12x12 inches, Center Chest: 20 prints needed"
4. **Manage Products**: Add/edit Bella+Canvas products
5. **Create Collections**: Set up team stores

## Project Structure

```
kb_apparel_site/
├── app.py                 # Main application
├── config.py              # Configuration
├── models.py              # Database models
├── requirements.txt       # Python dependencies
├── routes/               # Route blueprints
│   ├── auth.py          # Authentication
│   ├── main.py          # Homepage
│   ├── shop.py          # Product browsing
│   ├── cart.py          # Shopping cart
│   ├── checkout.py      # Checkout & payments
│   ├── account.py       # User accounts
│   ├── admin.py         # Admin dashboard
│   ├── collection.py    # Team collections
│   └── api.py           # API endpoints
├── templates/           # HTML templates
│   ├── base.html       # Base layout
│   ├── index.html      # Homepage
│   ├── auth/           # Login, register
│   ├── shop/           # Product pages, customizer
│   ├── cart/           # Cart page
│   ├── checkout/       # Checkout flow
│   ├── account/        # Account dashboard
│   ├── admin/          # Admin pages
│   └── collection/     # Collection pages
└── static/             # Static assets
    ├── css/           # Stylesheets
    ├── js/            # JavaScript
    ├── img/           # Images
    └── uploads/       # User uploads (designs, proofs)
```

## Database Schema

### Key Models
- **User**: Customer and admin accounts
- **Product**: Bella+Canvas catalog
- **Collection**: Team/school stores
- **Order**: Customer orders
- **OrderItem**: Individual items in order
- **Design**: Uploaded artwork
- **Address**: Shipping addresses

## Adding Products

### Manual Entry (Admin Panel)
1. Go to `/admin/products`
2. Click "Add Product"
3. Enter:
   - Style Number (e.g., 3001)
   - Name (e.g., "Unisex Jersey Tee")
   - Category (Tee, Hoodie, etc.)
   - Base Price
   - Available Sizes (JSON): `["XS", "S", "M", "L", "XL", "2XL", "3XL"]`
   - Available Colors (JSON): `["White", "Black", "Navy", "Red"]`

### Example Products to Start
- **3001**: Bella+Canvas Unisex Jersey Tee
- **3501**: Unisex Jersey Long Sleeve
- **3719**: Unisex Sponge Fleece Pullover Hoodie
- **8800**: Unisex Crewneck Sweatshirt

## Production Workflow

1. **Customer places order** → Status: New
2. **Payment processed** → Status: Paid
3. **Admin reviews in Production Center**:
   - Export blank apparel list → Order from supplier
   - Export DTF batch sheets → Send to print vendor
4. **Printing complete** → Status: In Production
5. **Items assembled** → Status: Ready
6. **Customer pickup or ship** → Status: Picked Up / Shipped
7. **Complete** → Status: Completed

## Payment Flow

### Stripe (Card + Apple Pay)
1. Customer enters card or uses Apple Pay
2. Payment intent created
3. Payment confirmed
4. Order created with payment ID

### PayPal/Venmo
1. Customer clicks PayPal button
2. Redirected to PayPal (can choose Venmo)
3. Payment approved
4. Returned to site, order created

## Customization

### Branding
- Edit `static/css/main.css` to change colors
- Update CSS variables in `:root` selector
- Replace logo in `templates/base.html`

### Email Templates
- Add email templates in `templates/email/`
- Configure SMTP in `.env`
- Email sending functions in `routes/checkout.py`

## Deployment

### Production Checklist
- [ ] Set strong `SECRET_KEY`
- [ ] Use PostgreSQL database
- [ ] Set `PAYPAL_MODE=live`
- [ ] Use live Stripe keys
- [ ] Configure production email server
- [ ] Set up SSL/HTTPS
- [ ] Configure domain
- [ ] Set up backups

### Recommended Hosting
- **Heroku**: Easy deployment with add-ons
- **DigitalOcean**: App Platform or Droplet
- **AWS**: Elastic Beanstalk or EC2
- **Render**: Modern alternative to Heroku

## Support

For questions or issues:
- Check this README
- Review inline code comments
- Check Flask documentation: https://flask.palletsprojects.com

## License

This project is proprietary software for Purposefully Made KC.

## Credits

Built with:
- Flask (https://flask.palletsprojects.com)
- Stripe (https://stripe.com)
- PayPal (https://paypal.com)
- Bella+Canvas (https://bellacanvas.com)
