@echo off
cd /d "C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site"
if exist ".git\index.lock" del /f ".git\index.lock"
git remote set-url origin git@github.com:kayleighsellskcre/purposefully-made-kc.git
git push origin main
echo.
echo Done! Railway will auto-deploy.
pause
