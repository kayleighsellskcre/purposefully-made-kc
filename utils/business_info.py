"""The business details printed on receipts and invoices (one place to change them)."""

# The last day to order for Christmas. After this date the note goes away by itself; change the date each year.
HOLIDAY_CUTOFF = (2026, 12, 1)


def holiday_note(today=None):
    """A short Christmas reminder until the cutoff day has passed, else None."""
    from datetime import date
    today = today or date.today()
    cutoff = date(*HOLIDAY_CUTOFF)
    if today > cutoff:
        return None
    return f'Christmas orders: place yours by {cutoff:%B} {cutoff.day}.'


BUSINESS = {
    'owner': 'Kayleigh Biggs',
    'name': 'Purposefully Made KC LLC',
    'email': 'purposefullymadekc@gmail.com',
    'phone': '(785) 249-1464',
    'venmo': '@Kayleigh-Biggs-1',
    'check_payable_to': 'Kayleigh Biggs',
    'pickup_address': '4632 Woodstock Street, Shawnee, KS 66218',
}

PAYMENT_METHODS = (
    ('Venmo', BUSINESS['venmo']),
    ('Cash', 'In person'),
    ('Check', f"Made out to {BUSINESS['check_payable_to']}"),
)

CARD_LABELS = {'stripe': 'Card', 'paypal': 'PayPal', 'cash': 'Cash'}
