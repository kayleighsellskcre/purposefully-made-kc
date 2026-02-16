# Get Everything Working on Railway

Follow these steps **in order**. Each step builds on the previous one.

**First: check what's wrong.** Visit **https://purposefullymadekc.com/status** — it shows exactly what's configured and what to fix.

---

## Step 1: Add PostgreSQL (so accounts persist)

**Without this, you lose your account after every deploy.**

1. In Railway, open your project
2. Click **+ New** → **Database** → **PostgreSQL**
3. Railway creates the database and sets `DATABASE_URL` for your app
4. Make sure your **app service** and **PostgreSQL** are in the same project (Railway links them automatically)

**Done when:** Your app redeploys and you no longer see "Using SQLite" in the logs.

---

## Step 2: Add these variables in Railway

Click your **app service** (not the database) → **Variables** tab → **Raw Editor**.

Paste this and **replace the placeholder values** with your real ones:

```
SECRET_KEY=your-random-secret-here
FLASK_ENV=production
ADMIN_EMAIL=purposefullymadekc@gmail.com
SSACTIVEWEAR_API_KEY=paste-your-sands-api-key-here
SSACTIVEWEAR_ACCOUNT_NUMBER=paste-your-sands-account-number-here
ADMIN_BASE_URL=https://purposefullymadekc.com
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

**Where to get each:**

| Variable | Where to get it |
|----------|-----------------|
| `SECRET_KEY` | Run: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_EMAIL` | Use: `purposefullymadekc@gmail.com` |
| `SSACTIVEWEAR_API_KEY` | Log in at [ssactivewear.com](https://www.ssactivewear.com) → Account → API Access |
| `SSACTIVEWEAR_ACCOUNT_NUMBER` | Same place as API key (your S&S account number) |
| `MAIL_*` | Gmail App Password (Google Account → Security → 2-Step Verification → App passwords) |

**Do NOT add `DATABASE_URL`** — Railway sets it when you add PostgreSQL.

---

## Step 3: Redeploy

After saving variables, Railway redeploys automatically. Wait for it to finish.

---

## Step 4: Register and become admin

1. Go to **https://purposefullymadekc.com**
2. Click **Register**
3. Create an account with **purposefullymadekc@gmail.com** (use your real password)
4. After registering, you should see **Admin** in the header

**If you don't see Admin:**

- Log out and log back in
- Or visit: `https://purposefullymadekc.com/auth/promote-admin?token=any-secret-you-pick`
  - First add `ADMIN_PROMOTE_TOKEN=any-secret-you-pick` in Railway Variables
  - Redeploy
  - Visit that URL (replace `any-secret-you-pick` with what you set)
  - Log in when prompted

---

## Step 5: Sync products from S&S Activewear

1. Click **Admin** in the header
2. Click **Products** in the sidebar
3. Click **Sync from S&S Activewear**
4. Wait for the sync to finish — your products will appear in the shop

**If you don't see the Sync button:** Check that `SSACTIVEWEAR_API_KEY` and `SSACTIVEWEAR_ACCOUNT_NUMBER` are set correctly in Railway Variables.

---

## Step 6: Daily auto-sync (optional)

To have styles, colors, sizes, and inventory update automatically every day:

1. Add `SYNC_CRON_TOKEN` = any secret (e.g. `my-daily-sync-2024`) in Railway Variables
2. Go to [cron-job.org](https://cron-job.org) (free)
3. Create a job: URL = `https://purposefullymadekc.com/api/cron/sync-ss?token=my-daily-sync-2024`, schedule = Daily

See **DAILY_SYNC_SETUP.md** for full details.

---

## Step 7: Verify everything

- [ ] **Accounts persist** — Log out, redeploy, log back in. Your account should still exist.
- [ ] **Admin works** — You see Admin in the header when logged in as purposefullymadekc@gmail.com
- [ ] **Products show** — Shop page has products after syncing from S&S
- [ ] **Mockups show** — Product pages show images (from your uploads/mockups folder in the repo)

---

## Quick reference: what each variable does

| Variable | Purpose |
|----------|---------|
| `ADMIN_EMAIL` | This email gets admin access automatically |
| `SSACTIVEWEAR_API_KEY` | Lets you sync products from S&S |
| `SSACTIVEWEAR_ACCOUNT_NUMBER` | Your S&S account (required with API key) |
| `DATABASE_URL` | Set by Railway when you add PostgreSQL — don't add it yourself |
| `ADMIN_PROMOTE_TOKEN` | Optional — use promote URL if admin doesn't work automatically |

---

## Still stuck?

- **Accounts gone after deploy** → PostgreSQL not added or not linked. Re-do Step 1.
- **No Admin link** → Add `ADMIN_EMAIL` and use the promote URL (Step 4).
- **No products / No Sync button** → Add `SSACTIVEWEAR_API_KEY` and `SSACTIVEWEAR_ACCOUNT_NUMBER`.
- **502 or crash** → Check Railway Logs. Often missing `SECRET_KEY` or database connection.
