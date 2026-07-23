@echo off
cd /d "C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site"
echo Committing group order updates...
git add routes/admin.py routes/collection.py templates/collection/share.html templates/admin/collections.html requirements.txt
git commit -m "Group orders: design isolation + Excel export

- Fix: designs uploaded for a group order are now is_gallery=False
  (private to that group only, never appear on the public gallery)
- Add openpyxl to requirements for Excel generation
- Add /c/<slug>/export.xlsx route: downloads a styled Excel workbook
  with 4 sheets: Summary, Orders, Line Items, Size Breakdown
  (accessible to admin + collection creator only)
- Add Export Excel button to admin/collections.html and share page"
echo Pushing to GitHub...
git push origin main
echo.
echo Done! Railway will redeploy in ~1-2 minutes.
echo Group order creators will now see a Download Order Spreadsheet button on their share page.
pause
