@echo off
echo Saving newly uploaded design files to git...
cd /d "C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site"
if exist ".git\index.lock" del /f ".git\index.lock"

git add static/uploads/designs/
git add static/uploads/products/
git add static/uploads/custom_requests/

git diff --cached --quiet && (
    echo No new upload files to save.
) || (
    git commit -m "Save uploaded design files so they survive Railway redeploys"
    git push origin main
    echo.
    echo Done! Files are now safely in git and will survive future deploys.
)
pause
