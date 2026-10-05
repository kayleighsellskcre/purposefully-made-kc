"""Starter templates for the Start a Group Order form.

Each group type lists the styles we recommend. A slot names preferred style
numbers first, then falls back to any active product with the same age and
category, so a template keeps working when a style is retired.
"""
from utils.product_filters import _bare_style, infer_age, infer_category, infer_fit


def _slot(styles, age, category, fit=None):
    return {'styles': styles, 'age': age, 'category': category, 'fit': fit}


GROUP_TEMPLATES = [
    {
        'key': 'family_vacation',
        'label': 'Family Vacation',
        'blurb': 'Matching looks for the whole crew, from babies to grandparents.',
        'kind': 'other',
        'back': 'none',
        'name_placeholder': 'e.g., Hayes Family Beach Trip 2027',
        'description': (
            'Matching shirts for our family trip! Pick your style, color, and size below. '
            'Kids and adults come in the same colors so we all match in photos.'
        ),
        'tips': [
            'We added the same tee in adult, youth, toddler, and baby sizes so everyone matches.',
            'A cozy crewneck is great for chilly evenings and travel days.',
            'Set your deadline at least 3 weeks before you leave so shirts arrive in time.',
        ],
        'watch': 'Comfort Colors runs a little oversized, so let your family know to size down for a fitted look.',
        'slots': [
            _slot(['3001'], 'adult', 'Tee'),
            _slot(['3001Y'], 'youth', 'Tee'),
            _slot(['3001T'], 'toddler', 'Tee'),
            _slot(['100B', '3001B'], 'baby', 'Onesie'),
            _slot(['3901'], 'adult', 'Sweatshirt'),
            _slot(['3901Y'], 'youth', 'Sweatshirt'),
        ],
    },
    {
        'key': 'school_spirit',
        'label': 'School Spirit Wear',
        'blurb': 'Spirit wear for students, families, teachers, and staff.',
        'kind': 'school',
        'back': 'none',
        'name_placeholder': 'e.g., Silver Lake Spirit Wear 2026',
        'description': (
            'Show your school spirit! Order for your student, yourself, or the whole family. '
            'Orders can be sent home with your child.'
        ),
        'tips': [
            'We included youth sizes from the start, since most school orders are for kids.',
            'The pullover hoodie is always a top seller.',
            'A long sleeve tee is perfect for fall, and the full-zip is a favorite with teachers and staff.',
        ],
        'watch': 'Plan around school breaks so orders can go home with students before a long weekend.',
        'slots': [
            _slot(['3001'], 'adult', 'Tee'),
            _slot(['3001Y'], 'youth', 'Tee'),
            _slot(['3719'], 'adult', 'Hoodie'),
            _slot(['3719Y'], 'youth', 'Hoodie'),
            _slot(['3501'], 'adult', 'Long Sleeve'),
            _slot(['3501Y'], 'youth', 'Long Sleeve'),
            _slot(['3739'], 'adult', 'Hoodie'),
        ],
    },
    {
        'key': 'sports_team',
        'label': 'Sports Team',
        'blurb': 'Fan gear for players, parents, siblings, and coaches.',
        'kind': 'team',
        'back': 'name_number',
        'name_placeholder': 'e.g., KC Thunder 10U Fan Gear',
        'description': (
            'Gear up for the season! Grab fan wear for players, parents, siblings, and grandparents. '
            'Add a name and number on the back if you like.'
        ),
        'tips': [
            'We turned on names and numbers for the back. You can change that in the back design step.',
            'Need jerseys too? Turn on Player Uniforms in the section just below.',
            'Matching hoodies keep the whole family warm at early games.',
        ],
        'watch': 'Set your deadline early so gear arrives before the first game.',
        'slots': [
            _slot(['3001'], 'adult', 'Tee'),
            _slot(['3001Y'], 'youth', 'Tee'),
            _slot(['3719'], 'adult', 'Hoodie'),
            _slot(['3719Y'], 'youth', 'Hoodie'),
            _slot(['3501'], 'adult', 'Long Sleeve'),
        ],
    },
    {
        'key': 'business',
        'label': 'Business / Corporate',
        'blurb': 'Polished staff apparel for your team, office, or trade show.',
        'kind': 'other',
        'back': 'none',
        'name_placeholder': 'e.g., Acme Co. Staff Apparel 2026',
        'description': (
            "Order your company apparel here. Pick your style, color, and size, and we'll take care of the rest."
        ),
        'tips': [
            'We started you with premium tees and a full-zip hoodie for a polished, professional look.',
            'A small logo on the left chest always looks sharp.',
            'If the company is covering the cost, mention that in the description so your team knows.',
        ],
        'watch': 'Stick to 2 or 3 colors so the whole team looks cohesive.',
        'slots': [
            _slot(['DM130'], 'adult', 'Tee'),
            _slot(['DT6000'], 'adult', 'Tee'),
            _slot(['3739'], 'adult', 'Hoodie'),
            _slot(['CC1566', '3945'], 'adult', 'Sweatshirt'),
        ],
    },
    {
        'key': 'organization_club',
        'label': 'Organization / Club',
        'blurb': 'Gear for your club, church, nonprofit, or volunteer group.',
        'kind': 'other',
        'back': 'none',
        'name_placeholder': 'e.g., Northland Garden Club 2026',
        'description': 'Rep our group! Pick your favorite style, color, and size below.',
        'tips': [
            'A classic tee is the anchor most members will buy.',
            'A hoodie or crewneck sells all year round.',
            'Want something special for leaders or volunteers? The full-zip makes a nice standout piece.',
        ],
        'watch': 'Keep the choices simple so members can order in a minute or two.',
        'slots': [
            _slot(['3001'], 'adult', 'Tee'),
            _slot(['3719'], 'adult', 'Hoodie'),
            _slot(['3901'], 'adult', 'Sweatshirt'),
            _slot(['3739'], 'adult', 'Hoodie'),
        ],
    },
    {
        'key': 'event',
        'label': 'Event',
        'blurb': 'Reunions, birthdays, bachelorettes, and more.',
        'kind': 'other',
        'back': 'none',
        'name_placeholder': 'e.g., Johnson Family Reunion 2027',
        'description': 'Get your shirt for the big day! Pick your style, color, and size below.',
        'tips': [
            'Tees and tanks are the easy, affordable picks for a one-day event.',
            'We added youth tees for reunions and birthdays. Remove them for adults-only events like bachelorettes.',
            'Set your deadline at least 3 weeks before the event.',
        ],
        'watch': 'Comfort Colors runs a little oversized, so a size down works for a fitted look.',
        'slots': [
            _slot(['3001'], 'adult', 'Tee'),
            _slot(['3001Y'], 'youth', 'Tee'),
            _slot(['CC1717'], 'adult', 'Tee'),
            _slot(['3480'], 'adult', 'Tank'),
            _slot(['8800'], 'adult', 'Tank', "Women's"),
        ],
    },
    {
        'key': 'kids_only',
        'label': 'Kids Only',
        'blurb': 'Youth and toddler sizes for camps, classes, and kid teams.',
        'kind': 'other',
        'back': 'none',
        'name_placeholder': 'e.g., Camp Sunshine Summer 2026',
        'description': 'Order a shirt for your little one! Youth and toddler sizes are available below.',
        'tips': [
            'We only added youth and toddler styles, so no adult sizes will show.',
            'Bright colors are easy to spot on field trips and at camp.',
        ],
        'watch': 'Kids grow fast, so sizing up is often a good idea.',
        'slots': [
            _slot(['3001Y'], 'youth', 'Tee'),
            _slot(['3501Y'], 'youth', 'Long Sleeve'),
            _slot(['3719Y'], 'youth', 'Hoodie'),
            _slot(['3901Y'], 'youth', 'Sweatshirt'),
            _slot(['3001T'], 'toddler', 'Tee'),
        ],
    },
    {
        'key': 'adults_only',
        'label': 'Adults Only',
        'blurb': 'Soft, grown-up styles with no youth sizes.',
        'kind': 'other',
        'back': 'none',
        'name_placeholder': 'e.g., Class of 2006 20-Year Reunion',
        'description': 'Grab your shirt! Pick your favorite style, color, and size below.',
        'tips': [
            'We picked soft, fashion-forward styles like heather tees, tri-blends, and Comfort Colors.',
            'No youth sizes are included.',
        ],
        'watch': 'Comfort Colors runs a little oversized, so a size down works for a fitted look.',
        'slots': [
            _slot(['3001CVC'], 'adult', 'Tee'),
            _slot(['CC1717'], 'adult', 'Tee'),
            _slot(['DM130'], 'adult', 'Tee'),
            _slot(['3719'], 'adult', 'Hoodie'),
            _slot(['CC1566'], 'adult', 'Sweatshirt'),
        ],
    },
    {
        'key': 'mixed_ages',
        'label': 'Mixed Ages',
        'blurb': 'Kids and adults ordering together, all matching.',
        'kind': 'other',
        'back': 'none',
        'name_placeholder': "e.g., St. Mary's Fall Festival 2026",
        'description': (
            'Order for the whole family! Every style comes in kid and adult sizes, so everyone can match.'
        ),
        'tips': [
            'We added the same tee and hoodie in adult, youth, and toddler sizes so everyone can match.',
            'In the color step, use Same as Adult to match the kids colors in one click.',
            'Remind families to check the size chart on each style.',
        ],
        'watch': 'Kids and adult sizes are separate styles, so check both when picking colors.',
        'slots': [
            _slot(['3001'], 'adult', 'Tee'),
            _slot(['3001Y'], 'youth', 'Tee'),
            _slot(['3001T'], 'toddler', 'Tee'),
            _slot(['3719'], 'adult', 'Hoodie'),
            _slot(['3719Y'], 'youth', 'Hoodie'),
            _slot(['3719T'], 'toddler', 'Hoodie'),
        ],
    },
]

TEMPLATE_KEYS = {t['key'] for t in GROUP_TEMPLATES}


def _facts(product):
    age = getattr(product, 'display_age', None) or infer_age(product) or 'adult'
    category = getattr(product, 'display_category', None) or infer_category(product) or ''
    fit = getattr(product, 'display_fit', None) or infer_fit(product) or ''
    return age, category, fit


def _pick(slot, items, taken):
    wanted = [_bare_style(s) for s in slot['styles']]
    for style in wanted:
        for product, bare, age, category, fit in items:
            if product.id not in taken and bare == style and age == slot['age']:
                return product
    for product, bare, age, category, fit in items:
        if product.id in taken or age != slot['age'] or category != slot['category']:
            continue
        if slot['fit'] and fit != slot['fit']:
            continue
        if not slot['fit'] and fit == "Women's":
            continue
        return product
    return None


def group_order_templates(products):
    """Templates with product_ids resolved against the active catalog."""
    items = [(p, _bare_style(p.style_number), *_facts(p)) for p in products or []]
    resolved = []
    for template in GROUP_TEMPLATES:
        taken = []
        for slot in template['slots']:
            product = _pick(slot, items, taken)
            if product is not None:
                taken.append(product.id)
        entry = {k: v for k, v in template.items() if k != 'slots'}
        entry['product_ids'] = [str(pid) for pid in taken]
        resolved.append(entry)
    return resolved
