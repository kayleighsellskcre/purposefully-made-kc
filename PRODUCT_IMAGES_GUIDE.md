# 📸 PRODUCT IMAGES GUIDE

## 🎯 How Product Photos Work

Your platform has **TWO WAYS** to get product photos:

### Method 1: Automatic from S&S API ✨ (Recommended)
When you sync products from S&S Activewear, their product images are automatically downloaded!

### Method 2: Manual Upload 📤 (For Custom Mockups)
You can upload your own custom mockup templates through the admin panel.

---

## 🔄 AUTOMATIC IMAGE SYNC FROM S&S

### How It Works:
1. **Add your S&S API key** to the `.env` file
2. **Sync products** from Admin → Products → "Sync from S&S Activewear"
3. **Images download automatically!** 
   - Front view images
   - Back view images  
   - Saved to: `static/uploads/products/`
   - Named: `3001_front.jpg`, `3001_back.jpg`, etc.

### What Happens:
✅ Product data syncs (name, sizes, colors, prices)  
✅ Front mockup image downloads  
✅ Back mockup image downloads  
✅ Images automatically link to the correct product by style number  
✅ All images saved locally in your project  

---

## 📤 MANUAL IMAGE UPLOAD

### When to Use:
- You want **custom mockup templates** (not S&S stock photos)
- You have **professional product photography**
- You want **lifestyle shots** or **styled mockups**
- You need to **replace** an S&S image

### How to Upload:

1. **Go to Admin Dashboard**
   - http://localhost:5000/admin

2. **Click "Products"**

3. **Find the product** and click "Edit"

4. **Scroll to "Product Images" section**

5. **Upload Images:**
   - **Front Mockup**: Click "Choose File" → Select front image
   - **Back Mockup**: Click "Choose File" → Select back image

6. **Click "Save Changes"**

### Image Requirements:
- **Format**: JPG, PNG, or GIF
- **Recommended Size**: 1000x1000 pixels (square)
- **Background**: Transparent or white (for best results)
- **File Size**: Under 5MB each

---

## 🗂️ WHERE IMAGES ARE STORED

**Location:** `static/uploads/products/`

**Naming Convention:**
- S&S synced: `3001_front.jpg`, `3001_back.jpg`
- Manual upload: `3001_front_yourfilename.jpg`

**Database Storage:**
- Path saved in `front_mockup_template` column
- Example: `uploads/products/3001_front.jpg`

---

## ✅ HOW IMAGES CORRELATE WITH S&S PRODUCTS

### Automatic Matching:
When you sync from S&S, images automatically match by:

1. **Style Number**: Each product has a unique style # (e.g., 3001, 3719)
2. **API Data**: S&S provides image URLs with each product
3. **Download & Save**: System downloads images and names them with style number
4. **Database Link**: Image path saved to the correct product record

**Example:**
```
Product: Bella+Canvas 3001 Unisex Jersey Tee
Style Number: 3001
Front Image: 3001_front.jpg → Automatically linked
Back Image: 3001_back.jpg → Automatically linked
```

### Manual Matching:
When you manually upload images:
1. Go to the specific product's edit page
2. Upload the image
3. System automatically saves it with the product's style number
4. Database updates to link the new image

---

## 🎨 IMAGE WORKFLOW

### Scenario 1: New Store Setup
```
1. Add S&S API key to .env
2. Sync products → Images auto-download ✅
3. Done! All products have images
```

### Scenario 2: Custom Mockups
```
1. Sync products from S&S (gets data + stock images)
2. Create custom mockup templates
3. Upload custom images → Replaces stock images
4. Your custom mockups now display
```

### Scenario 3: Mix of Both
```
1. Sync from S&S → Most products use stock images ✅
2. For popular items → Upload custom lifestyle shots
3. Best of both worlds!
```

---

## 🚀 QUICK START

**To get images for ALL products right now:**

1. Open `.env` file
2. Add your S&S API credentials (lines 20-21)
3. Go to: http://localhost:5000/admin/products
4. Click "Sync from S&S Activewear"
5. Click "Sync Now"
6. Wait a few minutes...
7. **Done!** All products now have front/back images ✨

---

## 🔍 VERIFY IMAGES ARE WORKING

1. **Check File System:**
   - Go to: `static/uploads/products/`
   - You should see files like: `3001_front.jpg`, `3719_back.jpg`

2. **Check Product Page:**
   - Go to: Shop → Click any product
   - You should see the front image
   - Click "Back" thumbnail to see back view

3. **Check Admin:**
   - Admin → Products → Edit any product
   - Scroll to "Product Images"
   - You'll see current images displayed

---

## ❓ TROUBLESHOOTING

### Images Not Downloading from S&S?
- **Check API key** in `.env` is correct
- **Test connection**: Run `.\venv\Scripts\python -c "from services.ssactivewear_api import test_api_connection; test_api_connection()"`
- **Check permissions**: Make sure `static/uploads/products/` folder exists

### Manual Upload Not Working?
- **Check file size**: Must be under 5MB
- **Check format**: JPG, PNG, or GIF only
- **Check file name**: No special characters

### Images Not Showing on Product Page?
- **Check file path** in database (should be `uploads/products/filename.jpg`)
- **Verify file exists** in `static/uploads/products/`
- **Clear browser cache** and refresh

---

## 📊 IMAGE STATUS CHECK

To see which products have images:

**In Admin:**
1. Go to Admin → Products
2. Products with images will show thumbnails
3. Products without images will show placeholder

**Or check database:**
```python
# In Python shell
from models import Product
products_with_images = Product.query.filter(Product.front_mockup_template != None).all()
print(f"{len(products_with_images)} products have front images")
```

---

## 🎉 SUMMARY

- **Easiest**: Sync from S&S → Auto-downloads all images
- **Customizable**: Upload your own mockup templates anytime
- **Flexible**: Mix stock photos with custom shots
- **Automatic Matching**: Images link to products by style number
- **No Manual Work**: System handles everything!

**Ready to go? Add your S&S API key and sync!** 🚀
