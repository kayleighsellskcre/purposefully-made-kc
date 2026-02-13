"""
Batch rename mockup files from Printful format to our format

FROM: BELLA_+_CANVAS_3001CVC_Athletic_Heather_Back_High.jpg
TO:   3001CVC_Athletic_Heather_back.jpg
"""
import os
from pathlib import Path

upload_dir = Path('uploads/mockups/3001CVC')

if not upload_dir.exists():
    print(f"ERROR: Directory not found: {upload_dir}")
    exit(1)

print("="*80)
print("RENAMING MOCKUP FILES")
print("="*80)

renamed_count = 0
skipped_count = 0

for file in sorted(upload_dir.glob('*.jpg')) + sorted(upload_dir.glob('*.png')):
    old_name = file.name
    
    # Skip if already in correct format
    if old_name.startswith('3001CVC_'):
        print(f"[SKIP] Already renamed: {old_name}")
        skipped_count += 1
        continue
    
    # Remove BELLA_+_CANVAS_ prefix
    new_name = old_name.replace('BELLA_+_CANVAS_', '')
    
    # Remove _High suffix before extension
    new_name = new_name.replace('_High.jpg', '.jpg')
    new_name = new_name.replace('_High.png', '.png')
    
    # Convert Front/Back to lowercase
    new_name = new_name.replace('_Front.', '_front.')
    new_name = new_name.replace('_Back.', '_back.')
    new_name = new_name.replace('_Side.', '_side.')
    
    # Rename the file
    new_path = upload_dir / new_name
    file.rename(new_path)
    
    print(f"[OK] {old_name}")
    print(f"  -> {new_name}")
    renamed_count += 1

print("\n" + "="*80)
print("RENAMING COMPLETE!")
print("="*80)
print(f"[OK] Renamed: {renamed_count} files")
print(f"[SKIP] Skipped: {skipped_count} files")
print("\nNow run: .\\venv\\Scripts\\python import_mockup_images.py 3001CVC")
print("="*80)
