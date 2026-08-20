# Overnight Audit — Push Summary
**Good morning! Everything below is ready to push. Open Cursor terminal and run the command at the bottom.**

---

## What was fixed

### 🛒 Cart & Favorites — Always Visible on Mobile
**Problem:** Cart and favorites icons were inside the collapsing hamburger menu, so on phones they disappeared.  
**Fix:** Moved both icons into a new always-visible `.nav-icons` strip that sits next to the hamburger button. Now they're always on screen at every size.  
**Files:** `templates/base.html`, `static/css/main.css`

---

### 🖼️ Product Images — Brand Prefix Stripping
**Problem:** Products with style numbers like `BC3001` couldn't find their images in `static/images/products/3001/` because the folder is named without the brand prefix.  
**Fix:** Added regex prefix-stripping (`BC3001` → `3001`) as a fallback image lookup in both the shop page and the collection/group order page.  
**Files:** `utils/mockups.py`, `utils/product_filters.py`

---

### 📸 "Skipped Picture Day" Placeholder
**Problem:** Products with no image showed a broken fallback path (`img/products/{style}.jpg`) on the collection page, and nothing at all in some places.  
**Fix:** All product card views (shop, collection, customize) now show a friendly "This mockup skipped picture day! Tap to customize & order ♡" message when no image is available.  
**Files:** `templates/shop/index.html`, `templates/collection/view.html`

---

### 📋 Collection/Group Order View — Image Fallback
**Problem:** The group order product page didn't have a `fallback_image_url` set, so non-carousel products had no image at all.  
**Fix:** Route now calls `get_first_shop_image_url()` for every product in the collection view, same as the shop page.  
**Files:** `routes/collection.py`, `templates/collection/view.html`

---

### 🔤 Missing CSS Variable
**Problem:** `--font-secondary` was used throughout (contact page labels, footer) but never defined, causing a silent CSS fallback.  
**Fix:** Added `--font-secondary: 'Cormorant Garamond', 'Inter', sans-serif;` to `:root`.  
**Files:** `static/css/main.css`

---

### 🗂️ Group Orders Directory — All Orders Shown
**Problem:** The public Group Orders page only showed orders flagged `show_in_directory = True`, hiding most orders.  
**Fix:** All active orders now show, with Public / Link Only / Code Required badges so visitors know how to access each one. A search box was added too.  
**Files:** `routes/shop.py`, `templates/shop/group_orders.html`

---

### ⚙️ Group Order Form — Restrict Options Simplified
**Problem:** There was a visible "Restrict Options" checkbox that confused organizers.  
**Fix:** Restrict options is now always `True` (hidden from the form). Organizers pick their colors/designs and everyone in the group stays matching automatically.  
**Files:** `templates/includes/group_order_edit_form.html`, `templates/admin/add_collection.html`, `utils/group_orders.py`

---

### 🗄️ CSS Cache Bust
Bumped CSS version from `?v=14` → `?v=15` so browsers pick up all the CSS changes immediately on next load.  
**Files:** `templates/base.html`

---

## Files changed (full list)

| File | What changed |
|------|-------------|
| `templates/base.html` | nav-icons strip, CSS v=15 |
| `static/css/main.css` | --font-secondary, .nav-icons, mobile cart/favorites touch targets |
| `utils/mockups.py` | brand-prefix strip in get_first_shop_image_url |
| `utils/product_filters.py` | brand-prefix strip in prepare_catalog / preview_image_url |
| `routes/collection.py` | set fallback_image_url on every product |
| `routes/shop.py` | removed show_in_directory filter from group orders query |
| `templates/collection/view.html` | fallback image + "skipped picture day" |
| `templates/shop/index.html` | "skipped picture day" on carousel and single-image cards |
| `templates/shop/group_orders.html` | search box, all orders, Public/Link/Code badges |
| `templates/includes/group_order_edit_form.html` | restrict_options hidden, 4-step layout |
| `templates/admin/add_collection.html` | back_design_type radios, restrict_options hidden |
| `utils/group_orders.py` | restrict_options always True |

---

## Push command — run this in Cursor terminal

```
git add -A && git commit -m "Overnight audit: mobile nav, image fallbacks, group orders UX, CSS vars" && git push
```

That's everything! The site should look and work much better on phones now. 🎉
