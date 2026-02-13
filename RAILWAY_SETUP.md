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
gunicorn -w 4 -b 0.0.0.0:$PORT "app:create_app()"
```

*(The parentheses are required so gunicorn invokes the factory to create the app.)*

---

## Step 5: Deploy & Create Admin

1. Click **Deploy** (or push to GitHub to trigger auto-deploy)
2. Once live, create your admin user. Run in **Railway CLI** or add a one-time setup:

   You'll need to run `python set_admin.py` or use the Flask shell. Easiest: add a temporary route or run a migration. Alternatively, register a new account on the live site, then in Railway's PostgreSQL console (or a script), set that user's `is_admin = true`.

---

## Troubleshooting

- **App won't start**: Check the start command and that `PORT` is used (Railway sets it)
- **Database errors**: Ensure PostgreSQL is added and `DATABASE_URL` is set
- **No emails**: Verify MAIL_* variables and Gmail App Password
- **Design request texts not sending**: Check ADMIN_PHONE_CARRIER matches your carrier
