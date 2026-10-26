"""The three ways to pay are explained the same, accurate way everywhere, and the sponsor wording fits any group."""
import glob
import re
from html import unescape

from tests.conftest import CUSTOMER_EMAIL
from utils.group_orders import PAYMENT_OPTIONS


def _text(html):
    html = re.sub(r'<(script|style)\b.*?</\1>|<!--.*?-->', '', html, flags=re.S)
    return unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)))


def test_the_three_options_say_who_chooses_and_who_pays(guest):
    each, whole, sponsor = PAYMENT_OPTIONS
    assert 'chooses which styles and options are available' in each['text'] and 'pays for their own items' in each['text']
    assert 'one style, color and design' in whole['text'] and 'names and sizes' in whole['text'] and 'full roster' in whole['text']
    assert 'set number of items' in sponsor['text'] and 'limit per item' in sponsor['text']
    assert 'extras' in sponsor['text'] and 'sponsor invoice before covered items are printed' in sponsor['text']
    assert 'choose their own' not in whole['text']          # an organizer-paid order does not let shoppers pick items


def test_front_door_setup_form_and_faq_use_the_same_words(client, customer_client):
    door = _text(customer_client.get('/shop/group-orders').get_data(as_text=True))
    form = _text(customer_client.get('/shop/group-orders/create').get_data(as_text=True))
    for opt in PAYMENT_OPTIONS:
        assert opt['text'] in door and opt['title'] in door, opt['key']
        assert opt['text'] in form and opt['title'] in form, opt['key']
        assert f"{opt['who']}: {opt['text']}" in door, opt['key']        # the FAQ list


def test_the_old_individual_only_wording_is_gone(client):
    door = _text(client.get('/shop/group-orders').get_data(as_text=True))
    assert "You don't collect money yourself" not in door
    assert 'Everyone orders their own' not in door
    assert 'pay your own way' not in door
    assert "follow that store's instructions for choosing and paying" in door
    assert 'Everyone joins in' in door and 'send in their sizes for you to pay' in door


def test_the_faq_payment_answer_is_a_short_list(client):
    html = client.get('/shop/group-orders').get_data(as_text=True)
    block = html.split('How does payment work?')[1].split('How long does it take?')[0]
    assert block.count('<li>') == 3 and '<ul class="faq-list">' in block


def test_each_setup_button_has_its_own_accessible_name_and_the_same_look(client):
    html = client.get('/shop/group-orders').get_data(as_text=True)
    labels = re.findall(r'class="btn btn-primary" aria-label="([^"]+)">Start a group order<', html)
    assert labels == ['Start an order where each person pays', 'Start an organizer-paid order',
                      'Start a sponsor-covered order']
    assert len(set(labels)) == 3


def test_each_button_opens_its_own_mode(customer_client):
    html = customer_client.get('/shop/group-orders').get_data(as_text=True)
    assert 'href="/shop/group-orders/create"' in html
    assert 'href="/shop/group-orders/create?mode=whole"' in html and 'href="/shop/group-orders/create?mode=amount"' in html
    for mode, checked in (('', 'each_pays'), ('?mode=whole', 'organizer_pays'), ('?mode=amount', 'company_sponsored')):
        page = customer_client.get('/shop/group-orders/create' + mode).get_data(as_text=True)
        assert f'value="{checked}" checked' in page, mode
        assert page.count('type="radio" name="payment_mode"') == 3


def test_sponsor_screens_talk_about_a_sponsor_and_shoppers_not_a_company_and_employees():
    files = glob.glob('templates/sponsored/*.html') + ['templates/includes/group_order_payment_mode_fields.html']
    for path in files:
        src = open(path, encoding='utf-8').read()
        visible = re.sub(r'\{#.*?#\}|\{\{.*?\}\}|\{%.*?%\}', '', src, flags=re.S)
        visible = re.sub(r'<(script|style)\b.*?</\1>|<!--.*?-->', '', visible, flags=re.S)
        text = _text(visible).lower()
        for word in ('employee', 'your company', "company's", 'the company'):
            assert word not in text, f'{path} says "{word}"'


def test_sponsor_emails_and_messages_use_sponsor_and_shopper():
    src = open('utils/sponsor_emails.py', encoding='utf-8').read() + open('utils/group_sponsor.py', encoding='utf-8').read()
    strings = ' '.join(re.findall(r"""(?:'[^'\n]{12,}'|"[^"\n]{12,}")""", src)).lower()
    for phrase in ('your company', "company's invoice", 'cancelled by the employee', 'company invoice was paid'):
        assert phrase not in strings, phrase
    assert "the sponsor's invoice" in strings
