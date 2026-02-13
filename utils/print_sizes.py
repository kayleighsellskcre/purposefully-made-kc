"""Print width mapping by garment size for DTF/apparel production."""

# Print width in inches by size (user-provided mapping)
# Youth: YS 7.5", YM 8", YL 8.5", YXL 9" (youth runs smaller than adult)
# Adult: XS 9", S 9.5", M 10", L 10.5", XL 11", 2XL 11.25", 3XL+ 11.75"
SIZE_PRINT_WIDTH_ADULT = {
    'XS': 9.0, 'S': 9.5, 'M': 10.0, 'L': 10.5,
    'XL': 11.0, '2XL': 11.25, 'XXL': 11.25,
    '3XL': 11.75, 'XXXL': 11.75, '4XL': 11.75, '5XL': 11.75,
}
SIZE_PRINT_WIDTH_YOUTH = {
    'YS': 7.5, 'YM': 8.0, 'YL': 8.5, 'YXL': 9.0,
    # When youth product uses adult size labels (S, M, L, XL), map to youth dimensions
    'S': 7.5, 'M': 8.0, 'L': 8.5, 'XL': 9.0,
}
# Combined for backward compatibility
SIZE_PRINT_WIDTH = {**SIZE_PRINT_WIDTH_YOUTH, **SIZE_PRINT_WIDTH_ADULT}

# Map adult size labels to youth equivalents (for youth products)
ADULT_TO_YOUTH_SIZE = {'XS': 'YS', 'S': 'S', 'M': 'M', 'L': 'L', 'XL': 'XL'}


YOUTH_SIZE_PREFIXES = ('YS', 'YM', 'YL', 'YXL', 'YOUTH')


def _is_youth_size(size):
    """Check if size unambiguously indicates youth (YS, YM, YL, YXL or numeric 2-16).
    S, M, L, XL alone are ambiguous - use product name for those."""
    if not size:
        return False
    s = str(size).strip().upper()
    if s in ('YS', 'YM', 'YL', 'YXL'):
        return True
    if any(s.startswith(p) for p in YOUTH_SIZE_PREFIXES):
        return True
    # Numeric youth sizes (2, 4, 6, 8, 10, 12, 14, 16)
    if s in ('2', '4', '6', '8', '10', '12', '14', '16'):
        return True
    return False


def get_print_width_for_size(size, product=None):
    """Return print width in inches for a given size.
    Use youth dimensions (e.g. S=7.5", YS=7.5") when:
    - Product name contains 'youth', OR
    - Product category is 'Youth', OR
    - Size is a youth size (YS, YM, YL, YXL, or numeric 2-16).
    """
    if not size:
        return None
    s = str(size).strip().upper()
    product_name = (getattr(product, 'name', '') or '').lower() if product else ''
    product_category = (getattr(product, 'category', '') or '').lower() if product else ''
    is_youth = (
        (product and 'youth' in product_name) or
        (product and product_category == 'youth') or
        _is_youth_size(size)
    )

    if is_youth:
        # Youth product: use youth dimensions (S=7.5", M=8", etc.)
        if s in SIZE_PRINT_WIDTH_YOUTH:
            return SIZE_PRINT_WIDTH_YOUTH[s]
        size_map_youth = {
            'YOUTH SMALL': 7.5, 'YOUTH MEDIUM': 8.0, 'YOUTH LARGE': 8.5, 'YOUTH XL': 9.0,
        }
        if s in size_map_youth:
            return size_map_youth[s]
        # Fallback for numeric or unknown youth sizes
        if s in ('2', '4', '6', '8', '10', '12', '14', '16'):
            return 7.5  # Default youth logo size
        return 7.5  # Safe default for youth
    else:
        # Adult product
        if s in SIZE_PRINT_WIDTH_ADULT:
            return SIZE_PRINT_WIDTH_ADULT[s]
        size_map_adult = {
            'ADULT XSMALL': 9.0, 'ADULT SMALL': 9.5, 'ADULT MEDIUM': 10.0, 'ADULT LARGE': 10.5,
            'ADULT XLARGE': 11.0, 'ADULT XXLARGE': 11.25, 'ADULT XXXLARGE': 11.75,
        }
        if s in size_map_adult:
            return size_map_adult[s]
        if s.startswith('2') and 'XL' in s:
            return 11.25
        if any(s.startswith(x) for x in ('3', '4', '5')):
            return 11.75
    return None
