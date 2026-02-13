# S&S ACTIVEWEAR API SETUP

## 🔑 Where to Add Your API Key

Open the file: **`.env`** (in the root folder of your project)

Find these lines (around line 19-22):

```env
# S&S Activewear API Configuration
SSACTIVEWEAR_API_KEY=your_ss_activewear_api_key_here
SSACTIVEWEAR_ACCOUNT_NUMBER=your_account_number_here
SSACTIVEWEAR_API_URL=https://api.ssactivewear.com
```

## 📝 Replace with Your Real Credentials

Replace `your_ss_activewear_api_key_here` and `your_account_number_here` with your actual credentials.

**Example:**
```env
SSACTIVEWEAR_API_KEY=abc123xyz789yourrealapikey
SSACTIVEWEAR_ACCOUNT_NUMBER=123456
SSACTIVEWEAR_API_URL=https://api.ssactivewear.com
```

## ⚡ Test Your API Connection

After adding your credentials, run:

```powershell
.\venv\Scripts\python -c "from services.ssactivewear_api import test_api_connection; test_api_connection()"
```

If successful, you'll see: `✓ API connection successful!`

## 📦 Sync Products from S&S Activewear

To import all products:

```powershell
.\venv\Scripts\python sync_catalog.py
```

Or from the admin dashboard:
1. Login at http://localhost:5000/login
2. Go to Admin → Products
3. Click "Sync from S&S Activewear"

## 🔄 Daily Auto-Sync (Optional)

Set up a scheduled task to run daily:

```powershell
flask sync-catalog
```

---

**Need Help?** Check `API_INTEGRATION_GUIDE.md` for detailed instructions.
