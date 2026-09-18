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
