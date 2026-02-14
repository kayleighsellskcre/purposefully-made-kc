# Railway Deployment Guide

## Step 1: Add a Database (Recommended)

Railway's filesystem is ephemeral—SQLite data is lost on redeploy. Add PostgreSQL:

1. In your Railway project, click **+ New** → **Database** → **PostgreSQL**
2. Railway creates a database and sets `DATABASE_URL` automatically
3. You don't need to add `DATABASE_URL` yourself—Railway injects it

*(If you skip this, the app will use SQLite and work, but data resets on each deploy.)*

---

## Step 2: Add Environment Variables

1. Click your **service** (the app, not the database)
2. Go to the **Variables** tab
3. Click **+ New Variable** or **Raw Editor**
4. Add these variables:

### Required (minimum to run)

| Variable | Value | Notes |
|----------|-------|-------|
| `SECRET_KEY` | `your-random-secret-key-here` | Generate one: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FLASK_ENV` | `production` | Tells Flask it's production |

### Database (only if you did NOT add PostgreSQL)

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | `sqlite:///apparel.db` |

*(If you added PostgreSQL, Railway sets this for you—don't override it.)*

### Your live site URL (for SMS links)

| Variable | Value |
|----------|-------|
| `ADMIN_BASE_URL` | `https://your-app-name.up.railway.app` | Replace with your actual Railway URL |

### Email (for order confirmations & design request texts)

| Variable | Value |
|----------|-------|
| `MAIL_SERVER` | `smtp.gmail.com` |
| `MAIL_PORT` | `587` |
| `MAIL_USE_TLS` | `True` |
| `MAIL_USERNAME` | `your-email@gmail.com` |
| `MAIL_PASSWORD` | Your Gmail App Password |
| `MAIL_DEFAULT_SENDER` | `your-email@gmail.com` |

### Text alerts for design requests

| Variable | Value |
|----------|-------|
| `ADMIN_PHONE` | `7852491464` |
| `ADMIN_PHONE_CARRIER` | `verizon` | Or: att, tmobile, sprint |

### Payments (add when ready)

| Variable | Value |
|----------|-------|
| `STRIPE_PUBLIC_KEY` | `pk_live_...` |
| `STRIPE_SECRET_KEY` | `sk_live_...` |
| `PAYPAL_CLIENT_ID` | Your PayPal client ID |
| `PAYPAL_CLIENT_SECRET` | Your PayPal secret |
| `PAYPAL_MODE` | `live` |

### Optional

| Variable | Value |
|----------|-------|
| `SHIPPING_FLAT_RATE` | `11.00` |
| `ADMIN_EMAIL` | `admin@yourdomain.com` |

---

## Step 3: Raw Editor (faster)

In the Variables tab, click **Raw Editor** and paste (replace values):

```
SECRET_KEY=generate-a-long-random-string-here
FLASK_ENV=production
ADMIN_BASE_URL=https://your-app-name.up.railway.app
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-gmail-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com
ADMIN_PHONE=7852491464
ADMIN_PHONE_CARRIER=verizon
SHIPPING_FLAT_RATE=11.00
```

---

## Step 4: Start Command

In **Settings** → **Deploy**, set:

```
gunicorn -w 4 -b 0.0.0.0:$PORT app:app
```

---

## Step 5: Make Your Account Admin

**Option A – One-click (easiest):**

1. In Railway → your **app** service → **Variables**, add:
   - `ADMIN_PROMOTE_TOKEN` = any secret string (e.g. `my-secret-promote-123`)
2. Redeploy.
3. Log in to the live site.
4. Visit: `https://purposefullymadekc.com/auth/promote-admin?token=my-secret-promote-123&email=purposefullymadekc@gmail.com`
   (use your token and email)
5. You’ll be promoted to admin. Remove `ADMIN_PROMOTE_TOKEN` from Variables after use (optional, for security).

**Option B – SQL in Postgres:**

1. In Railway, click your **Postgres** service → **Data** (or **Query**)
2. Run: `UPDATE "user" SET is_admin = true WHERE email = 'purposefullymadekc@gmail.com';`
3. Log out and log back in.

---

## Step 6: Include Product Images (uploads folder)

Your `uploads/` and `static/uploads/` folders are now tracked in git. After you:

1. Add and commit the uploads: `git add uploads/ static/uploads/` (if they exist)
2. Push to GitHub

…your product mockups will deploy with the app. No re-upload needed.

---

## Step 7: Migrate Products from Local

Your old products are in `apparel.db` on your computer. To copy them to Railway:

1. In Railway: **Postgres** → **Connect** → copy **DATABASE_URL**
2. On your computer, open PowerShell in the project folder:

```powershell
$env:DATABASE_URL = "postgresql://..."   # paste the URL
python migrate_to_railway.py
```

*(Fix `postgres://` to `postgresql://` in the URL if needed.)*

3. The script copies products from local SQLite to Railway PostgreSQL.

**Note:** Product images (mockups) are local files — they won't transfer. Use **Sync from S&S Activewear** in Admin to refresh images, or re-upload mockups.

---

## Troubleshooting

- **502 Bad Gateway**: Check Railway **Logs** for crash errors. Common causes: missing `SECRET_KEY`, database connection (we auto-fix `postgres://` → `postgresql://`), or import errors.
- **App won't start**: Check the start command and that `PORT` is used (Railway sets it). Procfile provides: `gunicorn -w 4 -b 0.0.0.0:$PORT "app:create_app()"`
- **Database errors**: Ensure PostgreSQL is added and `DATABASE_URL` is set
- **No emails**: Verify MAIL_* variables and Gmail App Password
- **Design request texts not sending**: Check ADMIN_PHONE_CARRIER matches your carrier
