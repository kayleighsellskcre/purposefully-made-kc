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
    ('Varsity Team', 'Varsity Team (Bold college block)'),
    ('Graduate', 'Graduate (Varsity collegiate)'),
    ('Squada One', 'Squada One (Modern athletic numbers)'),
    ('Sports Jersey', 'Sports Jersey (Classic athletic block)'),
    ('Varsity Regular', 'Varsity Regular (Cricut-style classic)'),
]

# Organizer-facing list. Every font here has a real file in FONT_FILES, so mockups and print files match the preview.
# (Freshman was removed: it has no free font file and always printed as Bebas Neue. Old orders that used it still work.)
GROUP_ORDER_FONTS = [
    ('Varsity Team', 'Varsity Team (Bold college block)'),
    ('Graduate', 'Graduate (Collegiate style)'),
    ('Squada One', 'Squada One (Modern athletic numbers)'),
    ('Bebas Neue', 'Bebas Neue (Clean jersey)'),
    ('Oswald', 'Oswald (Bold athletic)'),
    ('Anton', 'Anton (Strong block)'),
    ('Teko', 'Teko (College jersey)'),
    ('Sports Jersey', 'Sports Jersey (Classic athletic block)'),
    ('Varsity Regular', 'Varsity Regular (Cricut-style classic varsity)'),
]
