# Quick Setup: S&S Activewear API Integration

## ⚡ 5-Minute Setup

### Step 1: Add Your API Credentials

Edit `.env` file and replace these lines:

```env
SSACTIVEWEAR_API_KEY=your_ss_activewear_api_key_here
SSACTIVEWEAR_ACCOUNT_NUMBER=your_account_number_here
```

With your actual credentials:

```env
SSACTIVEWEAR_API_KEY=ABC123XYZ789  # Your actual API key
SSACTIVEWEAR_ACCOUNT_NUMBER=123456  # Your actual account number
```

### Step 2: Upgrade Database

Open terminal/command prompt and run:

```bash
# Activate virtual environment
.\venv\Scripts\activate

# Upgrade database to add new fields
flask upgrade-db
```

### Step 3: Test Connection

```bash
python -c "from services.ssactivewear_api import test_api_connection; test_api_connection()"
```

You should see: **✓ API connection successful!**

### Step 4: First Sync

```bash
# Test with 5 products first
python sync_catalog.py --limit 5

# If that works, run full sync
python sync_catalog.py
```

## ✅ Done!

Your products are now synced with live S&S Activewear data!

## 🔄 Keep Updated

### Manual Sync Anytime

```bash
python sync_catalog.py
```

### Automatic Daily Sync

**Windows:**
1. Open Task Scheduler
2. Create Basic Task
3. Name: "Sync Purposefully Made KC Catalog"
4. Trigger: Daily at 2:00 AM
5. Action: Start program
   - Program: `C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site\venv\Scripts\python.exe`
   - Arguments: `sync_catalog.py`
   - Start in: `C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site`

**macOS/Linux:**
```bash
# Add to crontab (crontab -e)
0 2 * * * cd /path/to/kb_apparel_site && ./venv/bin/python sync_catalog.py
```

## 📖 Full Documentation

See **API_INTEGRATION_GUIDE.md** for:
- Advanced features
- Inventory tracking
- Multiple brands
- Troubleshooting
- Best practices

## 🆘 Troubleshooting

### Can't connect to API
1. Check API credentials in `.env`
2. Verify account has API access enabled
3. Check internet connection

### No products synced
1. Run with `--dry-run` to see what would be synced
2. Check API credentials are correct
3. Verify account has access to Bella+Canvas products

### Need help?
Check **API_INTEGRATION_GUIDE.md** for detailed troubleshooting

---

**Ready to go! Your catalog will stay automatically updated with the latest products, colors, and sizes.** 🎉
