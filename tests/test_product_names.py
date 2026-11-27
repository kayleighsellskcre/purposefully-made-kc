from utils.product_names import display_product_name


def test_display_product_name_drops_registered_mark_and_style_code():
    assert display_product_name(
        'BELLA+CANVAS \u00ae Unisex Jersey Long Sleeve Tee. BC3501',
        'BC3501',
    ) == 'BELLA+CANVAS Unisex Jersey Long Sleeve Tee'
    assert display_product_name(
        'BELLA+CANVAS\u00ae Unisex Heather CVC V-Neck Tee BC3005CVC',
        'BC3005CVC',
    ) == 'BELLA+CANVAS Unisex Heather CVC V-Neck Tee'


def test_display_product_name_keeps_brand_when_there_is_no_style_suffix():
    assert display_product_name(
        'Comfort Colors Garment-Dyed Heavyweight Tee'
    ) == 'Comfort Colors Garment-Dyed Heavyweight Tee'
    assert display_product_name("Port & Company Women's Tie-Dye V-Neck Tee") == (
        "Port & Company Women's Tie-Dye V-Neck Tee"
    )


def test_display_product_name_reads_style_from_product_object():
    class Product:
        name = 'BELLA+CANVAS \u00ae Unisex Jersey Short Sleeve Tee. BC3001'
        style_number = 'BC3001'

    assert display_product_name(Product()) == (
        'BELLA+CANVAS Unisex Jersey Short Sleeve Tee'
    )


def test_design_label_does_not_double_the_word_design():
    from utils.product_names import design_label
    assert design_label('Lion of Judah') == 'Lion of Judah design'
    assert design_label('My Design 538') == 'My Design 538'
    assert design_label('') == ''


def test_shop_title_matches_the_shop_card():
    from utils.product_names import shop_title

    class Product:
        name = 'BELLA+CANVAS ® Unisex Jersey Short Sleeve Tee. BC3001'
        style_number = 'BC3001'
        brand = 'Bella+Canvas'

    assert shop_title(Product()) == 'Unisex Jersey Short Sleeve Tee'
