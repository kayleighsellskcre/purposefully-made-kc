"""One standard vocabulary of design tags, so the library never fills up with near-duplicates.

* Every tag has one canonical name, a type, and synonyms ("Mama", "Mommy", "Mother" -> Mom).
* A tag can imply others ("Football Mom" -> Football + Mom).
* A tag can be "related" to others: searching Grandma also finds Nana and Mimi, but they
  stay separate tags because they are not the same word.
* Corrections you make are saved and locked: automation may add to a design, but it never
  removes or overwrites something you set by hand.
"""
import json
import re

TAG_TYPES = (
    ('theme', 'Theme'),
    ('team', 'Team'),
    ('sport', 'Sport'),
    ('recipient', 'Recipient'),
    ('style', 'Style'),
    ('color', 'Color'),
    ('occasion', 'Occasion'),
    ('holiday', 'Holiday'),
    ('hobby', 'Hobby'),
    ('collection', 'Collection'),
    ('control', 'Gallery control'),
)
TAG_TYPE_LABELS = dict(TAG_TYPES)

# (slug, label, type, synonyms, implies, related)
SEED_TAGS = [
    # Recipients
    ('mom', 'Mom', 'recipient', ['mama', 'mommy', 'mother', 'mum', 'mamma', 'momma'], [], []),
    ('dad', 'Dad', 'recipient', ['daddy', 'father', 'papa', 'pops'], [], []),
    ('grandma', 'Grandma', 'recipient', ['grandmother', 'granny', 'gran', 'grammy', 'gigi'], [], ['nana', 'mimi']),
    ('nana', 'Nana', 'recipient', [], [], ['grandma', 'mimi']),
    ('mimi', 'Mimi', 'recipient', [], [], ['grandma', 'nana']),
    ('grandpa', 'Grandpa', 'recipient', ['grandfather', 'granddad', 'pawpaw', 'papaw'], [], []),
    ('aunt', 'Aunt', 'recipient', ['auntie', 'aunty'], [], []),
    ('uncle', 'Uncle', 'recipient', ['unc'], [], []),
    ('kids', 'Kids', 'recipient', ['kid', 'child', 'children', 'youth'], [], []),
    ('baby', 'Baby', 'recipient', ['infant', 'newborn', 'toddler'], [], ['kids']),
    ('sister', 'Sister', 'recipient', ['sis', 'sisters'], [], []),
    ('brother', 'Brother', 'recipient', ['bro', 'brothers'], [], []),
    ('bestie', 'Best Friends', 'recipient', ['besties', 'best friend', 'bff', 'friends', 'girls trip'], [], []),
    ('couple', 'Couples', 'recipient', ['couples', 'his and hers', 'mr and mrs', 'husband', 'wife'], [], []),
    ('teacher', 'Teacher', 'recipient', ['teachers', 'educator'], [], []),
    ('coach', 'Coach', 'recipient', ['coaches'], [], []),
    # Sports
    ('football', 'Football', 'sport', ['gridiron', 'touchdown'], [], []),
    ('baseball', 'Baseball', 'sport', [], [], ['softball']),
    ('softball', 'Softball', 'sport', [], [], ['baseball']),
    ('soccer', 'Soccer', 'sport', ['futbol'], [], []),
    ('basketball', 'Basketball', 'sport', ['hoops', 'bball'], [], []),
    ('volleyball', 'Volleyball', 'sport', ['vball'], [], []),
    ('cheer', 'Cheer', 'sport', ['cheerleader', 'cheerleading'], [], ['dance']),
    ('dance', 'Dance', 'sport', ['dancer'], [], ['cheer']),
    ('track', 'Track & Field', 'sport', ['cross country', 'running'], [], []),
    ('golf', 'Golf', 'sport', ['golfer'], [], []),
    # Teams
    ('kc-chiefs', 'KC Chiefs', 'team', ['kansas city chiefs', 'chiefs', 'chiefs kingdom', 'arrowhead'], ['football'], []),
    ('kc-royals', 'KC Royals', 'team', ['kansas city royals', 'royals'], ['baseball'], []),
    ('kc-current', 'KC Current', 'team', ['kansas city current', 'current fc'], ['soccer'], []),
    ('sporting-kc', 'Sporting KC', 'team', ['sporting kansas city', 'sporting'], ['soccer'], []),
    ('ku-jayhawks', 'KU Jayhawks', 'team', ['jayhawks', 'rock chalk', 'kansas jayhawks'], [], []),
    ('k-state-wildcats', 'K-State Wildcats', 'team', ['kstate', 'k state', 'wildcats', 'powercat'], [], []),
    ('mizzou-tigers', 'Mizzou Tigers', 'team', ['mizzou', 'missouri tigers'], [], []),
    # Themes
    ('kansas-city', 'Kansas City', 'theme', ['kc', 'kcmo', 'kck', 'kc pride', 'the city of fountains'], [], []),
    ('faith', 'Faith', 'theme', ['faith based', 'christian', 'god', 'jesus', 'blessed'], [], []),
    ('scripture', 'Scripture', 'theme', ['bible', 'bible verse', 'biblical', 'psalm', 'verse'], ['faith'], []),
    ('encouragement', 'Encouragement', 'theme', ['encouraging', 'you got this'], [], []),
    ('inspirational', 'Inspirational', 'theme', ['inspire', 'motivational', 'motivation'], [], []),
    ('affirmation', 'Positive Affirmation', 'theme', ['affirmations', 'positive vibes', 'good vibes'], [], []),
    ('funny', 'Funny', 'theme', ['humor', 'humorous', 'hilarious', 'joke'], [], []),
    ('sarcasm', 'Sarcasm', 'theme', ['sarcastic', 'sassy', 'sass'], ['funny'], []),
    ('country-music', 'Country Music', 'theme', ['country', 'nashville', 'honky tonk'], [], []),
    ('rock', 'Rock & Roll', 'theme', ['rock and roll', 'rockstar', 'band tee'], [], []),
    ('concert', 'Concert & Tour', 'theme', ['tour', 'concert tee', 'eras'], [], []),
    ('music-lover', 'Music Lover', 'theme', ['music', 'musician', 'vinyl'], [], []),
    ('pop-culture', 'Pop Culture', 'theme', ['movie', 'tv show', 'celebrity'], [], []),
    ('school-spirit', 'School Spirit', 'theme', ['spirit wear', 'spirit week', 'mascot', 'school pride'], [], []),
    ('western', 'Western', 'theme', ['cowgirl', 'cowboy', 'rodeo', 'howdy', 'yeehaw'], [], []),
    # Styles
    ('vintage', 'Vintage', 'style', ['retro', 'old school', 'throwback'], [], []),
    ('distressed', 'Distressed', 'style', ['grunge', 'weathered', 'worn'], [], []),
    ('minimal', 'Minimal', 'style', ['minimalist', 'simple', 'clean'], [], []),
    ('bold', 'Bold', 'style', ['block letters', 'statement'], [], []),
    ('script', 'Script', 'style', ['handwritten', 'cursive', 'calligraphy'], [], []),
    ('varsity', 'Varsity', 'style', ['collegiate', 'athletic lettering'], [], []),
    ('boho', 'Boho', 'style', ['bohemian'], [], []),
    ('floral', 'Floral', 'style', ['flowers', 'botanical'], [], []),
    ('glitter', 'Glitter', 'style', ['sparkle', 'sparkly', 'foil'], [], []),
    ('leopard', 'Leopard Print', 'style', ['cheetah print', 'animal print'], [], []),
    # Holidays and occasions
    ('christmas', 'Christmas', 'holiday', ['xmas', 'merry', 'santa', 'holiday season'], [], []),
    ('halloween', 'Halloween', 'holiday', ['spooky', 'trick or treat', 'pumpkin', 'witchy'], [], []),
    ('thanksgiving', 'Thanksgiving', 'holiday', ['turkey', 'grateful', 'thankful', 'fall'], [], []),
    ('fall', 'Fall', 'holiday', ['autumn', 'pumpkin spice'], [], []),
    ('valentines', "Valentine's Day", 'holiday', ['valentine', 'galentine', 'heart', 'love'], [], []),
    ('easter', 'Easter', 'holiday', ['bunny', 'egg hunt', 'he is risen'], [], []),
    ('spring', 'Spring', 'holiday', [], [], []),
    ('summer', 'Summer', 'holiday', ['beach', 'pool', 'vacation vibes'], [], []),
    ('patriotic', 'Patriotic', 'holiday', ['4th of july', 'fourth of july', 'usa', 'america', 'memorial day', 'red white and blue'], [], []),
    ('new-years', "New Year's", 'holiday', ['nye', 'new year'], [], []),
    ('st-patricks', "St. Patrick's Day", 'holiday', ['st patricks', 'lucky', 'shamrock'], [], []),
    ('mothers-day', "Mother's Day", 'holiday', ['mothers day'], ['mom'], []),
    ('fathers-day', "Father's Day", 'holiday', ['fathers day'], ['dad'], []),
    ('graduation', 'Graduation', 'occasion', ['grad', 'class of'], [], []),
    ('game-day', 'Game Day', 'occasion', ['gameday', 'tailgate', 'sunday funday'], [], []),
    ('birthday', 'Birthday', 'occasion', ['bday', 'birthday girl', 'birthday crew'], [], []),
    ('wedding', 'Wedding', 'occasion', ['bride', 'bridal', 'bachelorette', 'groom'], [], []),
    ('back-to-school', 'Back to School', 'occasion', ['first day of school', 'school year'], [], []),
    ('family-vacation', 'Family Vacation', 'occasion', ['vacation', 'family trip', 'girls trip'], [], []),
    # Hobbies and interests
    ('coffee', 'Coffee & Drinks', 'hobby', ['latte', 'espresso', 'iced coffee', 'caffeine', 'tea', 'wine'], [], []),
    ('outdoors', 'Outdoors & Adventure', 'hobby', ['camping', 'hiking', 'fishing', 'hunting', 'adventure', 'national park'], [], []),
    ('pets', 'Animals & Pet Lovers', 'hobby', ['dog', 'cat', 'pet', 'puppy', 'dog mom', 'cat mom', 'animal lover'], [], []),
    ('books', 'Books & Reading', 'hobby', ['reading', 'reader', 'bookworm', 'librarian'], [], []),
    ('hobbies', 'Hobbies & Interests', 'hobby', ['crafting', 'gardening', 'baking', 'travel'], [], []),
    # Combined phrases that stand for several tags at once
    ('football-mom', 'Football Mom', 'theme', ['football mama', 'football mommy'], ['football', 'mom'], []),
    ('baseball-mom', 'Baseball Mom', 'theme', ['baseball mama'], ['baseball', 'mom'], []),
    ('soccer-mom', 'Soccer Mom', 'theme', ['soccer mama'], ['soccer', 'mom'], []),
    ('basketball-mom', 'Basketball Mom', 'theme', ['basketball mama'], ['basketball', 'mom'], []),
    ('cheer-mom', 'Cheer Mom', 'theme', ['cheer mama'], ['cheer', 'mom'], []),
    ('dog-mom', 'Dog Mom', 'theme', ['dog mama', 'fur mama'], ['pets', 'mom'], []),
    ('game-day-mom', 'Game Day Mom', 'theme', ['gameday mama'], ['game-day', 'mom'], []),
    # Collections (manual or suggested; not automatic subjects)
    ('matching-set', 'Matching Set', 'collection', ['coordinating', 'matching family', 'matching designs'], [], []),
    ('mama-and-mini', 'Mama & Mini', 'collection', ['mama and mini', 'mommy and me', 'mom and mini'], ['mom', 'matching-set'], []),
    ('couples-set', 'Couples Set', 'collection', ['his and hers set'], ['couple', 'matching-set'], []),
    ('besties-set', 'Best Friends Set', 'collection', ['matching besties'], ['bestie', 'matching-set'], []),
    ('family-set', 'Family Set', 'collection', ['matching family set'], ['matching-set'], []),
    # Gallery controls (you set these by hand; automation never uses them)
    ('fan-favorite', 'Pin to Fan Favorites', 'control', [], [], []),
    ('hide-favorite', 'Keep out of Fan Favorites', 'control', [], [], []),
]


def slugify(text):
    text = re.sub(r"[^a-z0-9]+", '-', (text or '').lower().replace("'", '')).strip('-')
    return text[:60]


def _norm(text):
    return re.sub(r'\s+', ' ', re.sub(r"[^a-z0-9 ]+", ' ', (text or '').lower().replace("'", ''))).strip()


def _loads(raw):
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else (raw or [])
    except (TypeError, ValueError):
        data = []
    return [str(x) for x in data] if isinstance(data, list) else []


def ensure_vocabulary():
    """Add any seed tag that is missing. Never changes a tag that already exists (your edits stay)."""
    from models import DesignTag, db
    existing = {t.slug for t in DesignTag.query.with_entities(DesignTag.slug).all()}
    added = 0
    for slug, label, tag_type, synonyms, implies, related in SEED_TAGS:
        if slug in existing:
            continue
        db.session.add(DesignTag(slug=slug, label=label, tag_type=tag_type,
                                 synonyms=json.dumps(synonyms), implies=json.dumps(implies),
                                 related=json.dumps(related), is_active=True))
        added += 1
    if added:
        db.session.commit()
    return added


def vocabulary(active_only=True):
    """{slug: tag row} for the whole vocabulary."""
    from models import DesignTag
    query = DesignTag.query
    if active_only:
        query = query.filter(DesignTag.is_active == True)  # noqa: E712
    return {t.slug: t for t in query.all()}


def _lookup(tags):
    """{normalized word or phrase: tag} covering labels, slugs and synonyms."""
    index = {}
    ordered = sorted(tags.values(), key=lambda t: t.slug)
    for tag in ordered:                                   # a tag's own name always wins
        for word in (tag.label, tag.slug.replace('-', ' ')):
            key = _norm(word)
            if key and key not in index:
                index[key] = tag
    for tag in ordered:                                   # then synonyms, first come first served
        for word in tag_synonyms(tag):
            key = _norm(word)
            if key and key not in index:
                index[key] = tag
    return index


def tag_synonyms(tag):
    return _loads(tag.synonyms)


def tag_implies(tag):
    return _loads(tag.implies)


def tag_related(tag):
    return _loads(tag.related)


def canonical_for(text):
    """The canonical tag for a word or phrase ("Mama" -> Mom), or None. Never invents a tag."""
    return _lookup(vocabulary()).get(_norm(text))


def with_implied(slugs):
    """The given tag slugs plus everything they imply ("football-mom" -> football, mom)."""
    tags = vocabulary()
    out = []

    def add(slug):
        if slug in tags and slug not in out:
            out.append(slug)
            for nxt in tag_implies(tags[slug]):
                add(nxt)
    for slug in slugs:
        add(slug)
    return out


def clean_tags(words):
    """Turn loose words from the AI or a form into canonical tag slugs: deduped, known tags only."""
    index = _lookup(vocabulary())
    found = []
    for word in words or []:
        tag = index.get(_norm(word))
        if tag and tag.slug not in found:
            found.append(tag.slug)
    return with_implied(found)


def search_terms(query):
    """What to look for when someone searches: the words, their synonyms, and (lower weight) related tags.

    Returns {'exact': set(words), 'related': set(words)}. "Grandma" finds Grandma designs first,
    then Nana and Mimi designs; "Mama" finds Mom designs.
    """
    tags = vocabulary()
    index = _lookup(tags)
    q = _norm(query)
    exact, related = set(), set()
    if not q:
        return {'exact': exact, 'related': related}
    exact.update(q.split())
    hits = []
    if q in index:
        hits.append(index[q])
    else:
        for word in q.split():
            if word in index:
                hits.append(index[word])
    for tag in hits:
        exact.add(_norm(tag.label))
        exact.update(_norm(s) for s in tag_synonyms(tag))
        for slug in tag_related(tag):
            other = tags.get(slug)
            if other:
                related.add(_norm(other.label))
    return {'exact': {w for w in exact if w}, 'related': related - exact}


# ── Per-design tags, with your edits protected ────────────────────────────────

def design_tag_slugs(design):
    from models import DesignTag, DesignTagLink, db
    rows = (db.session.query(DesignTag.slug)
            .join(DesignTagLink, DesignTagLink.tag_id == DesignTag.id)
            .filter(DesignTagLink.design_id == design.id).all())
    return [r[0] for r in rows]


def apply_auto_tags(design, slugs, confidence=None):
    """Add automatic tags to a design. Adds only: it never removes a tag, and never touches a tag you set."""
    from models import DesignTag, DesignTagLink, db
    tags = vocabulary()
    have = {l.tag_id: l for l in DesignTagLink.query.filter_by(design_id=design.id).all()}
    added = []
    for slug in with_implied(slugs):
        tag = tags.get(slug)
        if not tag or tag.id in have:
            continue
        db.session.add(DesignTagLink(design_id=design.id, tag_id=tag.id, source='auto', confidence=confidence))
        added.append(slug)
    return added


def set_manual_tags(design, slugs, user_id=None):
    """You decide the tags: exactly this list. Removed tags are remembered so automation never re-adds them."""
    from models import DesignTag, DesignTagLink, db
    tags = vocabulary(active_only=False)
    wanted = {tags[s].id: s for s in slugs if s in tags}
    current = {l.tag_id: l for l in DesignTagLink.query.filter_by(design_id=design.id).all()}
    for tag_id, link in list(current.items()):
        if tag_id not in wanted:
            if link.source == 'auto' and not link.locked:
                record_correction(design, 'tag', next((t.slug for t in tags.values() if t.id == tag_id), str(tag_id)),
                                  '', 'tag_removed', user_id=user_id)
            db.session.delete(link)
    for tag_id, slug in wanted.items():
        link = current.get(tag_id)
        if link is None:
            db.session.add(DesignTagLink(design_id=design.id, tag_id=tag_id, source='manual', locked=True))
        else:
            link.source, link.locked = 'manual', True
    design.modified_at = _now()
    return sorted(wanted.values())


# ── Locks and the correction history ──────────────────────────────────────────

def _now():
    from datetime import datetime
    return datetime.utcnow()


def locked_fields(design):
    return set(_loads(getattr(design, 'locked_fields', None)))


def is_locked(design, field):
    return field in locked_fields(design)


def lock_field(design, field, locked=True):
    fields = locked_fields(design)
    (fields.add if locked else fields.discard)(field)
    design.locked_fields = json.dumps(sorted(fields))


def record_correction(design, field, original, corrected, correction_type, *, user_id=None, lock=True):
    """Remember a change you made to something automation set: what it was, what you made it, and lock it."""
    from models import DesignCorrection, db
    row = DesignCorrection(design_id=design.id, field=field, original_value=str(original or '')[:2000],
                           corrected_value=str(corrected or '')[:2000], correction_type=correction_type,
                           locked=bool(lock), user_id=user_id)
    db.session.add(row)
    if lock and field in ('title', 'colors', 'style', 'audience', 'keywords', 'categories'):
        lock_field(design, field)
    design.modified_at = _now()
    return row


def set_if_unlocked(design, field, value, *, attr=None):
    """Automation writes a value only when you have not locked that field. Returns True when it wrote."""
    if is_locked(design, field):
        return False
    setattr(design, attr or field, value)
    return True
