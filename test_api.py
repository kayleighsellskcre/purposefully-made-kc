"""
Test S&S Activewear API Connection
"""
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

print("="*80)
print("TESTING S&S ACTIVEWEAR API CONNECTION")
print("="*80)

# Check if API key is loaded
api_key = os.getenv('SSACTIVEWEAR_API_KEY')
account_num = os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER')

print(f"API Key found: {bool(api_key)}")
if api_key:
    print(f"API Key (first 20 chars): {api_key[:20]}...")
print(f"Account Number: {account_num}")
print()

if not api_key or api_key == 'your_ss_activewear_api_key_here':
    print("ERROR: API key not configured!")
    print("Add your real API key to the .env file")
    exit(1)

# Now test the actual connection
from services.ssactivewear_api import SSActivewearAPI

try:
    print("Initializing API client...")
    api = SSActivewearAPI()
    
    print("Testing connection by fetching categories...")
    categories = api.get_categories()
    
    if categories:
        print(f"SUCCESS! API connection working!")
        print(f"Found {len(categories)} categories")
        
        print("\nTesting Bella+Canvas product fetch...")
        styles = api.get_styles(brand_name='Bella+Canvas')
        print(f"Found {len(styles)} Bella+Canvas styles!")
        
        if styles:
            print("\nSample products:")
            for i, style in enumerate(styles[:5], 1):
                print(f"  {i}. {style.get('styleName')} (#{style.get('styleNumber')})")
        
        print("\n" + "="*80)
        print("API IS WORKING CORRECTLY!")
        print("="*80)
    else:
        print("WARNING: API connected but returned no data")
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
