"""Shared organization rules for the public and admin design galleries."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class GalleryCategory:
    key: str
    label: str
    storage_key: str
    aliases: tuple[str, ...] = ()


GALLERY_CATEGORIES = (
    GalleryCategory(
        'faith', 'Faith & Inspiration', 'faith',
        ('bible', 'inspirational'),
    ),
    GalleryCategory('sports', 'Sports', 'sports'),
    GalleryCategory('school', 'School', 'school'),
    GalleryCategory('kc', 'Kansas City', 'kc'),
    GalleryCategory('music', 'Music', 'music'),
    GalleryCategory('holiday', 'Holiday', 'holiday', ('seasonal',)),
    GalleryCategory('family', 'Couples & Family', 'couples', ('family',)),
    GalleryCategory('funny', 'Funny', 'funny'),
    GalleryCategory(
        'favorites', 'Fan Favorites', 'evergreen',
        ('custom_orders', 'favorites', 'fan_favorites'),
    ),
    GalleryCategory(
        'luxury', 'Luxury Basics', 'luxury_basics', ('luxury',),
    ),
)

GALLERY_FOLDER_OPTIONS = tuple(
    (category.storage_key, category.label) for category in GALLERY_CATEGORIES
)
GALLERY_FOLDER_KEYS = frozenset(
    [key for key, _label in GALLERY_FOLDER_OPTIONS] + ['custom_orders']
)
GALLERY_CATEGORY_LABELS = {
    category.key: category.label for category in GALLERY_CATEGORIES
}

# Always list these folders on the public gallery, even before any designs
# are filed there. Other empty folders stay hidden so the landing page
# does not grow a row of blank tiles.
ALWAYS_VISIBLE_GALLERY_CATEGORIES = frozenset({'music'})

# Internal Music labels. Stored on extra_categories next to extra folders.
# They never become customer-facing category buttons.
MUSIC_GENRES = (
    ('country', 'Country & Western'),
    ('rock', 'Rock & Roll'),
    ('pop', 'Pop'),
    ('soul', 'Soul/Blues/Jazz'),
    ('reggae', 'Reggae'),
    ('gospel', 'Gospel'),
    ('vintage', 'Vintage Music'),
)
MUSIC_GENRE_KEYS = frozenset(key for key, _label in MUSIC_GENRES)
MUSIC_GENRE_LABELS = {key: label for key, label in MUSIC_GENRES}

_CATEGORY_BY_ALIAS = {}
for _category in GALLERY_CATEGORIES:
    for _value in (
        _category.key,
        _category.storage_key,
        *_category.aliases,
    ):
        _CATEGORY_BY_ALIAS[_value] = _category


def normalize_category(value: str | None) -> str:
    """Return the public category key for a stored folder/tag."""
    cleaned = (value or '').strip().lower()
    category = _CATEGORY_BY_ALIAS.get(cleaned)
    return category.key if category else ''


def storage_key_for(value: str | None) -> str:
    """Return the stored folder key for a public, alias, or storage value."""
    cleaned = (value or '').strip().lower()
    category = _CATEGORY_BY_ALIAS.get(cleaned)
    return category.storage_key if category else ''


def assigned_gallery_folders(form) -> list[str]:
    """Unique storage folder keys from an upload or edit form, in given order."""
    values = []
    getter = getattr(form, 'getlist', None)
    for field in ('extra_categories', 'upload_cats'):
        if callable(getter):
            values.extend(getter(field) or [])
        else:
            raw = form.get(field)
            if raw:
                values.extend(str(raw).split(','))
    folder = (form.get('folder') or '').strip()
    if folder:
        values.append(folder)
    keys = []
    for value in values:
        storage = storage_key_for(value)
        if storage and storage not in keys:
            keys.append(storage)
    return keys


def assigned_music_genres(form) -> list[str]:
    """Unique internal Music genre keys from an upload or edit form."""
    values = []
    getter = getattr(form, 'getlist', None)
    for field in ('music_genres',):
        if callable(getter):
            values.extend(getter(field) or [])
        else:
            raw = form.get(field)
            if raw:
                values.extend(str(raw).split(','))
    keys = []
    for value in values:
        cleaned = (value or '').strip().lower()
        if cleaned in MUSIC_GENRE_KEYS and cleaned not in keys:
            keys.append(cleaned)
    return keys


def stored_music_genres(extra_categories: str | None) -> list[str]:
    """Genre keys already saved on a design, in stored order."""
    keys = []
    for value in (extra_categories or '').split(','):
        cleaned = value.strip().lower()
        if cleaned in MUSIC_GENRE_KEYS and cleaned not in keys:
            keys.append(cleaned)
    return keys


def music_genre_labels(extra_categories: str | None) -> list[str]:
    return [MUSIC_GENRE_LABELS[key] for key in stored_music_genres(extra_categories)]


def public_extra_storage_keys(extra_categories: str | None) -> list[str]:
    """Extra folder keys only. Internal Music genres are left out."""
    keys = []
    for value in (extra_categories or '').split(','):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in MUSIC_GENRE_KEYS:
            continue
        if cleaned not in keys:
            keys.append(cleaned)
    return keys


def compose_extra_categories(
    public_extras: list[str],
    genres: list[str],
) -> str | None:
    """Join extra public folders and internal Music genres for storage."""
    keys = []
    for value in public_extras + genres:
        cleaned = (value or '').strip()
        if not cleaned or cleaned in keys:
            continue
        keys.append(cleaned)
    return ','.join(keys) if keys else None


def design_category_keys(
    folder: str | None,
    extra_categories: str | None = None,
) -> list[str]:
    """Return unique public category keys, preserving their stored order."""
    values = [folder, *((extra_categories or '').split(','))]
    keys = []
    for value in values:
        key = normalize_category(value)
        if key and key not in keys:
            keys.append(key)
    return keys or ['favorites']


def gallery_group_for_title(title: str | None) -> str:
    """Optional familiar team/school subgroup inferred from a design title."""
    text = (title or '').lower()
    rules = (
        (r'\bchief', 'Kansas City Chiefs'),
        (r'\broyal', 'Kansas City Royals'),
        (r'\bsporting\b', 'Sporting KC'),
        (r'\bkc current\b|\bcurrent fc\b', 'KC Current'),
        (r'\bjayhawk', 'KU Jayhawks'),
        (r'\bwildcat\b|\bk-?state\b', 'K-State Wildcats'),
        (r'\bmizzou\b|\bmu tiger', 'Mizzou Tigers'),
        (r'\briverview\b', 'Riverview Falcons'),
        (r'\bfalcon\b', 'Falcons'),
        (r'\beagle\b', 'Eagles'),
        (r'\bbulldog\b', 'Bulldogs'),
        (r'\bbear\b', 'Bears'),
        (r'\bpatriot\b', 'Patriots'),
        (r'\btrojan\b', 'Trojans'),
        (r'\bpanther\b', 'Panthers'),
        (r'\bcardinal\b', 'Cardinals'),
        (r'\btiger\b', 'Tigers'),
        (r'\bhawk\b', 'Hawks'),
    )
    for pattern, label in rules:
        if re.search(pattern, text):
            return label
    return ''
