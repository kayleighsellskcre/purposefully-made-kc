@echo off
cd /d "C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site"
if exist ".git\index.lock" del /f ".git\index.lock"
git add routes/shop.py
git add templates/checkout/index.html
git add push_shop_fixes.bat
git add save_uploads.bat
git commit -m "Improve checkout UX and shop color filter; save utility scripts"
git push origin main
echo.
echo Done!
pause
