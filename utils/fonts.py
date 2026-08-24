"""Name/number font choices for the customizer and group orders.

Keep these lists in one place. The shop dropdown, group-order organizer
form, and admin collection form used to drift apart.
"""

# Shop customizer dropdown. Each name must exist in
# utils.personalization_layout.FONT_FILES so the production PNG matches the preview.
CUSTOMIZE_BACK_FONTS = [
    ('Bebas Neue', 'Bebas Neue (Classic jersey)'),
    ('Oswald', 'Oswald (Bold athletic)'),
    ('Anton', 'Anton (Strong block)'),
    ('Teko', 'Teko (College jersey)'),
    ('Jersey M54', 'Jersey M54 (Classic sports jersey)'),
    ('Varsity Regular', 'Varsity Regular (Classic varsity)'),
]

# Organizer-facing list. Preview-only webfonts (Freshman, etc.) still fall back
# to Bebas Neue on the production PNG if they have no file in FONT_FILES.
GROUP_ORDER_FONTS = [
    ('Freshman', 'Freshman — Classic college jersey'),
    ('Black Ops One', 'Black Ops One — Bold varsity block'),
    ('Graduate', 'Graduate — Collegiate style'),
    ('Squada One', 'Squada One — Modern athletic numbers'),
    ('Bebas Neue', 'Bebas Neue — Clean jersey'),
    ('Oswald', 'Oswald — Bold athletic'),
    ('Anton', 'Anton — Strong block'),
    ('Teko', 'Teko — College jersey'),
    ('Jersey M54', 'Jersey M54 — Classic sports jersey'),
    ('Varsity Regular', 'Varsity Regular — Classic varsity block'),
]
