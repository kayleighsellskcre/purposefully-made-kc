@echo off
echo Pushing black background removal fixes to GitHub...
cd /d "C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site"
git add routes/cart.py services/image_processing.py
git commit -m "Fix black background not removed on shirt preview

- routes/cart.py: use _resolve_image_url() for gallery design URLs
  (was broken: f'/static/{file_path}' corrupts R2 https:// URLs)
- services/image_processing.py: boost flood-fill and color-key
  tolerances for near-black backgrounds (JPEG artifacts can shift
  pure-black pixels to 5-30 per channel, just outside default tol)
- services/image_processing.py: dark-background safety-net pass
  after standard cleanup: if dark opaque remnants remain, run a
  forced _remove_enclosed_bg with relaxed 85%% guard (was 40%%,
  which incorrectly skipped removal when main flood-fill failed)
- Run Fix All Backgrounds in admin to reprocess existing designs"
git push origin main
echo Done! Railway will redeploy automatically.
pause
