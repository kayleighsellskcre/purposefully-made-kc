"""Smart upload: read a design once and file it everywhere it belongs.

One vision call (the OpenAI key the site already uses for design names) returns the
name, colors, visible wording, the collections and subcategories it fits, tags, style
and who it is for, each with a confidence. Everything is then checked against the
real taxonomy and tag vocabulary, so nothing invented ever lands in the library.

Rules that keep it honest:
* A team or artist is only named when the words are actually visible on the artwork
  (or in its title), never from colors alone.
* Confident results are applied automatically. Unsure ones go to the review list.
* Anything that mentions a protected name (pro teams, artists, brands) is flagged for
  a look before it is published. The flag never blocks filing the design.
* Things you set by hand are never overwritten.
"""
import json
import re

from utils.design_tags import (
    _norm, apply_auto_tags, canonical_for, clean_tags, is_locked, record_correction, set_if_unlocked,
    vocabulary,
)
from utils.design_taxonomy import (
    COLLECTION_BY_KEY, COLLECTIONS, is_valid_pair, legacy_key_for,
)

AUTO_THRESHOLD = 0.75           # at or above this a category is applied automatically
MAX_COLLECTIONS = 4             # a design belongs in a few places, never everywhere

# Words that mean "a person should look before this is sold": pro teams, universities,
# artists and well-known brands. Identifying one does not mean it is allowed or not allowed.
PROTECTED_WORDS = (
    'chiefs', 'chiefs kingdom', 'arrowhead', 'royals', 'sporting kc', 'sporting kansas city', 'kc current',
    'jayhawks', 'rock chalk', 'k-state', 'kstate', 'powercat', 'mizzou', 'nfl', 'mlb', 'nba', 'nhl', 'mls',
    'super bowl', 'taylor swift', 'eras tour', 'beyonce', 'morgan wallen', 'zach bryan', 'luke combs',
    'chris stapleton', 'kenny chesney', 'george strait', 'garth brooks', 'bluey', 'disney', 'mickey',
    'minnie', 'marvel', 'star wars', 'harry potter', 'barbie', 'nike', 'adidas', 'coca cola', 'starbucks',
    'dunkin', 'stanley', 'lululemon', 'carhartt', 'yeti',
)

# Where a tag naturally files a design. Used to fill a missing subcategory and as the
# no-internet fallback; the AI's own collection picks still come first.
TAG_TO_PLACE = {
    'mom': ('family-relationships', 'moms'), 'dad': ('family-relationships', 'dads'),
    'grandma': ('family-relationships', 'grandparents'), 'nana': ('family-relationships', 'grandparents'),
    'mimi': ('family-relationships', 'grandparents'), 'grandpa': ('family-relationships', 'grandparents'),
    'aunt': ('family-relationships', 'aunts-and-uncles'), 'uncle': ('family-relationships', 'aunts-and-uncles'),
    'kids': ('family-relationships', 'kids-and-babies'), 'baby': ('family-relationships', 'kids-and-babies'),
    'sister': ('family-relationships', 'siblings'), 'brother': ('family-relationships', 'siblings'),
    'bestie': ('family-relationships', 'friends-and-besties'), 'couple': ('family-relationships', None),
    'football': ('sports-game-day', 'football'), 'baseball': ('sports-game-day', 'baseball-and-softball'),
    'softball': ('sports-game-day', 'baseball-and-softball'), 'soccer': ('sports-game-day', 'soccer'),
    'basketball': ('sports-game-day', 'basketball'), 'volleyball': ('sports-game-day', 'volleyball'),
    'cheer': ('sports-game-day', 'cheer-and-dance'), 'dance': ('sports-game-day', 'cheer-and-dance'),
    'track': ('sports-game-day', 'general-sports'), 'golf': ('sports-game-day', 'general-sports'),
    'game-day': ('sports-game-day', 'general-sports'),
    'kc-chiefs': ('kansas-city', 'kc-chiefs'), 'kc-royals': ('kansas-city', 'kc-royals'),
    'kc-current': ('kansas-city', 'kc-current'), 'sporting-kc': ('kansas-city', 'sporting-kc'),
    'kansas-city': ('kansas-city', 'kansas-city-pride'),
    'faith': ('faith-inspiration', 'faith-based'), 'scripture': ('faith-inspiration', 'scripture-and-biblical-sayings'),
    'encouragement': ('faith-inspiration', 'encouragement'), 'inspirational': ('faith-inspiration', 'inspirational'),
    'affirmation': ('faith-inspiration', 'positive-affirmations'),
    'funny': ('funny-sarcastic', 'funny-sayings'), 'sarcasm': ('funny-sarcastic', 'sarcasm-and-sass'),
    'country-music': ('music-entertainment', 'country-music'), 'rock': ('music-entertainment', 'rock-and-retro'),
    'concert': ('music-entertainment', 'concert-and-tour-inspired'), 'music-lover': ('music-entertainment', 'music-lovers'),
    'pop-culture': ('music-entertainment', 'pop-culture'),
    'school-spirit': ('school-spirit', None), 'back-to-school': ('school-spirit', None),
    'western': ('lifestyle-interests', 'western-and-country'), 'coffee': ('lifestyle-interests', 'coffee-and-drinks'),
    'outdoors': ('lifestyle-interests', 'outdoors-and-adventure'), 'pets': ('lifestyle-interests', 'animals-and-pet-lovers'),
    'books': ('lifestyle-interests', 'books-and-reading'), 'hobbies': ('lifestyle-interests', 'hobbies-and-interests'),
    'christmas': ('holidays-seasons', 'christmas'), 'halloween': ('holidays-seasons', 'halloween'),
    'thanksgiving': ('holidays-seasons', 'fall-and-thanksgiving'), 'fall': ('holidays-seasons', 'fall-and-thanksgiving'),
    'valentines': ('holidays-seasons', 'valentines-day'), 'easter': ('holidays-seasons', 'easter-and-spring'),
    'spring': ('holidays-seasons', 'easter-and-spring'), 'summer': ('holidays-seasons', 'summer-and-patriotic'),
    'patriotic': ('holidays-seasons', 'summer-and-patriotic'), 'new-years': ('holidays-seasons', 'other-holidays'),
    'st-patricks': ('holidays-seasons', 'other-holidays'), 'mothers-day': ('holidays-seasons', 'other-holidays'),
    'fathers-day': ('holidays-seasons', 'other-holidays'),
}


# -- Asking the vision model -------------------------------------------------------

def _prompt():
    places = []
    for c in COLLECTIONS:
        subs = ', '.join(f'{s.key}' for s in c.subcategories)
        places.append(f'- {c.key} ({c.label})' + (f': {subs}' if subs else ''))
    by_type = {}
    for tag in sorted(vocabulary().values(), key=lambda t: t.slug):
        by_type.setdefault(tag.tag_type, []).append(tag.slug)
    tags = '\n'.join(f'- {kind}: {", ".join(slugs)}' for kind, slugs in by_type.items() if kind != 'color')
    return (
        'You organize apparel print artwork for a boutique shop. Look at the image and any visible wording. '
        'Return JSON only:\n'
        '{"title": "2-8 word customer-facing name using the exact visible wording plus a short icon/layout descriptor",\n'
        ' "colors": ["prominent INK colors, most prominent first; ignore the light gray checkerboard"],\n'
        ' "visible_text": "all wording you can read on the artwork",\n'
        ' "collections": [{"key": "...", "sub": "... or null", "confidence": 0.0}],\n'
        ' "tags": ["tag keys from the lists below"],\n'
        ' "style": "one word like vintage, minimal, distressed, script, bold, varsity, floral",\n'
        ' "audience": "who it is for, like mom, grandma, dad, kids, teacher, or empty",\n'
        ' "keywords": ["up to 8 extra search words people would type"],\n'
        ' "protected": true if the artwork shows a pro team, college, artist, brand, or character name or logo}\n\n'
        'Collections (use these keys; sub must belong to that collection):\n' + '\n'.join(places) + '\n\n'
        'Tags (use only these keys):\n' + tags + '\n\n'
        'Rules: choose up to 4 collections, only ones that truly fit, each with an honest confidence from 0 to 1. '
        'Never name a team, artist or school from colors alone; only if the words or logo are visible. '
        'Do not add tags just to add tags. If unsure, give a low confidence.'
    )


def request_classification(file_bytes, api_key, timeout=25):
    """The raw JSON from one vision call, or {} when there is no key or the call fails."""
    if not file_bytes or not (api_key or '').strip():
        return {}
    try:
        import requests
        from utils.design_metadata import _vision_data_url
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key.strip()}', 'Content-Type': 'application/json'},
            json={
                'model': 'gpt-4o-mini', 'temperature': 0, 'max_tokens': 700,
                'response_format': {'type': 'json_object'},
                'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': _prompt()},
                    {'type': 'image_url', 'image_url': {'url': _vision_data_url(file_bytes), 'detail': 'low'}},
                ]}],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return json.loads(response.json()['choices'][0]['message']['content'])
    except Exception:
        return {}


# -- Checking what came back --------------------------------------------------------

def _words_in(text):
    return ' ' + _norm(text) + ' '


def _team_is_visible(tag, evidence):
    """A team tag only counts when its name (or a synonym) is actually written in the evidence text."""
    from utils.design_tags import tag_synonyms
    names = [tag.label, tag.slug.replace('-', ' ')] + tag_synonyms(tag)
    return any(f' {_norm(n)} ' in evidence for n in names if _norm(n))


def _protected_hit(*texts):
    blob = _words_in(' '.join(t for t in texts if t))
    return [w for w in PROTECTED_WORDS if f' {_norm(w)} ' in blob]


def interpret(raw, *, filename='', title_hint=''):
    """Turn raw model output into a checked result. Unknown keys and unsupported teams are dropped."""
    raw = raw if isinstance(raw, dict) else {}
    visible = str(raw.get('visible_text') or '')[:400]
    title = re.sub(r'\s+', ' ', str(raw.get('title') or '')).strip()[:200]
    evidence = _words_in(' '.join([visible, title, title_hint or '', filename or '']))

    tags = vocabulary()
    slugs = clean_tags([str(t) for t in (raw.get('tags') or [])][:30])
    dropped = []
    for slug in list(slugs):
        tag = tags.get(slug)
        if tag and tag.tag_type == 'team' and not _team_is_visible(tag, evidence):
            slugs.remove(slug)
            dropped.append(slug)                      # named a team without its words showing: not trusted

    places = {}
    for item in raw.get('collections') or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '').strip()
        sub = str(item.get('sub') or '').strip() or None
        if key not in COLLECTION_BY_KEY:
            continue
        if sub and not is_valid_pair(key, sub):
            sub = None
        try:
            conf = max(0.0, min(1.0, float(item.get('confidence'))))
        except (TypeError, ValueError):
            conf = 0.0
        if sub and sub.startswith('kc-') and not any(s.startswith('kc-') or s == 'sporting-kc' for s in slugs):
            sub, conf = None, min(conf, 0.6)          # a specific KC team needs its name visible
        old = places.get(key)
        if not old or conf > old['confidence']:
            places[key] = {'key': key, 'sub': sub, 'confidence': conf}
    # a subcategory the tags make obvious, when the model left it blank
    for slug in slugs:
        place = TAG_TO_PLACE.get(slug)
        if place and place[0] in places and not places[place[0]]['sub'] and place[1]:
            places[place[0]]['sub'] = place[1]
    collections = sorted(places.values(), key=lambda p: -p['confidence'])[:MAX_COLLECTIONS]

    keywords = []
    for word in raw.get('keywords') or []:
        word = re.sub(r'\s+', ' ', str(word)).strip().lower()[:40]
        if word and word not in keywords:
            keywords.append(word)
    colors = [re.sub(r'\s+', ' ', str(c)).strip().title() for c in (raw.get('colors') or []) if str(c).strip()][:3]
    audience = re.sub(r'\s+', ' ', str(raw.get('audience') or '')).strip().title()[:60]
    style = re.sub(r'\s+', ' ', str(raw.get('style') or '')).strip().title()[:60]

    hits = _protected_hit(visible, title, title_hint, ' '.join(slugs))
    return {
        'title': title, 'colors': colors, 'visible_text': visible, 'collections': collections,
        'tags': slugs, 'dropped_tags': dropped, 'keywords': keywords[:12], 'style': style, 'audience': audience,
        'protected': bool(raw.get('protected')) or bool(hits), 'protected_words': hits,
        'confidence': collections[0]['confidence'] if collections else 0.0, 'source': 'ai',
    }


def classify_from_text(title='', filename=''):
    """No-internet fallback: file the design from the words in its name, with modest confidence."""
    from utils.design_metadata import clean_filename_title
    text = ' '.join(x for x in (title, clean_filename_title(filename) or '') if x)
    words = _norm(text).split()
    phrases = set(words)
    for n in (2, 3):
        phrases.update(' '.join(words[i:i + n]) for i in range(len(words) - n + 1))
    slugs = clean_tags(sorted(phrases))
    places = {}
    for slug in slugs:
        place = TAG_TO_PLACE.get(slug)
        if place and place[0] not in places:
            places[place[0]] = {'key': place[0], 'sub': place[1], 'confidence': 0.6}
    collections = list(places.values())[:MAX_COLLECTIONS]
    hits = _protected_hit(text, ' '.join(slugs))
    return {
        'title': '', 'colors': [], 'visible_text': '', 'collections': collections, 'tags': slugs,
        'dropped_tags': [], 'keywords': [], 'style': '', 'audience': '', 'protected': bool(hits),
        'protected_words': hits, 'confidence': 0.6 if collections else 0.0, 'source': 'name',
    }


# -- Putting it on the design ---------------------------------------------------------

def apply_classification(design, result, *, chose_folder=False, user_id=None):
    """Write a checked result onto a design. Adds and fills in; never overwrites your locked edits.

    Returns the status: 'done' when it is confident and clear, otherwise 'needs_review'.
    """
    from models import DesignCategoryLink, db
    from datetime import datetime

    confident = [p for p in result['collections'] if p['confidence'] >= AUTO_THRESHOLD]
    unsure = [p for p in result['collections'] if p['confidence'] < AUTO_THRESHOLD]

    existing = {(l.category_key, l.subcategory_key): l for l in DesignCategoryLink.query.filter_by(design_id=design.id)}
    has_primary = any(l.is_primary for l in existing.values())
    for place in confident:
        pair = (place['key'], place['sub'])
        if pair in existing:
            continue
        db.session.add(DesignCategoryLink(
            design_id=design.id, category_key=place['key'], subcategory_key=place['sub'],
            is_primary=not has_primary, source='auto', confidence=place['confidence']))
        has_primary = True

    apply_auto_tags(design, result['tags'], confidence=result['confidence'] or None)

    if result.get('style'):
        set_if_unlocked(design, 'style', result['style'])
    if result.get('audience'):
        set_if_unlocked(design, 'audience', result['audience'])
    if result.get('keywords'):
        merged = [w for w in (design.keywords or '').split(',') if w.strip()]
        for w in result['keywords']:
            if w not in merged:
                merged.append(w)
        set_if_unlocked(design, 'keywords', ','.join(merged)[:1000])

    # keep the gallery you already have working: mirror onto the folder fields (never over a manual choice)
    if not chose_folder and confident and not is_locked(design, 'categories'):
        legacy = [legacy_key_for(p['key']) for p in confident]
        legacy = [k for k in legacy if k]
        design.folder = legacy[0] if legacy else (design.folder or 'evergreen')
        extras = [k for k in legacy[1:] if k != design.folder]
        design.extra_categories = ','.join(extras) or design.extra_categories

    if result.get('visible_text') and not design.art_text:
        design.art_text = result['visible_text'][:400]
    design.ai_confidence = result['confidence']
    design.ai_processed_at = datetime.utcnow()
    design.modified_at = datetime.utcnow()
    suggestions = {'unsure': unsure, 'protected_words': result.get('protected_words') or [],
                   'dropped_tags': result.get('dropped_tags') or [], 'source': result.get('source')}
    design.ai_suggestions = json.dumps(suggestions)

    if result.get('protected') and design.ip_status != 'cleared':
        design.ip_status = 'review'
    clear = bool(confident) or chose_folder
    design.ai_status = 'done' if (clear and design.ip_status != 'review') else 'needs_review'
    return design.ai_status


def link_manual_folders(design, folder_keys):
    """Folders you picked by hand become category links, marked manual and locked."""
    from models import DesignCategoryLink, db
    from utils.design_taxonomy import collection_for_legacy
    have = {(l.category_key, l.subcategory_key) for l in DesignCategoryLink.query.filter_by(design_id=design.id)}
    first = not any(l.is_primary for l in DesignCategoryLink.query.filter_by(design_id=design.id))
    for key in folder_keys or []:
        coll = collection_for_legacy(key)
        if not coll or (coll, None) in have:
            continue
        db.session.add(DesignCategoryLink(design_id=design.id, category_key=coll, subcategory_key=None,
                                          is_primary=first, source='manual', locked=True))
        have.add((coll, None))
        first = False
