# 🚀 QUICK START GUIDE

## ✅ Your Platform is Ready!

### 1. 🔐 Login to Your Account

**Website:** http://localhost:5000

**Your Admin Credentials:**
- Email: `kayleighsellskcre@gmail.com`
- Password: `admin123`

**⚠️ IMPORTANT:** Change your password immediately after first login!
- Go to: Account → Profile → Change Password

---

### 2. 🔑 Add Your S&S Activewear API Key

**Open file:** `.env` (in your project root folder)

**Find this section (around line 19-22):**
```env
# S&S Activewear API Configuration
SSACTIVEWEAR_API_KEY=your_ss_activewear_api_key_here
SSACTIVEWEAR_ACCOUNT_NUMBER=your_account_number_here
```

**Replace with your real credentials:**
```env
SSACTIVEWEAR_API_KEY=your_actual_api_key
SSACTIVEWEAR_ACCOUNT_NUMBER=your_actual_account_number
```

**Save the file** and your API will be connected!

---

### 3. 📦 Import Products from S&S Activewear

**Option A: From Admin Dashboard** (Recommended)
1. Login at http://localhost:5000/login
2. Click "Admin Dashboard" in your account menu
3. Go to "Products"
4. Click "Sync from S&S Activewear" button
5. Select "Full Sync" and click "Sync Now"

**Option B: From Command Line**
```powershell
.\venv\Scripts\python sync_catalog.py
```

---

### 4. ✅ All Navigation is Working!

**Public Pages:**
- Home: http://localhost:5000/
- Shop: http://localhost:5000/shop
- Cart: http://localhost:5000/cart
- Checkout: http://localhost:5000/checkout

**Account Pages (must login):**
- My Orders: http://localhost:5000/account/orders
- My Addresses: http://localhost:5000/account/addresses
- My Profile: http://localhost:5000/account/profile

**Admin Pages (admin only):**
- Dashboard: http://localhost:5000/admin
- Orders: http://localhost:5000/admin/orders
- Products: http://localhost:5000/admin/products
- Collections: http://localhost:5000/admin/collections
- Production: http://localhost:5000/admin/production

---

### 5. 🎨 Test the Platform

1. **Browse Shop** - View available products
2. **Customize Product** - Upload a design and see live preview
3. **Add to Cart** - Test cart functionality
4. **Checkout** - Place a test order
5. **View Orders** - Check your order history in your account

---

## 🛠️ Need Help?

- **API Setup Guide:** See `API_KEY_SETUP.md`
- **Full Documentation:** See `README.md`
- **Detailed API Info:** See `API_INTEGRATION_GUIDE.md`

---

## 📧 Your Account Summary

| Field | Value |
|-------|-------|
| **Email** | kayleighsellskcre@gmail.com |
| **Password** | admin123 |
| **Role** | Admin/Owner |
| **Status** | Active |

**Remember:** Change your password after first login!

---

## 🎉 You're All Set!

Your luxury apparel platform is fully functional. All buttons work, all pages are connected, and you're ready to start taking orders!

**Next Steps:**
1. Add your S&S API key
2. Sync products
3. Customize your branding
4. Add payment credentials (Stripe/PayPal)
5. Start selling!

---

**Happy Selling! 🚀**
