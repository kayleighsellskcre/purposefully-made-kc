"""The business details printed on receipts and invoices (one place to change them)."""

BUSINESS = {
    'owner': 'Kayleigh Biggs',
    'name': 'Purposefully Made KC LLC',
    'email': 'purposefullymadekc@gmail.com',
    'phone': '785.249.1464',
    'venmo': '@Kayleigh-Biggs-1',
    'check_payable_to': 'Kayleigh Biggs',
}

PAYMENT_METHODS = (
    ('Venmo', BUSINESS['venmo']),
    ('Cash', 'In person'),
    ('Check', f"Made out to {BUSINESS['check_payable_to']}"),
)

CARD_LABELS = {'stripe': 'Card', 'paypal': 'PayPal', 'cash': 'Cash'}
