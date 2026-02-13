"""
Debug S&S API response structure
"""
import os
from dotenv import load_dotenv
load_dotenv()

from services.ssactivewear_api import SSActivewearAPI
import json

api = SSActivewearAPI()

print("Fetching first 2 Bella+Canvas styles...")
styles = api.get_styles(brand_name='Bella+Canvas')

if styles:
    print(f"\nTotal styles: {len(styles)}")
    print("\n" + "="*80)
    print("FIRST STYLE STRUCTURE:")
    print("="*80)
    print(json.dumps(styles[0], indent=2))
    
    print("\n" + "="*80)
    print("KEYS AVAILABLE:")
    print("="*80)
    print(list(styles[0].keys()))
    
    # Try to get style details
    style_id = styles[0].get('styleID') or styles[0].get('style_id') or styles[0].get('id')
    if style_id:
        print(f"\nFetching details for style ID: {style_id}")
        details = api.get_style_details(style_id)
        if details:
            print("\n" + "="*80)
            print("STYLE DETAILS STRUCTURE:")
            print("="*80)
            print(json.dumps(details, indent=2)[:1000])
else:
    print("No styles returned!")
