# Daily S&S Activewear Sync

Your site can automatically sync styles, colors, sizes, and inventory from S&S Activewear every day.

---

## Step 1: Add the cron token in Railway

1. Railway → your **kb_apparel_site** service → **Variables**
2. Add: `SYNC_CRON_TOKEN` = any secret string (e.g. `my-daily-sync-secret-2024`)
3. Redeploy

---

## Step 2: Set up a daily cron job

Use a free service like [cron-job.org](https://cron-job.org) or [EasyCron](https://www.easycron.com):

1. Create an account
2. Add a new cron job:
   - **URL:** `https://purposefullymadekc.com/api/cron/sync-ss?token=YOUR_SYNC_CRON_TOKEN`
   - **Schedule:** Daily (e.g. 3:00 AM or 6:00 AM)
   - **Request method:** GET

3. Save

Every day at the scheduled time, the job will sync **only styles that have mockup folders** in `uploads/mockups/` (e.g. 3001, 3001CVC). Each style is fetched directly from S&S with live colors, sizes, and inventory.

---

## Step 3: Verify it works

After the first run:

1. Check your shop — products should appear with correct colors and sizes
2. Check product pages — inventory counts should show for each size
3. In cron-job.org, check the job's execution history for success/failure

---

## Manual sync

You can also trigger a sync manually:

- **From Admin:** Admin → Products → "Sync from S&S Activewear" (syncs only styles in uploads/mockups/)
- **From URL:** Visit `https://purposefullymadekc.com/api/cron/sync-ss?token=YOUR_SYNC_CRON_TOKEN` in your browser (you'll see a JSON response)

---

## Troubleshooting

- **401 Unauthorized:** Wrong or missing `SYNC_CRON_TOKEN`
- **"No products returned":** Check `SSACTIVEWEAR_API_KEY` and `SSACTIVEWEAR_ACCOUNT_NUMBER` in Railway
- **"Invalid credentials (401)":** 
  - Get a fresh API key at ssactivewear.com → My Account → API Access
  - Use your **account number** (numeric), not customer ID
  - Ensure no extra spaces when pasting into Railway
- **Sync works in Admin but cron fails:** Check the cron job URL has the correct token
