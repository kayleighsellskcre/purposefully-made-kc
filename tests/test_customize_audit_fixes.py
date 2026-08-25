"""Regression coverage for customize color selection + upload UX audit fixes."""


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


def test_upload_message_no_longer_mentions_reprocess():
    from services.image_processing import issue_messages
    msgs = issue_messages({'issues': ['background_may_remain']})
    assert msgs
    assert not any('reprocess' in m.lower() for m in msgs)
