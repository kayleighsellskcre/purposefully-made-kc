"""The customer design gallery, built from the master design library.

One design, one record: the collections it sits in, its tags, its colors and its sales all come from that record,
so a design shows up everywhere it belongs without being uploaded or managed twice.

Customers see: Collection -> Subcategory -> Designs. Anything more specific (recipient, sport, style, color) is a
filter. Fan Favorites, New Arrivals, Trending and Matching Sets build themselves from real activity.
"""
import re
from datetime import datetime, timedelta

from models import Design, DesignCategoryLink, DesignRelation, DesignTag, DesignTagLink, Order, OrderItem, db
from utils.design_tags import _norm, search_terms, tag_related, tag_synonyms, vocabulary
from utils.design_taxonomy import COLLECTION_BY_KEY, COLLECTIONS, label_for

# the gallery's old public folder keys -> the new collection they became
LEGACY_TO_COLLECTION = {
    'faith': 'faith-inspiration', 'sports': 'sports-game-day', 'school': 'school-spirit', 'kc': 'kansas-city',
    'music': 'music-entertainment', 'holiday': 'holidays-seasons', 'family': 'family-relationships',
    'funny': 'funny-sarcastic', 'luxury': 'luxury-basics',
}
AUTOMATIC = (
    ('fan-favorites', 'Fan Favorites', 'Loved by our customers'),
    ('new-arrivals', 'New Arrivals', 'Fresh off the design table'),
    ('trending', 'Trending Designs', 'What people are choosing right now'),
    ('matching-sets', 'Matching Sets', 'Designs made to go together'),
)
AUTOMATIC_KEYS = {k for k, _l, _d in AUTOMATIC}
ALWAYS_SHOW = {'music-entertainment'}           # kept visible even when empty, as before
NEW_DAYS, TREND_DAYS = 60, 30
FILTERS = (('recipient', 'Who it is for'), ('sport', 'Sport'), ('style', 'Style'), ('color', 'Color'))
SOLD_OUT_STATUSES = ('cancelled', 'failed', 'refunded')


# -- Putting library data onto the gallery cards -------------------------------------------

def enrich_cards(cards):
    """Add collections, tags, colors and search words to each public card (a handful of queries for all of them)."""
    if not cards:
        return cards
    ids = [c['id'] for c in cards]
    child_ids = {}
    for card in cards:
        for v in card.get('variants') or []:
            if v.get('id') and v['id'] != card['id']:
                child_ids[v['id']] = card['id']
    all_ids = ids + list(child_ids)

    links = {}
    for l in DesignCategoryLink.query.filter(DesignCategoryLink.design_id.in_(all_ids)).all():
        owner = child_ids.get(l.design_id, l.design_id)
        links.setdefault(owner, []).append(l)
    vocab = vocabulary(active_only=False)
    by_id = {t.id: t for t in vocab.values()}
    tags = {}
    for l in DesignTagLink.query.filter(DesignTagLink.design_id.in_(all_ids)).all():
        tag = by_id.get(l.tag_id)
        if tag and tag.is_active:
            tags.setdefault(child_ids.get(l.design_id, l.design_id), set()).add(tag.slug)
    rows = {d.id: d for d in Design.query.filter(Design.id.in_(all_ids)).all()}
    families = {}
    for design_id, d in rows.items():
        owner = child_ids.get(design_id, design_id)
        for f in (d.color_families or '').split(','):
            if f:
                families.setdefault(owner, [])
                if f not in families[owner]:
                    families[owner].append(f)

    for card in cards:
        mine = sorted(links.get(card['id'], []), key=lambda l: (not l.is_primary, l.id))
        places = []
        for l in mine:
            if l.category_key in COLLECTION_BY_KEY and (l.category_key, l.subcategory_key) not in places:
                places.append((l.category_key, l.subcategory_key))
        if not places:                                   # not organized yet: its old folders still place it
            for key in card.get('category_keys') or []:
                coll = LEGACY_TO_COLLECTION.get(key)
                if coll and (coll, None) not in places:
                    places.append((coll, None))
        card['places'] = places
        design = rows.get(card['id'])
        explicit = False
        if design is not None:
            from utils.design_categories import normalize_category
            raw = [design.folder] + (design.extra_categories or '').split(',')
            explicit = any(normalize_category(v) == 'favorites' for v in raw)
        # Hand-picked favorites, or a design nobody has filed anywhere yet (it used to land in Fan Favorites).
        card['curated_favorite'] = explicit or (not places and 'favorites' in (card.get('category_keys') or []))
        card['collections'] = list(dict.fromkeys(p[0] for p in places))
        card['subs'] = [f'{c}:{s}' for c, s in places if s]
        slugs = tags.get(card['id'], set())
        shown = {s for s in slugs if s in vocab and vocab[s].tag_type != 'control'}
        card['tag_slugs'] = sorted(slugs)
        card['tag_labels'] = [vocab[s].label for s in sorted(shown)]
        card['recipients'] = [s for s in slugs if s in vocab and vocab[s].tag_type == 'recipient']
        card['sports'] = [s for s in slugs if s in vocab and vocab[s].tag_type == 'sport']
        style_words = [s for s in slugs if s in vocab and vocab[s].tag_type == 'style']
        if design and design.style and _norm(design.style).replace(' ', '-') not in style_words:
            style_words.append(_norm(design.style).replace(' ', '-'))
        card['styles'] = style_words
        card['families'] = families.get(card['id'], [])
        extra, weak = [], []
        for s in shown:
            tag = vocab.get(s)
            if tag:
                extra += [tag.label] + tag_synonyms(tag)
                for rel in tag_related(tag):
                    other = vocab.get(rel)
                    if other:
                        weak += [other.label] + tag_synonyms(other)
        if design:
            extra += [design.keywords or '', design.art_text or '', design.audience or '', design.style or '']
        card['search_extra'] = _norm(' '.join(extra))
        card['related_words'] = _norm(' '.join(weak))
        card['sku'] = design.sku if design else ''
    return cards


def _blob(card):
    parts = [card.get('title') or '', card.get('group') or '', ' '.join(card.get('category_labels') or []),
             ' '.join(label_for(c) for c in card.get('collections') or []), card.get('search_extra') or '',
             ' '.join(f"{(v.get('label') or '')}" for v in card.get('variants') or []),
             ' '.join(card.get('families') or [])]
    return ' ' + _norm(' '.join(parts)) + ' '


# -- Search ----------------------------------------------------------------------------------

def search_cards(cards, query, *, pool=None):
    """Designs matching what someone typed. "Mama" finds Mom designs; "Grandma" also shows Nana and Mimi after.

    Every word must match (as the gallery always did); words match their synonyms too. Close cousins
    (related tags) come after the exact matches, never mixed in ahead of them.
    """
    words = [w for w in _norm(query).split() if w]
    if not words:
        return list(pool if pool is not None else cards)
    strong, weak = [], []
    for card in pool if pool is not None else cards:
        blob = _blob(card)
        extra_weak = ' ' + (card.get('related_words') or '') + ' '
        exact = related = True
        for word in words:
            terms = search_terms(word)
            hit_exact = any(f' {t} ' in blob or (len(t) > 3 and t in blob) for t in terms['exact'] | {word})
            hit_related = hit_exact or any(f' {t} ' in extra_weak for t in terms['related'])
            exact = exact and hit_exact
            related = related and hit_related
        if exact:
            strong.append(card)
        elif related:
            weak.append(card)
    return strong + weak


# -- Collections -------------------------------------------------------------------------------

def _covers(members, used, limit=6):
    covers = []
    for card in members:
        if len(covers) >= limit:
            break
        marker = (card.get('url') or '').strip().lower()
        if marker and marker in used:
            continue
        if marker:
            used.add(marker)
        covers.append({'id': card['id'], 'url': card['url'], 'title': card['title']})
    if not covers and members:
        first = members[0]
        covers.append({'id': first['id'], 'url': first['url'], 'title': first['title']})
    return covers


def collection_members(cards, key, sub=None):
    out = [c for c in cards if key in c.get('collections', [])]
    if sub:
        out = [c for c in out if f'{key}:{sub}' in c.get('subs', [])]
    return out


def subcategory_options(cards, key):
    """Subcategories of one collection that actually have designs (empty ones are never shown)."""
    coll = COLLECTION_BY_KEY.get(key)
    if not coll:
        return []
    members = collection_members(cards, key)
    out = []
    for s in coll.subcategories:
        n = sum(1 for c in members if f'{key}:{s.key}' in c.get('subs', []))
        if n:
            out.append({'key': s.key, 'label': s.label, 'count': n})
    return out


# -- Automatic collections ----------------------------------------------------------------------

def _sales(card_by_design, since=None):
    """{card id: units sold} from real orders (color versions count toward their main design)."""
    if not card_by_design:
        return {}
    q = (db.session.query(OrderItem.design_id, db.func.sum(OrderItem.quantity))
         .join(Order, Order.id == OrderItem.order_id)
         .filter(OrderItem.design_id.in_(list(card_by_design)),
                 ~Order.status.in_(SOLD_OUT_STATUSES), ~Order.payment_status.in_(['failed', 'refunded'])))
    if since is not None:
        q = q.filter(Order.created_at >= since)
    out = {}
    for design_id, units in q.group_by(OrderItem.design_id).all():
        owner = card_by_design.get(design_id)
        if owner is not None:
            out[owner] = out.get(owner, 0) + int(units or 0)
    return out


def _design_to_card(cards):
    mapping = {}
    for card in cards:
        mapping[card['id']] = card['id']
        for v in card.get('variants') or []:
            if v.get('id'):
                mapping[v['id']] = card['id']
    return mapping


def automatic_collections(cards, now=None):
    """{'fan-favorites': [...], 'new-arrivals': [...], 'trending': [...], 'matching-sets': [...]} (empty ones omitted)."""
    now = now or datetime.utcnow()
    by_id = {c['id']: c for c in cards}
    mapping = _design_to_card(cards)
    sold = _sales(mapping)
    recent = _sales(mapping, since=now - timedelta(days=TREND_DAYS))
    out = {}

    pinned = {c['id'] for c in cards if 'fan-favorite' in c.get('tag_slugs', [])}
    hidden = {c['id'] for c in cards if 'hide-favorite' in c.get('tag_slugs', [])}
    chosen = {c['id'] for c in cards if c.get('curated_favorite')}
    best = {i for i, n in sold.items() if n >= 2}
    best = set(sorted(best, key=lambda i: -sold[i])[:24])
    fav = (pinned | chosen | best) - hidden
    fan = [by_id[i] for i in fav if i in by_id]
    fan.sort(key=lambda c: (c['id'] not in pinned, -sold.get(c['id'], 0), c.get('uploaded_at') or ''), reverse=False)
    fan.sort(key=lambda c: (0 if c['id'] in pinned else 1, -sold.get(c['id'], 0)))
    if fan:
        out['fan-favorites'] = fan

    cutoff = (now - timedelta(days=NEW_DAYS)).isoformat()
    fresh = sorted((c for c in cards if (c.get('uploaded_at') or '') >= cutoff),
                   key=lambda c: c.get('uploaded_at') or '', reverse=True)[:24]
    if fresh:
        out['new-arrivals'] = fresh

    hot = sorted((i for i, n in recent.items() if n >= 1), key=lambda i: -recent[i])[:12]
    if hot:
        out['trending'] = [by_id[i] for i in hot if i in by_id]

    sets = matching_sets(cards)
    if sets:
        out['matching-sets'] = [c for group in sets for c in group]
        for group in sets:
            label = 'Matching set: ' + ' + '.join(c['title'] for c in group[:3])
            for c in group:
                c['set_label'] = label
    return out


def matching_sets(cards):
    """Groups of designs made to coordinate (confirmed by you, or tagged as a set). Not every family design is a set."""
    by_id = {c['id']: c for c in cards}
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    mapping = _design_to_card(cards)
    for rel in DesignRelation.query.filter_by(relation_type='matching_set', status='confirmed').all():
        a, b = mapping.get(rel.design_id), mapping.get(rel.related_design_id)
        if a in by_id and b in by_id:
            parent[find(a)] = find(b)
    members = {i for i in parent}
    groups = {}
    for i in members:
        groups.setdefault(find(i), []).append(by_id[i])
    return [sorted(g, key=lambda c: c['title']) for g in sorted(groups.values(), key=lambda g: -len(g)) if len(g) > 1]


def automatic_tile_cards(autos):
    return [{'key': k, 'label': label, 'blurb': blurb, 'members': autos.get(k, [])}
            for k, label, blurb in AUTOMATIC if autos.get(k)]


def landing_tiles(cards, autos):
    """The tiles on the gallery front page: automatic collections first, then each collection that has designs."""
    tiles, used = [], set()
    for item in automatic_tile_cards(autos):
        tiles.append({'key': item['key'], 'label': item['label'], 'count': len(item['members']),
                      'covers': _covers(item['members'], used), 'featured': True, 'blurb': item['blurb']})
    for coll in COLLECTIONS:
        members = collection_members(cards, coll.key)
        if not members and coll.key not in ALWAYS_SHOW:
            continue
        tiles.append({'key': coll.key, 'label': coll.label, 'count': len(members),
                      'covers': _covers(members, used), 'featured': False, 'blurb': ''})
    return tiles


# -- Filters -----------------------------------------------------------------------------------

def filter_options(cards):
    """Only the choices that exist among these designs, with counts. A filter with fewer than two choices is left out."""
    vocab = vocabulary(active_only=False)
    out = {}
    for name, label in FILTERS:
        counts = {}
        for card in cards:
            if name == 'recipient':
                vals = card.get('recipients', [])
            elif name == 'sport':
                vals = card.get('sports', [])
            elif name == 'style':
                vals = card.get('styles', [])
            else:
                vals = card.get('families', [])
            for v in vals:
                counts[v] = counts.get(v, 0) + 1
        options = []
        for value, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            tag = vocab.get(value)
            options.append({'value': value, 'label': tag.label if tag else value.replace('-', ' ').title(), 'count': n})
        if len(options) >= 2 or (options and name == 'recipient'):
            out[name] = {'label': label, 'options': options}
    return out


def apply_filters(cards, args):
    chosen = {name: (args.get(name) or '').strip().lower() for name, _l in FILTERS}
    out = []
    for card in cards:
        if chosen['recipient'] and chosen['recipient'] not in card.get('recipients', []):
            continue
        if chosen['sport'] and chosen['sport'] not in card.get('sports', []):
            continue
        if chosen['style'] and chosen['style'] not in card.get('styles', []):
            continue
        if chosen['color'] and chosen['color'] not in card.get('families', []):
            continue
        out.append(card)
    return out, {k: v for k, v in chosen.items() if v}


# -- Related designs on each card ----------------------------------------------------------------

def attach_related(cards, per_card=6):
    """data for the 'You might also like' row: confirmed versions and sets first, then shared tags."""
    by_id = {c['id']: c for c in cards}
    mapping = _design_to_card(cards)
    confirmed = {}
    for rel in DesignRelation.query.filter(DesignRelation.status == 'confirmed',
                                           DesignRelation.relation_type != 'exact_duplicate').all():
        a, b = mapping.get(rel.design_id), mapping.get(rel.related_design_id)
        if a and b and a != b:
            confirmed.setdefault(a, []).append((rel.relation_type, rel.score or 0, b))
            confirmed.setdefault(b, []).append((rel.relation_type, rel.score or 0, a))
    priority = {'color_variation': 0, 'matching_set': 1, 'wording_variation': 2}
    by_tag = {}
    for card in cards:
        for slug in card.get('tag_slugs', []):
            by_tag.setdefault(slug, []).append(card['id'])
    for card in cards:
        picked = []
        for kind, score, other in sorted(confirmed.get(card['id'], []), key=lambda r: (priority.get(r[0], 9), -r[1])):
            if other in by_id and other not in picked:
                picked.append(other)
        if len(picked) < per_card:
            shared = {}
            for slug in card.get('tag_slugs', []):
                if len(by_tag.get(slug, [])) > 40:        # a tag on nearly everything says nothing
                    continue
                for other in by_tag.get(slug, []):
                    if other != card['id']:
                        shared[other] = shared.get(other, 0) + 1
            for other, n in sorted(shared.items(), key=lambda kv: -kv[1]):
                if n >= 2 and other not in picked:
                    picked.append(other)
        card['related'] = [{'id': by_id[i]['id'], 'title': by_id[i]['title'], 'url': by_id[i]['url'],
                            'variants': by_id[i]['variants'] if by_id[i]['has_colors'] else
                            [{'id': by_id[i]['variants'][0]['id']}] if by_id[i]['variants'] else [],
                            'has_colors': by_id[i]['has_colors']}
                           for i in picked[:per_card] if i in by_id]
    return cards
