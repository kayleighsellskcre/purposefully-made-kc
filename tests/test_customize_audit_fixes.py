"""Regression coverage for customize color selection + upload UX audit fixes."""


def test_customize_design_picker_includes_music_without_genre_menus(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'data-tab="Music"' in html
    assert 'Faith &amp; Inspiration' in html
    assert 'Kansas City' in html
    assert 'Country &amp; Western' not in html
    assert 'Rock &amp; Roll' not in html
    assert 'Soul/Blues/Jazz' not in html


def test_customize_has_no_reprocess_stronger_cut(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'reprocessDesign' not in html
    assert 'Reprocess (stronger cut)' not in html
    assert 'Reprocess (Stronger Cut)' not in html


def test_customize_does_not_delay_auto_color_click(client, seed):
    """First-click race: delayed firstColor.click() used to overwrite the customer."""
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'firstColor.click()' not in html
    assert 'setTimeout(() => {\n                firstColor.click()' not in html
    assert 'selectColor(firstColor)' in html
    assert '_mockupGen' in html


def test_product_detail_color_swatches_carry_images(client, seed):
    html = client.get(f'/shop/product/{seed["tee_id"]}').get_data(as_text=True)
    assert 'data-front-image=' in html
    assert 'color-option' in html
    assert 'color-swatch' in html
    assert 'color-swatch-name' in html
    assert 'Black' in html
    assert 'White' in html


def test_customize_does_not_render_empty_design_overlays(client, seed):
    html = client.get(f'/shop/customize/{seed["tee_id"]}').get_data(as_text=True)
    assert 'alt="Design"' not in html
    assert 'alt="Back Design"' not in html
    assert 'id="designImage" hidden' in html
    assert 'id="backDesignImage" hidden' in html
    assert 'src="" alt="Design"' not in html
    assert 'src="" alt="Back Design"' not in html


def test_product_detail_main_photo_shows_the_whole_garment(client, seed):
    html = client.get(f'/shop/product/{seed["tee_id"]}').get_data(as_text=True)
    assert '.product-image img' in html
    assert 'object-fit: contain' in html


def test_product_detail_thumbnails_use_the_selected_color(client, seed):
    html = client.get(f'/shop/product/{seed["tee_id"]}').get_data(as_text=True)
    assert 'id="thumbFront"' in html
    assert 'alt="Front of' in html
    assert 'thumbFront.src = front' in html
    assert 'thumbBackBtn.hidden' in html


def test_upload_message_no_longer_mentions_reprocess():
    from services.image_processing import issue_messages
    msgs = issue_messages({'issues': ['background_may_remain']})
    assert msgs
    assert not any('reprocess' in m.lower() for m in msgs)
