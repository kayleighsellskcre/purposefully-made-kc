================================================================================
MOCKUP IMAGE UPLOAD INSTRUCTIONS - ALL STYLES
================================================================================

Each style has its own folder. Upload images for each style to its folder.

FOLDER STRUCTURE:
-----------------
uploads/mockups/3001/      - Jersey Tee (has images)
uploads/mockups/3001CVC/   - CVC Jersey Tee (has images)
uploads/mockups/3001Y/     - Youth Jersey Tee
uploads/mockups/3001YCVC/  - Youth CVC Jersey Tee
uploads/mockups/3413/      - Triblend Tee
uploads/mockups/3413Y/     - Youth Triblend Tee
uploads/mockups/3501/      - Jersey Long Sleeve Tee
uploads/mockups/3501CVC/   - Heather CVC Long Sleeve Tee
uploads/mockups/3501Y/     - Youth Jersey Long Sleeve Tee
uploads/mockups/3501YCVC/  - Youth Heather CVC Long Sleeve Tee
uploads/mockups/3513/      - Triblend Long Sleeve Tee
uploads/mockups/3513Y/     - Youth Triblend Long Sleeve Tee
uploads/mockups/3719/      - Sponge Fleece Hoodie
uploads/mockups/3719Y/     - Youth Sponge Fleece Hoodie
uploads/mockups/3729/      - Sponge Fleece Drop Shoulder Hoodie
uploads/mockups/3901/      - Sponge Fleece Raglan Crewneck
uploads/mockups/3901Y/     - Youth Sponge Fleece Crewneck
uploads/mockups/3945/      - Sponge Fleece Drop Shoulder Crewneck
uploads/mockups/4711/      - Heavyweight Crewneck Sweatshirt
uploads/mockups/4719/      - Heavyweight Hoodie
uploads/mockups/6400/      - Women's Relaxed Jersey Tee

NAMING FORMAT (for each style):
-------------------------------
STYLE_ColorName_view.jpg

Examples for 3413:
  3413_Athletic_Heather_front.jpg
  3413_Athletic_Heather_back.jpg
  3413_Black_front.jpg
  3413_Black_back.jpg

Examples for 4719:
  4719_Heather_Grey_front.jpg
  4719_Heather_Grey_back.jpg

Rules:
• Style number first (must match folder name)
• Color name with underscores for spaces
• View: front, back, or side
• Extension: .jpg, .jpeg, or .png

AFTER UPLOADING:
----------------
Run the import script for each style:
  python import_mockup_images.py 3413
  python import_mockup_images.py 3501
  (etc.)

Or run for all at once - ask for "import all mockups"

================================================================================
