# S&S Activewear API Integration Guide

## 🎯 Overview

Your platform is now integrated with S&S Activewear API to automatically sync:
- ✅ Product catalog (Bella+Canvas and other brands)
- ✅ Available colors per product
- ✅ Available sizes per product
- ✅ Real-time inventory levels
- ✅ Wholesale pricing

## 🔧 Setup

### 1. Add Your API Credentials

Edit `.env` file and add your S&S Activewear credentials:

```env
SSACTIVEWEAR_API_KEY=your_api_key_here
SSACTIVEWEAR_ACCOUNT_NUMBER=your_account_number_here
SSACTIVEWEAR_API_URL=https://api.ssactivewear.com
```

**Where to find these:**
1. Login to your S&S Activewear account
2. Go to Account Settings → API Access
3. Generate or copy your API key
4. Your account number is usually displayed in your dashboard

### 2. Test the Connection

```bash
# Activate virtual environment
.\venv\Scripts\activate

# Test API connection
python -c "from services.ssactivewear_api import test_api_connection; test_api_connection()"
```

You should see: `✓ API connection successful!`

## 📥 Syncing Your Catalog

### First Time Sync

```bash
# Preview what will be synced (dry run - no changes)
python sync_catalog.py --dry-run

# Sync first 5 products (for testing)
python sync_catalog.py --limit 5

# Full sync (this will take a few minutes)
python sync_catalog.py
```

### Daily Updates

```bash
# Run this daily to update your catalog
python sync_catalog.py
```

This will:
- ✅ Add new products from S&S
- ✅ Update colors, sizes, and pricing
- ✅ Keep your catalog current

### Sync Options

```bash
# Only add new products (don't update existing)
python sync_catalog.py --no-update

# Preview without saving (dry run)
python sync_catalog.py --dry-run

# Test with limited products
python sync_catalog.py --limit 10
```

## ⏰ Automated Daily Sync

### Windows (Task Scheduler)

1. Open Task Scheduler
2. Create Basic Task
3. Name: "Purposefully Made KC Catalog Sync"
4. Trigger: Daily at 2:00 AM
5. Action: Start a program
   - Program: `C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site\venv\Scripts\python.exe`
   - Arguments: `sync_catalog.py`
   - Start in: `C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site`
6. Finish

### macOS/Linux (Cron)

Add to crontab (`crontab -e`):

```bash
# Run daily at 2:00 AM
0 2 * * * cd /path/to/kb_apparel_site && ./venv/bin/python sync_catalog.py >> sync.log 2>&1
```

## 🎨 Admin UI Controls

### Manual Sync from Admin Panel

I've added a sync button to the admin panel:

1. Login as admin
2. Go to Products page
3. Click "Sync from S&S Activewear" button
4. View sync progress and results

## 📊 What Gets Synced

### Product Information
- ✅ Style number (e.g., "3001")
- ✅ Product name
- ✅ Category (Tee, Hoodie, etc.)
- ✅ Description
- ✅ Brand

### Pricing
- ✅ Wholesale cost (your cost)
- ✅ Retail price (automatically calculated with 2.5x markup)
- 💡 You can adjust markup in `services/ssactivewear_api.py`

### Availability
- ✅ All available colors
- ✅ All available sizes
- ✅ Inventory levels (optional)

### Images
- ⚠️ S&S provides product images via API
- 💡 You can download and link them automatically (see Advanced section)

## 🔄 How Updates Work

### New Products
- Automatically added with all details
- Set as active by default
- Ready to customize immediately

### Existing Products
- Colors and sizes updated
- Pricing updated
- Your custom settings preserved (mockups, descriptions you've edited, etc.)

### Removed Products
- Not automatically deleted
- Mark as inactive manually if needed

## 🚀 Advanced Features

### Sync Specific Brands

Edit `sync_catalog.py` to sync other brands:

```python
# Change this line
products_data = api.sync_bella_canvas_catalog(limit=limit)

# To sync other brands
products_data = api.get_styles(brand_name='Gildan')
```

### Adjust Pricing Markup

Edit `services/ssactivewear_api.py`:

```python
# Find this line
retail_price = wholesale_price * 2.5  # 2.5x markup

# Change to your desired markup
retail_price = wholesale_price * 3.0  # 3x markup
```

### Check Inventory Levels

```python
from services.ssactivewear_api import SSActivewearAPI

api = SSActivewearAPI()
inventory = api.get_inventory(style_number='3001')
print(inventory)
```

### Filter by Category

```python
# In sync_catalog.py, filter products
products = [p for p in products_data if p['category'] == 'Hoodie']
```

## 🔍 Troubleshooting

### "API key not configured"
- Check that `.env` file has `SSACTIVEWEAR_API_KEY`
- Make sure no extra spaces or quotes
- Restart Flask server after updating .env

### "No products fetched"
- Verify API credentials are correct
- Check account has access to Bella+Canvas products
- Test connection: `python services/ssactivewear_api.py`

### "Connection timeout"
- S&S API can be slow for large catalogs
- Use `--limit` option for testing
- Check internet connection

### Products not showing in admin
- Verify sync completed successfully
- Check `is_active` field is True
- Refresh admin page

## 📈 Best Practices

### Daily Sync Schedule
- ✅ Run daily at off-peak hours (2-4 AM)
- ✅ Monitor sync logs for errors
- ✅ Review new products before making them visible

### Pricing Strategy
- Set appropriate markup based on:
  - Your print costs (DTF transfer)
  - Overhead and shipping
  - Market rates
  - Volume discounts

### Product Curation
- Sync entire catalog
- Mark unwanted products as inactive
- Feature bestsellers on homepage

### Data Backup
- Backup database before major syncs
- Keep sync logs for troubleshooting
- Test with `--dry-run` first

## 🆘 Support

### S&S Activewear Support
- Website: https://www.ssactivewear.com
- API Docs: https://www.ssactivewear.com/api
- Support: 1-800-523-2155

### Platform Support
- Check `sync.log` for errors
- Review `services/ssactivewear_api.py` for API details
- Test connection with: `python services/ssactivewear_api.py`

## 🎯 Next Steps

1. ✅ Add API credentials to `.env`
2. ✅ Test connection
3. ✅ Run first sync with `--limit 5`
4. ✅ Review synced products in admin
5. ✅ Run full sync
6. ✅ Set up daily automation
7. ✅ Customize pricing markup if needed
8. ✅ Start taking orders!

---

**Your catalog will now stay automatically updated with the latest Bella+Canvas products, colors, and sizes from S&S Activewear!** 🎉
