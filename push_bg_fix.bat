@echo off
cd /d "C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site"
echo Committing background removal fix...
git add services/image_processing.py
git commit -m "Fix bg removal: BFS enclosed-region cleanup for letter holes inside 2, 3, A, B etc."
echo Pushing to GitHub...
git push origin main
echo.
echo Done! Railway will redeploy in ~1-2 minutes.
echo Then go to Admin - Design Gallery and click Fix Backgrounds on All Designs
pause
