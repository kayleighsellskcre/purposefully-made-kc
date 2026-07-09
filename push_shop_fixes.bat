@echo off
cd /d "C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site"
if exist ".git\index.lock" del /f ".git\index.lock"
git add templates/admin/design_gallery.html
git add templates/admin/gallery_queue.html
git add static/uploads/
git commit -m "Fix: gallery delete modal CSS missing; commit any new upload files"
git push origin main
echo.
echo Done!
pause
