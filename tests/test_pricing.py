"""Pricing rules, and the guarantee that the browser cannot set its own price.

Seeded prices: tee $30.00, hoodie $45.00, youth tee $24.00.
"""
import json

import pytest

from models import db, Product, Design
from utils.pricing import (
    BACK_DESIGN_FEE, BLANK_ITEM_DISCOUNT, SMALL_LOGO_DISCOUNT,
    calculate_unit_price, size_surcharge,
)


# ── The rules in isolation ────────────────────────────────────────────────────

def test_base_price_with_no_options(app, seed):
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        assert calculate_unit_price(tee, size='M', placement='center_chest') == 30.00


def test_small_logo_discount_applies_to_chest_placements(app, seed):
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        for placement in ('left_chest', 'right_chest'):
            price = calculate_unit_price(tee, size='M', placement=placement)
            assert price == 30.00 - SMALL_LOGO_DISCOUNT


def test_small_logo_discount_does_not_apply_to_full_front(app, seed):
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        assert calculate_unit_price(tee, size='M', placement='center_chest') == 30.00
        assert calculate_unit_price(tee, size='M', placement='full_front') == 30.00


@pytest.mark.parametrize('size,expected_extra', [
    ('S', 0), ('M', 0), ('L', 0), ('XL', 0),
    ('2XL', 2), ('2X', 2), ('XXL', 2),
    ('3XL', 3), ('3X', 3), ('XXXL', 3),
    ('4XL', 4), ('4X', 4),
])
def test_extended_size_surcharge_for_adult(app, seed, size, expected_extra):
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        assert size_surcharge(tee, size) == expected_extra
        assert calculate_unit_price(tee, size=size, placement='center_chest') == 30.00 + expected_extra


def test_size_surcharge_is_case_insensitive(app, seed):
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        assert size_surcharge(tee, '2xl') == 2
        assert size_surcharge(tee, ' 3xl ') == 3


def test_youth_garment_never_gets_size_surcharge(app, seed):
    """A youth product has adult-looking sizes (XL, 2XL) but must not be upcharged."""
    with app.app_context():
        youth = Product.query.get(seed['youth_id'])
        assert size_surcharge(youth, '2XL') == 0
        assert calculate_unit_price(youth, size='2XL', placement='center_chest') == 24.00


def test_youth_is_detected_by_age_group_not_product_name(app, seed):
    """Regression: cart.py used to test for 'youth' in the product NAME, so a
    youth garment named without that word was wrongly charged the surcharge."""
    with app.app_context():
        sneaky = Product(
            style_number='KIDS-1', name='Little Kids Tee',  # no 'youth' in the name
            category='Tee', age_group='youth', base_price=20.00, is_active=True,
            available_sizes=json.dumps(['2XL']), available_colors=json.dumps(['Black']),
        )
        db.session.add(sneaky)
        db.session.commit()
        assert size_surcharge(sneaky, '2XL') == 0


def test_back_design_fee(app, seed):
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        price = calculate_unit_price(
            tee, size='M', placement='center_chest', has_back_design=True,
        )
        assert price == 30.00 + BACK_DESIGN_FEE


def test_blank_item_discount(app, seed):
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        price = calculate_unit_price(tee, size='M', placement=None, is_blank=True)
        assert price == 30.00 - BLANK_ITEM_DISCOUNT


def test_price_never_goes_negative(app, seed):
    with app.app_context():
        cheap = Product(
            style_number='CHEAP-1', name='Cheap Adult Tee', category='Tee',
            age_group='adult', base_price=3.00, is_active=True,
            available_sizes=json.dumps(['M']), available_colors=json.dumps(['Black']),
        )
        db.session.add(cheap)
        db.session.commit()
        price = calculate_unit_price(
            cheap, size='M', placement='left_chest', is_blank=True,
        )
        assert price == 0.0


def test_recreate_design_fees_are_added(app, seed):
    with app.app_context():
        tee = Product.query.get(seed['tee_id'])
        assert calculate_unit_price(tee, size='M', design_fee=0) == 30.00
        assert calculate_unit_price(tee, size='M', design_fee=4) == 34.00
        assert calculate_unit_price(tee, size='M', design_fee=20) == 50.00


def test_all_rules_stack_together(app, seed):
    """Hoodie $45, left chest -$2, 3XL +$3, back design +$6, $4 design fee."""
    with app.app_context():
        hoodie = Product.query.get(seed['hoodie_id'])
        price = calculate_unit_price(
            hoodie, size='3XL', placement='left_chest',
            has_back_design=True, design_fee=4,
        )
        assert price == 45.00 - 2.00 + 3.00 + 6.00 + 4.00
        assert price == 56.00


# ── The rules as applied by the cart route ───────────────────────────────────

def _add_to_cart(client, **fields):
    return client.post('/cart/add', data=fields)


def test_cart_add_uses_server_price(client, seed):
    resp = _add_to_cart(
        client, product_id=seed['tee_id'], size='M', color='Black',
        quantity=1, placement='center_chest', design_id=seed['free_design_id'],
    )
    assert resp.status_code == 200
    with client.session_transaction() as sess:
        assert sess['cart'][0]['unit_price'] == 30.00


def test_cart_add_ignores_a_tampered_price(client, seed):
    """The headline security fix: a hand-crafted request cannot set the price."""
    resp = _add_to_cart(
        client, product_id=seed['tee_id'], size='M', color='Black',
        quantity=1, placement='center_chest', design_id=seed['free_design_id'],
        unit_price='0.01',
    )
    assert resp.status_code == 200
    with client.session_transaction() as sess:
        assert sess['cart'][0]['unit_price'] == 30.00


def test_cart_add_ignores_an_inflated_price(client, seed):
    """Also guard the other direction, so nobody can be overcharged."""
    _add_to_cart(
        client, product_id=seed['tee_id'], size='M', color='Black',
        quantity=1, placement='center_chest', design_id=seed['free_design_id'],
        unit_price='9999.00',
    )
    with client.session_transaction() as sess:
        assert sess['cart'][0]['unit_price'] == 30.00


def test_cart_add_ignores_a_negative_price(client, seed):
    _add_to_cart(
        client, product_id=seed['tee_id'], size='M', color='Black',
        quantity=1, placement='center_chest', design_id=seed['free_design_id'],
        unit_price='-500',
    )
    with client.session_transaction() as sess:
        assert sess['cart'][0]['unit_price'] == 30.00


def test_cart_add_charges_the_size_surcharge(client, seed):
    _add_to_cart(
        client, product_id=seed['tee_id'], size='3XL', color='Black',
        quantity=1, placement='center_chest', design_id=seed['free_design_id'],
    )
    with client.session_transaction() as sess:
        assert sess['cart'][0]['unit_price'] == 33.00


def test_cart_add_charges_the_recreate_design_fee(customer_client, seed):
    """The $20 design belongs to this customer, so the fee must be charged."""
    _add_to_cart(
        customer_client, product_id=seed['tee_id'], size='M', color='Black',
        quantity=1, placement='center_chest', design_id=seed['fee_20_design_id'],
    )
    with customer_client.session_transaction() as sess:
        assert sess['cart'][0]['unit_price'] == 50.00


def test_guest_cannot_attach_another_customers_design(client, seed):
    """A private design is rejected, so the item falls back to a blank garment
    rather than silently printing someone else's artwork."""
    _add_to_cart(
        client, product_id=seed['tee_id'], size='M', color='Black',
        quantity=1, placement='center_chest', design_id=seed['fee_20_design_id'],
    )
    with client.session_transaction() as sess:
        assert sess['cart'][0]['design_id'] is None
        assert sess['cart'][0]['is_blank'] is True


def test_cart_add_applies_blank_discount_when_no_artwork(client, seed):
    _add_to_cart(
        client, product_id=seed['tee_id'], size='M', color='Black', quantity=1,
    )
    with client.session_transaction() as sess:
        assert sess['cart'][0]['is_blank'] is True
        assert sess['cart'][0]['unit_price'] == 18.00


def test_cart_add_charges_back_design_fee(client, seed):
    """Regression: the old server-side fallback omitted the $6 back fee entirely,
    so any request without a browser price got the back print for free."""
    _add_to_cart(
        client, product_id=seed['tee_id'], size='M', color='Black', quantity=1,
        placement='center_chest', design_id=seed['free_design_id'],
        back_design_name='SMITH', back_design_number='12',
    )
    with client.session_transaction() as sess:
        assert sess['cart'][0]['unit_price'] == 36.00
