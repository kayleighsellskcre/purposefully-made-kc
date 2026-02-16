"""
S&S Activewear API Integration
Syncs product catalog, colors, sizes, and inventory from S&S Activewear
"""
import requests
import json
from datetime import datetime
import os
from urllib.parse import urlparse
from pathlib import Path


class SSActivewearAPI:
    """S&S Activewear API client"""
    
    def __init__(self, api_key=None, account_number=None, api_url=None):
        self.api_key = str(api_key or os.getenv('SSACTIVEWEAR_API_KEY') or '').strip()
        self.account_number = str(account_number or os.getenv('SSACTIVEWEAR_ACCOUNT_NUMBER') or '').strip()
        self.api_url = (api_url or os.getenv('SSACTIVEWEAR_API_URL') or 'https://api.ssactivewear.com').rstrip('/')
        
        if not self.api_key:
            raise ValueError("S&S Activewear API key not configured. Add SSACTIVEWEAR_API_KEY to .env")
        
        if not self.account_number:
            raise ValueError("S&S Activewear account number not configured. Add SSACTIVEWEAR_ACCOUNT_NUMBER to .env")
        
        # S&S API uses Basic Auth: username=account_number, password=api_key
        import base64
        credentials = f"{self.account_number}:{self.api_key}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        self.headers = {
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/json'
        }
    
    def get_styles(self, brand_name='Bella+Canvas'):
        """
        Get all styles for a specific brand
        
        Args:
            brand_name: Brand name (default: Bella+Canvas)
        
        Returns:
            List of style dictionaries
        """
        try:
            endpoint = f"{self.api_url}/v2/styles"
            params = {'brandName': brand_name} if brand_name else {}

            response = requests.get(endpoint, auth=(self.account_number, self.api_key), params=params, timeout=60)

            if response.status_code == 401:
                raise ValueError("Invalid S&S API credentials (401). Check SSACTIVEWEAR_API_KEY and SSACTIVEWEAR_ACCOUNT_NUMBER in Railway.")
            if response.status_code == 403:
                raise ValueError("S&S API access denied (403). Your account may not have API access enabled.")
            response.raise_for_status()

            data = response.json()
            if isinstance(data, list):
                return data
            for key in ('Styles', 'styles', 'data'):
                if key in data and isinstance(data[key], list):
                    return data[key]
            return []
        except requests.exceptions.RequestException as e:
            err_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    body = e.response.text[:200] if e.response.text else ''
                    err_msg = f"{err_msg} | Response: {body}"
                except Exception:
                    pass
            print(f"Error fetching styles from S&S API: {err_msg}")
            raise ValueError(f"S&S API error: {err_msg}")
    
    def get_style_details(self, style_id):
        """
        Get detailed information for a specific style including all colors, sizes, and inventory
        
        Args:
            style_id: Style ID from S&S (e.g., 9182)
        
        Returns:
            Style details dictionary with colors, sizes, and color_variants with inventory
        """
        import sys
        
        try:
            # Get basic style info
            endpoint = f"{self.api_url}/v2/styles/{style_id}"
            response = requests.get(endpoint, auth=(self.account_number, self.api_key), timeout=30)
            response.raise_for_status()
            style_data = response.json()
            
            # If it's a list, get first item
            if isinstance(style_data, list) and len(style_data) > 0:
                style_data = style_data[0]
            
            print(f"  Getting SKUs for style {style_id}...", file=sys.stderr, flush=True)
            
            # Now get all color/size variations (SKUs) with inventory
            endpoint = f"{self.api_url}/v2/products"
            params = {'styleID': style_id}
            response = requests.get(endpoint, auth=(self.account_number, self.api_key), params=params, timeout=30)
            response.raise_for_status()
            products = response.json()
            
            print(f"  Got {len(products) if isinstance(products, list) else 0} SKUs", file=sys.stderr, flush=True)
            
            # Organize by color with sizes and inventory DIRECTLY from products endpoint
            color_variants = {}
            all_colors = set()
            all_sizes = set()
            
            if isinstance(products, list):
                for product in products:
                    color_name = product.get('colorName')
                    size_name = product.get('sizeName')
                    sku = product.get('sku', '')
                    color_id = product.get('colorID')
                    
                    # Get inventory from product object directly
                    # S&S API includes qty in the products endpoint
                    qty = product.get('qty', 0) or product.get('inventory', 0) or product.get('availableQty', 0)
                    
                    # Get mockup images for this color
                    front_image = product.get('frontImage') or product.get('frontmodel')
                    back_image = product.get('backImage') or product.get('backmodel')
                    side_image = product.get('sideImage')
                    
                    if color_name:
                        all_colors.add(color_name)
                        
                        # Initialize color variant if not exists
                        if color_name not in color_variants:
                            color_variants[color_name] = {
                                'color_name': color_name,
                                'color_id': color_id,
                                'front_image': front_image,
                                'back_image': back_image,
                                'side_image': side_image,
                                'sizes': {}
                            }
                        
                        # Add size and inventory
                        if size_name:
                            all_sizes.add(size_name)
                            # Use the qty from products endpoint directly
                            color_variants[color_name]['sizes'][size_name] = qty
                            print(f"    {color_name} - {size_name}: {qty} units", file=sys.stderr, flush=True)
            
            total_colors = len(color_variants)
            total_inventory = sum(sum(v['sizes'].values()) for v in color_variants.values())
            print(f"  Organized into {total_colors} colors with {total_inventory} total units", file=sys.stderr, flush=True)
            
            # Add organized data to style_data
            style_data['colors'] = sorted(list(all_colors))
            style_data['sizes'] = sorted(list(all_sizes), key=lambda x: ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL'].index(x) if x in ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL'] else 999)
            style_data['color_variants'] = list(color_variants.values())
            
            return style_data
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching style {style_id} from S&S API: {e}", file=sys.stderr, flush=True)
            return None
    
    def get_products_by_style_number(self, style_number):
        """
        Fetch all products (SKUs) for a specific style by style number.
        Uses /v2/products/?style= or ?partnumber= - works even when full catalog fails.
        
        Args:
            style_number: Style number e.g. "3001", "3001CVC"
        
        Returns:
            List of product SKU dicts, or empty list if not found
        """
        try:
            endpoint = f"{self.api_url}/v2/products"
            # Try multiple identifiers - S&S uses different formats per brand
            attempts = [
                ('partnumber', style_number),
                ('style', style_number),
                ('style', f'bella + canvas {style_number}'),  # Full style name for Bella+Canvas
            ]
            for param_name, param_value in attempts:
                try:
                    params = {param_name: param_value}
                    response = requests.get(endpoint, auth=(self.account_number, self.api_key), params=params, timeout=60)
                    if response.status_code == 401:
                        raise ValueError("Invalid S&S API credentials (401).")
                    if response.status_code == 403:
                        raise ValueError("S&S API access denied (403).")
                    response.raise_for_status()
                    data = response.json()
                    products = data if isinstance(data, list) else data.get('products', data.get('data', []))
                    if products and isinstance(products, list):
                        return products
                except requests.exceptions.HTTPError:
                    continue  # 404 or similar - try next identifier
            return []
        except ValueError:
            raise
        except requests.exceptions.RequestException as e:
            print(f"Error fetching products for style {style_number}: {e}")
            return []

    def get_style_by_part_number(self, part_number):
        """
        Fetch style metadata (title, description, sizing) by part number.
        /v2/styles/?partnumber=3001
        """
        try:
            endpoint = f"{self.api_url}/v2/styles"
            params = {'partnumber': part_number}
            response = requests.get(endpoint, auth=(self.account_number, self.api_key), params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            styles = data if isinstance(data, list) else data.get('Styles', data.get('styles', []))
            if styles and isinstance(styles, list) and len(styles) > 0:
                return styles[0]
            return None
        except Exception:
            return None

    def get_style_spec_sheet(self, style_id):
        """
        Fetch detailed spec sheet for a style including size chart, fabric details, etc.
        /v2/styles/{styleID}/specsheet
        """
        try:
            endpoint = f"{self.api_url}/v2/styles/{style_id}/specsheet"
            response = requests.get(endpoint, auth=(self.account_number, self.api_key), timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def get_inventory(self, style_id=None, style_number=None, warehouse=None):
        """
        Get real-time inventory levels
        
        Args:
            style_id: Optional style ID to filter
            style_number: Optional style number to filter
            warehouse: Optional warehouse code to filter
        
        Returns:
            List of inventory records
        """
        try:
            endpoint = f"{self.api_url}/v2/inventory"
            
            params = {}
            if style_id:
                params['styleID'] = style_id
            elif style_number:
                params['styleNumber'] = style_number
            if warehouse:
                params['warehouse'] = warehouse
            
            response = requests.get(endpoint, auth=(self.account_number, self.api_key), params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            # Return as list
            if isinstance(data, list):
                return data
            return []
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching inventory from S&S API: {e}")
            return []
    
    def get_categories(self):
        """Get all product categories"""
        try:
            endpoint = f"{self.api_url}/v2/categories"
            response = requests.get(endpoint, auth=(self.account_number, self.api_key), timeout=30)
            response.raise_for_status()
            data = response.json()
            # API returns list directly
            return data if isinstance(data, list) else []
        except requests.exceptions.RequestException as e:
            print(f"Error fetching categories from S&S API: {e}")
            return []
    
    def download_product_image(self, image_url, style_number, view='front'):
        """
        Download product image from S&S API
        
        Args:
            image_url: URL of the image
            style_number: Product style number
            view: 'front' or 'back'
        
        Returns:
            Local file path or None
        """
        try:
            # Create products directory if it doesn't exist
            upload_dir = Path('static/uploads/products')
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            # Download image
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
            
            # Get file extension from URL
            parsed = urlparse(image_url)
            ext = Path(parsed.path).suffix or '.jpg'
            
            # Save with style number and view
            filename = f"{style_number}_{view}{ext}"
            filepath = upload_dir / filename
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            # Return path relative to static folder
            return f"uploads/products/{filename}"
            
        except Exception as e:
            print(f"Error downloading image from {image_url}: {e}")
            return None
    
    def fetch_style_data_by_style_number(self, style_number):
        """
        Fetch full style data (colors, sizes, inventory, descriptions, sizing) for a style by its number.
        Uses Products API directly - works when full catalog sync fails.
        
        Returns:
            Style dict in same format as get_style_details, or None
        """
        products = self.get_products_by_style_number(style_number)
        if not products:
            return None

        # Build style_data from products
        first = products[0]
        style_id = first.get('styleID')
        style_name = first.get('styleName', style_number)
        brand_name = first.get('brandName', 'Bella+Canvas')

        # Get style metadata (title, description, sizing) if available
        meta = self.get_style_by_part_number(style_number) or {}
        title = meta.get('title', first.get('styleName', style_number))
        description = meta.get('description', first.get('description', ''))
        
        # Get sizing/spec sheet data
        spec_sheet = None
        if style_id:
            spec_sheet = self.get_style_spec_sheet(style_id)

        color_variants = {}
        all_colors = set()
        all_sizes = set()
        size_order = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL']

        for p in products:
            color_name = p.get('colorName')
            size_name = p.get('sizeName')
            qty = p.get('qty', 0) or p.get('inventory', 0) or 0
            if not color_name:
                continue
            all_colors.add(color_name)
            if color_name not in color_variants:
                color_variants[color_name] = {
                    'color_name': color_name,
                    'color_id': p.get('colorID'),
                    'front_image': p.get('colorFrontImage') or p.get('frontImage'),
                    'back_image': p.get('colorBackImage') or p.get('backImage'),
                    'side_image': p.get('colorSideImage'),
                    'sizes': {}
                }
            if size_name:
                all_sizes.add(size_name)
                color_variants[color_name]['sizes'][size_name] = int(qty)

        sizes = sorted(all_sizes, key=lambda x: size_order.index(x) if x in size_order else 999)
        style_data = {
            'styleID': style_id,
            'styleName': style_name,
            'styleNumber': style_number,
            'brandName': brand_name,
            'title': title,
            'description': description,
            'baseCategory': meta.get('baseCategory', 'T-Shirts'),
            'colors': sorted(list(all_colors)),
            'sizes': sizes,
            'color_variants': list(color_variants.values()),
            'spec_sheet': spec_sheet,  # NEW: spec sheet with sizing
            'fit_guide': meta.get('fitType', ''),
            'fabric': meta.get('fabric', ''),
        }
        # Add wholesale from first product with price
        for p in products:
            price = p.get('customerPrice') or p.get('piecePrice') or p.get('mapPrice')
            if price is not None:
                style_data['wholesalePrice'] = float(price)
                break
        if 'wholesalePrice' not in style_data:
            style_data['wholesalePrice'] = 10
        return style_data

    def parse_style_to_product(self, style_data):
        """
        Convert S&S API style data to our Product model format
        
        Args:
            style_data: Raw style data from S&S API
        
        Returns:
            Dictionary compatible with Product model
        """
        # S&S API uses 'styleName' as the style number (e.g., "3001")
        style_number = style_data.get('styleName', '') or style_data.get('styleNumber', '')
        
        # Extract colors - might be in different formats
        colors = []
        if 'colors' in style_data:
            colors = style_data['colors']
        elif 'Colors' in style_data:
            colors = [color.get('colorName', '') for color in style_data['Colors']]
        
        # Extract sizes
        sizes = []
        if 'sizes' in style_data:
            sizes = style_data['sizes']
        elif 'Sizes' in style_data:
            sizes = list(set([size.get('sizeName', '') for size in style_data['Sizes']]))
        
        # Sort sizes in logical order
        if sizes:
            size_order = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL']
            sizes = sorted(sizes, key=lambda x: size_order.index(x) if x in size_order else 999)
        
        # Determine category from baseCategory
        base_category = style_data.get('baseCategory', '')
        title = style_data.get('title', '').lower()
        
        if 'hoodie' in title or 'hoodie' in base_category.lower():
            category = 'Hoodie'
        elif 'sweatshirt' in title or 'crew' in title:
            category = 'Sweatshirt'
        elif 'tank' in title:
            category = 'Tank'
        elif 'long sleeve' in title:
            category = 'Long Sleeve'
        elif 'tee' in title or 't-shirt' in title:
            category = 'Tee'
        else:
            category = 'Tee'
        
        # Get pricing - default markup of 2.5x if no price
        wholesale_price = style_data.get('wholesalePrice', 10)
        retail_price = wholesale_price * 2.5
        
        # Get style image from S&S
        front_image = None
        style_image_url = style_data.get('styleImage')
        if style_image_url:
            # Download from S&S CDN
            full_url = f"https://cdn.ssactivewear.com/{style_image_url}"
            front_image = self.download_product_image(full_url, style_number, 'front')
        
        # Process color variants with mockup images and inventory
        color_variants_data = []
        if 'color_variants' in style_data:
            for variant in style_data['color_variants']:
                color_variants_data.append({
                    'color_name': variant['color_name'],
                    'color_id': variant['color_id'],
                    'front_image': variant.get('front_image'),
                    'back_image': variant.get('back_image'),
                    'side_image': variant.get('side_image'),
                    'size_inventory': json.dumps(variant.get('sizes', {}))  # {"S": 45, "M": 120, etc}
                })
        
        return {
            'style_number': style_number,
            'name': f"{style_data.get('brandName', 'Bella+Canvas')} {style_data.get('title', style_number)}",
            'category': category,
            'description': style_data.get('description', ''),
            'base_price': round(retail_price, 2),
            'wholesale_cost': round(wholesale_price, 2),
            'available_sizes': json.dumps(sizes) if sizes else json.dumps(['S', 'M', 'L', 'XL']),
            'available_colors': json.dumps(colors) if colors else json.dumps(['Black', 'White']),
            'is_active': True,
            'brand': style_data.get('brandName', 'Bella+Canvas'),
            'front_mockup_template': front_image,
            'back_mockup_template': None,  # Back images can be added later
            'color_variants': color_variants_data,  # NEW: Color-specific images + inventory
            # NEW: Sizing and fabric information
            'size_chart': json.dumps(style_data.get('spec_sheet')) if style_data.get('spec_sheet') else None,
            'fit_guide': style_data.get('fit_guide', ''),
            'fabric_details': style_data.get('fabric', ''),
            # Store raw API data for reference
            'api_data': json.dumps({
                'last_synced': datetime.utcnow().isoformat(),
                'style_id': style_data.get('styleID'),
                'ss_data': style_data
            })
        }
    
    def sync_bella_canvas_catalog(self, limit=None):
        """
        Sync entire Bella+Canvas catalog from S&S
        
        Args:
            limit: Optional limit on number of styles to sync (for testing)
        
        Returns:
            List of parsed product dictionaries
        """
        import sys
        print("="*80, file=sys.stderr, flush=True)
        print("FETCHING STYLES FROM S&S...", file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)
        
        # Quick connectivity test first
        try:
            cats = self.get_categories()
            print(f"API connection OK (categories: {len(cats) if cats else 0})", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"API connection test failed: {e}", file=sys.stderr, flush=True)
            raise

        styles = self.get_styles(brand_name='Bella+Canvas')
        # Fallback: if brand filter returns nothing, try fetching all styles
        if not styles:
            print("No styles with brand filter, trying all styles...", file=sys.stderr, flush=True)
            styles = self.get_styles(brand_name='')
        if not styles:
            print("ERROR: No styles returned from API!", file=sys.stderr, flush=True)
            raise ValueError("S&S API returned no styles. Check: 1) API key and account number are correct, 2) Your S&S account has API access enabled at ssactivewear.com.")
        print(f"RAW STYLES RETURNED: {len(styles) if styles else 0}", file=sys.stderr, flush=True)
        
        # Filter for Bella+Canvas only (API returns mixed brands)
        bella_canvas_styles = [s for s in styles if 'bella' in s.get('brandName', '').lower() and 'canvas' in s.get('brandName', '').lower()]
        print(f"FILTERED TO {len(bella_canvas_styles)} BELLA+CANVAS STYLES", file=sys.stderr, flush=True)
        
        if limit:
            print(f"LIMITING TO {limit} PRODUCTS", file=sys.stderr, flush=True)
            bella_canvas_styles = bella_canvas_styles[:limit]
        
        print(f"PROCESSING {len(bella_canvas_styles)} STYLES", file=sys.stderr, flush=True)
        
        products = []
        for i, style in enumerate(bella_canvas_styles, 1):
            # S&S uses 'styleID' for API calls and 'styleName' as the style number
            style_id = style.get('styleID')
            style_name = style.get('styleName')
            
            print(f"  [{i}/{len(bella_canvas_styles)}] {style_name} (ID: {style_id})", file=sys.stderr, flush=True)
            
            # Get detailed information using styleID
            style_details = self.get_style_details(style_id)
            if style_details:
                # style_details might be a list, get first item
                if isinstance(style_details, list) and len(style_details) > 0:
                    style_details = style_details[0]
                
                product_data = self.parse_style_to_product(style_details)
                products.append(product_data)
                print(f"    ✓ Processed", file=sys.stderr, flush=True)
            else:
                print(f"    WARNING: No details for {style_name}", file=sys.stderr, flush=True)
        
        print(f"SUCCESSFULLY PROCESSED {len(products)} PRODUCTS", file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)
        return products

    def sync_mockup_styles(self, style_numbers=None):
        """
        Sync only styles that have mockup folders. Fetches each style directly from
        S&S Products API - works even when full catalog returns nothing.
        
        Args:
            style_numbers: Optional list of style numbers. If None, discovers from
                           uploads/mockups/ and static/uploads/mockups/
        
        Returns:
            List of parsed product dicts (same format as sync_bella_canvas_catalog)
        """
        import sys
        from pathlib import Path

        if style_numbers is None:
            styles = set()
            for base in (Path('uploads/mockups'), Path('static/uploads/mockups')):
                if base.is_dir():
                    for p in base.iterdir():
                        if p.is_dir() and not p.name.startswith('.'):
                            styles.add(p.name)
            style_numbers = sorted(styles)

        if not style_numbers:
            print("No mockup style folders found.", file=sys.stderr, flush=True)
            return []

        print("="*80, file=sys.stderr, flush=True)
        print(f"SYNCING {len(style_numbers)} MOCKUP STYLES FROM S&S", file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)

        products = []
        for i, style_num in enumerate(style_numbers, 1):
            print(f"  [{i}/{len(style_numbers)}] {style_num}...", file=sys.stderr, flush=True)
            style_data = self.fetch_style_data_by_style_number(style_num)
            if style_data:
                product_data = self.parse_style_to_product(style_data)
                products.append(product_data)
                print(f"    ✓ {len(style_data.get('colors', []))} colors, {len(style_data.get('sizes', []))} sizes", file=sys.stderr, flush=True)
            else:
                print(f"    ✗ Not found in S&S", file=sys.stderr, flush=True)

        print(f"SYNCED {len(products)} PRODUCTS", file=sys.stderr, flush=True)
        print("="*80, file=sys.stderr, flush=True)
        return products


def test_api_connection():
    """Test S&S API connection and credentials"""
    try:
        api = SSActivewearAPI()
        print("Testing S&S Activewear API connection...")
        print(f"API URL: {api.api_url}")
        
        # Try to fetch categories as a simple test
        categories = api.get_categories()
        
        if categories:
            print("✓ API connection successful!")
            print(f"Found {len(categories)} categories")
            return True
        else:
            print("✗ API connection failed - no data returned")
            return False
            
    except Exception as e:
        print(f"✗ API connection failed: {e}")
        return False


if __name__ == '__main__':
    # Run test when executed directly
    test_api_connection()
