"""Curated SanMar bestsellers shown in the shop.

Hats (Richardson, New Era) are intentionally omitted until a cap/embroidery
flow exists. Only high-volume print-shop styles are listed.
"""

# Display name → SanMar getProductInfoByBrand spellings to try, then styles.
CURATED_BRANDS = [
    {
        'name': 'Bella+Canvas',
        'group': 'Everyday Favorite',
        'api_names': ['BELLA+CANVAS', 'Bella+Canvas', 'Bella + Canvas'],
        'styles': [
            'BC3001', '3001',           # Unisex jersey tee
            'BC3001CVC', '3001CVC',     # Heather CVC tee
            'BC3001Y', '3001Y',         # Youth tee
            'BC3001T', '3001T',         # Toddler tee
            'BC3001B', '3001B',         # Infant tee
            'BC100B', '100B',           # Infant onesie
            'BC3005', '3005',           # Unisex v-neck
            'BC3200', '3200',           # Baseball tee
            'BC3413', '3413',           # Triblend tee
            'BC3480', '3480',           # Unisex tank
            'BC3501', '3501',           # Long sleeve tee
            'BC3719', '3719',           # Pullover hoodie
            'BC3739', '3739',           # Full-zip hoodie
            'BC3901', '3901',           # Sweatshirt
            'BC6400', '6400',           # Women's relaxed tee
            'BC6400CVC', '6400CVC',
        ],
    },
    {
        'name': 'Comfort Colors',
        'group': 'Boutique / Premium',
        'api_names': ['Comfort Colors', 'COMFORT COLORS'],
        'styles': [
            '1717', 'C1717',            # Garment-dyed heavyweight tee
            '1567',                     # Garment-dyed long sleeve
            '9018',                     # Youth garment-dyed tee
            '1566',                     # Garment-dyed hoodie
            '6030',                     # Garment-dyed crew
        ],
    },
    {
        'name': 'Stanley/Stella',
        'group': 'Boutique / Premium',
        'api_names': ['Stanley/Stella', 'STANLEY/STELLA', 'Stanley Stella'],
        'styles': [
            'STTU755',                  # Creator tee
            'STSU823',                  # Drummer hoodie
            'STTW036',                  # Expresser women's tee
            'STTK184',                  # Mini Creator kids tee
        ],
    },
    {
        'name': 'Port & Company',
        'group': 'Budget-Friendly',
        'api_names': ['Port & Company', 'PORT & COMPANY', 'Port and Company'],
        'styles': [
            'PC54',                     # Core Cotton tee
            'PC61',                     # Essential tee
            'LPC54',                    # Ladies Core Cotton
            'YPC54',                    # Youth Core Cotton
            'PC78H',                    # Core Fleece hoodie
            'PC90H',                    # Essential Fleece hoodie
            'PC147',                    # Tie-Dye tee
            'PC147Y', 'YPC147',         # Youth Tie-Dye tee
            'LPC147V',                  # Ladies Tie-Dye v-neck
            'PC147LS',                  # Tie-Dye long sleeve
            'PC144',                    # Crystal Tie-Dye hoodie
            'PC145',                    # Crystal Tie-Dye tee
        ],
    },
    {
        'name': 'Sport-Tek',
        'group': 'Athletic',
        'api_names': ['Sport-Tek', 'SPORT-TEK', 'Sport Tek'],
        'styles': [
            'ST350',                    # PosiCharge Competitor tee
            'LST350',                   # Ladies Competitor
            'YST350',                   # Youth Competitor
            'ST350LS',                  # Competitor long sleeve
            'ST253',                    # Sport-Wick fleece hoodie
        ],
    },
    {
        'name': 'District',
        'group': 'Trendy',
        'api_names': ['District', 'DISTRICT'],
        'styles': [
            'DT6000',                   # Very Important Tee
            'DT6001',                   # Women's V.I.T.
            'DM130',                    # Perfect Tri tee
            'DT6100',                   # V.I.T. fleece hoodie
            'DT6104',                   # V.I.T. fleece crew
        ],
    },
    {
        'name': 'Rabbit Skins',
        'group': 'Baby / Toddler',
        'api_names': ['Rabbit Skins', 'RABBIT SKINS', 'RabbitSkins'],
        'styles': [
            '3321', 'RS3321',           # Infant onesie
            '3322', 'RS3322',           # Infant long-sleeve onesie
            '3316', 'RS3316',           # Infant tee
            '3317', 'RS3317',           # Infant long-sleeve tee
            '3301', 'RS3301',           # Toddler tee
        ],
    },
    {
        'name': 'Gildan',
        'group': 'Sweatshirt Basics',
        'api_names': ['Gildan', 'GILDAN'],
        'styles': [
            'G64000', 'G64500', 'G64400',   # Softstyle tee, v-neck, long sleeve
            'G180', 'G18000',               # Heavy Blend hoodie
            'G185', 'G18000C',              # Heavy Blend crew
            'G186',                         # Heavy Blend full-zip
            'G180B', 'G18500B',             # Youth hoodie
            'G185B',                        # Youth crew
        ],
    },
    {
        'name': 'MV Sport',
        'group': 'Athletic / Lifestyle',
        'api_names': ['MV Sport', 'MV SPORT'],
        'styles': [
            '17116',    # Vintage Fleece Raglan Crewneck
            'W23716',   # Women's Colorblocked Crop Hoodie
            'W25167',   # Women's Coastal Color Crewneck
            '496',      # Pro-Weave Crewneck
        ],
    },
    {
        'name': 'C2 Sport',
        'group': 'Athletic / Performance',
        'api_names': ['C2 Sport', 'C2 SPORT'],
        'styles': [
            '5100',     # Unisex Performance Tee
            '5600',     # Women's Performance Tee
            '5200',     # Youth Performance Tee
            '5104',     # Unisex Performance Long Sleeve
        ],
    },
]


def shop_brand_names():
    return [brand['name'] for brand in CURATED_BRANDS]


def all_allowed_styles():
    styles = []
    for brand in CURATED_BRANDS:
        styles.extend(brand['styles'])
    return styles
