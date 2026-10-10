"""Multi-team group orders: one organization page, one store per team.

The admin wizard can create several team stores at once (e.g. Rainbow
Cheetahs with Basketball, Soccer and Volleyball). The first team uses the
store the wizard just built; every other team gets a copy of it with its own
jerseys, colors, jersey logos and back-print settings. All of it is added to
the current transaction and nothing is committed here, so a problem never
leaves half an organization behind.
"""
from __future__ import annotations

import json

from models import db, Collection, Organization, OrgSection, Product, ProductColorVariant

# Columns a team store copies from the first store. Identity, timestamps,
# share token and the per-store card text are left out on purpose.
_SKIP_COLUMNS = {
    'id', 'name', 'slug', 'share_token', 'created_at', 'updated_at',
    'card_title', 'team_store_config', 'expected_count',
}

_SPORT_ICONS = (
    ('basketball', '🏀'), ('soccer', '⚽'), ('volleyball', '🏐'),
    ('softball', '🥎'), ('baseball', '⚾'), ('football', '🏈'),
    ('cheer', '📣'), ('track', '🏃'), ('cross country', '🏃'),
    ('swim', '🏊'), ('tennis', '🎾'), ('hockey', '🏒'), ('golf', '⛳'),
    ('wrestling', '🤼'), ('dance', '💃'), ('band', '🎵'), ('choir', '🎵'),
    ('lacrosse', '🥍'), ('bowling', '🎳'), ('gymnastics', '🤸'),
)


class OrgSetupError(ValueError):
    """Shown to the admin as-is; the whole save is rolled back."""


def sport_icon(name):
    lowered = (name or '').lower()
    for word, icon in _SPORT_ICONS:
        if word in lowered:
            return icon
    return '🏷️'


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick(values, idx):
    return values[idx].strip() if idx < len(values) and values[idx] else ''


def _unique(ids):
    out = []
    for pid in ids:
        if pid and pid not in out:
            out.append(pid)
    return out


def team_names_from_form(form):
    return [n.strip() for n in form.getlist('org_team_names[]') if n and n.strip()]


def _unique_slug(model, base):
    from slugify import slugify
    base = slugify(base) or 'group'
    slug, n = base, 1
    while model.query.filter_by(slug=slug).first():
        slug = f'{base}-{n}'
        n += 1
    return slug


def _colors_for(product_ids):
    rows = db.session.query(
        ProductColorVariant.product_id, ProductColorVariant.color_name
    ).filter(ProductColorVariant.product_id.in_(product_ids)).all() if product_ids else []
    colors = {}
    for pid, color in rows:
        if color:
            colors.setdefault(pid, set()).add(color)
    return colors


def team_uniform_from_form(form, idx, team_name, allowed_logo_ids):
    """One team's jersey setup from the per-team cards.

    Returns a uniform dict for team_store_config (``enabled`` False when the
    team has no jersey) or raises OrgSetupError with a message for the admin.
    """
    home_pid = _as_int(_pick(form.getlist('org_team_uniform_product_id[]'), idx))
    youth_pid = _as_int(_pick(form.getlist('org_team_youth_product_id[]'), idx))
    away_pid = _as_int(_pick(form.getlist('org_team_away_product_id[]'), idx))
    away_youth_pid = _as_int(_pick(form.getlist('org_team_away_youth_product_id[]'), idx))
    home_color = _pick(form.getlist('org_team_home_color[]'), idx)
    away_color = _pick(form.getlist('org_team_away_color[]'), idx)
    home_logo = _as_int(_pick(form.getlist('org_team_jersey_logo_id[]'), idx))
    away_logo = _as_int(_pick(form.getlist('org_team_away_jersey_logo_id[]'), idx))

    if not home_pid:
        if youth_pid or away_pid or home_color:
            raise OrgSetupError(f'{team_name}: choose a Home jersey style.')
        return {'enabled': False}
    if not home_color:
        raise OrgSetupError(f'{team_name}: choose a Home jersey color.')

    home_ids = _unique([home_pid, youth_pid])
    away_ids = []
    if away_color:
        if away_color == home_color and not away_pid:
            raise OrgSetupError(f'{team_name}: choose a different Away color, or remove the away jersey.')
        if away_pid:
            # The wizard's youth away menu reads "Same as away jersey", so an
            # empty choice means youth players order the away style too.
            away_ids = _unique([away_pid, away_youth_pid])
        else:
            away_ids = _unique([home_pid, away_youth_pid or youth_pid])
    elif away_pid:
        raise OrgSetupError(f'{team_name}: choose an Away jersey color, or remove the away jersey.')

    product_ids = _unique(home_ids + away_ids)
    active = {p.id for p in Product.query.filter(
        Product.id.in_(product_ids), Product.is_active == True  # noqa: E712
    ).all()}
    missing = [pid for pid in product_ids if pid not in active]
    if missing:
        raise OrgSetupError(f'{team_name}: a selected jersey style is no longer available.')

    colors = _colors_for(product_ids)
    if any(home_color not in colors.get(pid, set()) for pid in home_ids):
        raise OrgSetupError(
            f'{team_name}: the Home color {home_color} is not offered in every Home jersey '
            'style. Pick a color the youth and adult styles both come in.'
        )
    if away_ids and any(away_color not in colors.get(pid, set()) for pid in away_ids):
        raise OrgSetupError(
            f'{team_name}: the Away color {away_color} is not offered in every Away jersey '
            'style. Pick a color the youth and adult styles both come in.'
        )

    if home_logo not in allowed_logo_ids:
        home_logo = None
    if away_logo not in allowed_logo_ids or away_logo == home_logo:
        away_logo = None

    return {
        'enabled': True,
        'product_id': product_ids[0],
        'product_ids': product_ids,
        'home_color': home_color,
        'away_color': away_color if away_ids else '',
        'home_design_id': home_logo,
        'away_design_id': away_logo,
        'home_product_ids': home_ids,
        'away_product_ids': away_ids,
    }


def _load_config(collection):
    try:
        parsed = json.loads(collection.team_store_config or '{}')
    except (TypeError, ValueError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _apply_uniform(store, uniform, fan_ids):
    """Point the store at this team's jersey plus the shared fan wear."""
    config = _load_config(store)
    jersey_ids = set(uniform.get('product_ids') or [])
    fan_ids = [pid for pid in fan_ids if pid not in jersey_ids]
    config['version'] = 1
    config['uniform'] = uniform
    config['fan_product_ids'] = fan_ids
    config.setdefault('fan_personalization_enabled', False)
    store.team_store_config = json.dumps(config, separators=(',', ':'))

    wanted = _unique((uniform.get('product_ids') or []) + list(fan_ids))
    by_id = {p.id: p for p in Product.query.filter(Product.id.in_(wanted)).all()} if wanted else {}
    store.products = [by_id[pid] for pid in wanted if pid in by_id]


def _copy_store(source, name, slug):
    values = {
        col.name: getattr(source, col.name)
        for col in Collection.__table__.columns
        if col.name not in _SKIP_COLUMNS
    }
    store = Collection(name=name, slug=slug, **values)
    store.team_store_config = source.team_store_config
    store.products = list(source.products)
    return store


def _ids(raw):
    try:
        parsed = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        parsed = []
    return [i for i in (_as_int(v) for v in parsed if v is not None) if i]


def _apply_team_logos(stores, uniforms):
    """Each team's store offers its own jersey logos, not the other teams'.

    Logos that no team picked for a jersey stay available everywhere (shared
    spirit-wear art). The jersey logo is listed first at the top of the store.
    """
    team_logos = []
    for uniform in uniforms:
        logos = [i for i in (uniform.get('home_design_id'), uniform.get('away_design_id')) if i]
        team_logos.append(logos)
    claimed = {i for logos in team_logos for i in logos}
    if not claimed:
        return
    for store, logos in zip(stores, team_logos):
        if not logos:
            continue  # no jersey logo picked: this team keeps every logo
        allowed = _ids(store.allowed_design_ids)
        keep = _unique(logos + [i for i in allowed if i not in claimed or i in logos])
        store.allowed_design_ids = json.dumps(keep) if keep else None
        showcase = _ids(store.showcase_design_ids)
        show = _unique(logos + [i for i in showcase if i in keep])
        store.showcase_design_ids = json.dumps(show) if show else None


def _apply_per_team_back(form, stores):
    if form.get('back_design_per_team') != 'different':
        return
    types = form.getlist('org_team_back_design_type[]')
    name_parts = form.getlist('org_team_back_name_part[]')
    fonts = form.getlist('org_team_back_font[]')
    text_colors = form.getlist('org_team_back_text_color[]')
    outlines = form.getlist('org_team_back_outline[]')
    outline_colors = form.getlist('org_team_back_outline_color[]')
    for idx, store in enumerate(stores):
        if idx < len(types):
            bt = types[idx]
            store.allow_back_design = bt != 'none'
            store.back_design_type = bt if bt in ('name_number', 'image', 'both') else 'both'
        if idx < len(name_parts):
            part = name_parts[idx].strip().lower()
            store.back_design_name_part = part if part in ('first', 'last') else 'last'
        if idx < len(fonts):
            store.back_design_font = fonts[idx] or None
        if idx < len(text_colors):
            store.back_design_text_color = text_colors[idx] or None
        if idx < len(outlines):
            store.back_design_outline = outlines[idx] == 'on'
        if idx < len(outline_colors):
            store.back_design_outline_color = outline_colors[idx] or None


def create_org_from_wizard(collection, form, user):
    """Build the organization and one store per team. Does not commit.

    Returns (organization, stores). Raises OrgSetupError for bad input.
    """
    team_names = team_names_from_form(form)
    if not team_names:
        raise OrgSetupError('Enter at least one team name, or uncheck the multi-team option.')
    lowered = [n.lower() for n in team_names]
    if len(set(lowered)) != len(lowered):
        raise OrgSetupError('Each team needs a different name.')

    org_name = collection.name.strip()
    per_team = form.get('org_style_mode') == 'different'
    base_config = _load_config(collection)
    fan_ids = [i for i in (_as_int(v) for v in base_config.get('fan_product_ids') or []) if i]
    allowed_logo_ids = set(_ids(collection.allowed_design_ids))

    # Validate every team before writing anything.
    uniforms = []
    if per_team:
        for idx, name in enumerate(team_names):
            uniforms.append(team_uniform_from_form(form, idx, name, allowed_logo_ids))
        if not any(u.get('enabled') for u in uniforms) and not fan_ids:
            raise OrgSetupError('Choose a jersey for at least one team, or pick some fan wear styles.')
        for name, uniform in zip(team_names, uniforms):
            if not uniform.get('enabled') and not fan_ids:
                raise OrgSetupError(f'{name}: choose a jersey, or add fan wear styles for this store.')

    org = Organization(
        name=org_name,
        slug=_unique_slug(Organization, org_name),
        created_by_user_id=getattr(user, 'id', None),
        is_active=True,
    )
    db.session.add(org)
    db.session.flush()

    multi = len(team_names) > 1
    if multi:
        collection.name = f'{team_names[0]}: {org_name}'
    stores = [collection]
    for name in team_names[1:]:
        store = _copy_store(
            collection,
            name=f'{name}: {org_name}',
            slug=_unique_slug(Collection, f'{org_name}-{name}'),
        )
        db.session.add(store)
        stores.append(store)
    db.session.flush()

    if per_team:
        for store, uniform in zip(stores, uniforms):
            _apply_uniform(store, uniform, fan_ids)
        _apply_team_logos(stores, uniforms)
        _apply_per_team_back(form, stores)

    for sort_idx, (name, store) in enumerate(zip(team_names, stores)):
        db.session.add(OrgSection(
            organization_id=org.id,
            collection_id=store.id,
            label=name[:100],
            icon=sport_icon(name),
            sort_order=sort_idx,
        ))
    db.session.flush()
    return org, stores


def add_store_to_org(collection, form):
    """Attach a new store to an existing organization. Does not commit."""
    org_id = _as_int((form.get('org_existing_id') or '').strip())
    org = Organization.query.get(org_id) if org_id else None
    if not org:
        return None
    exists = OrgSection.query.filter_by(organization_id=org.id, collection_id=collection.id).first()
    if not exists:
        label = (form.get('org_section_label') or collection.name).strip() or collection.name
        db.session.add(OrgSection(
            organization_id=org.id,
            collection_id=collection.id,
            label=label[:100],
            icon=(form.get('org_section_icon') or '').strip()[:10] or sport_icon(label),
            sort_order=OrgSection.query.filter_by(organization_id=org.id).count(),
        ))
    return org
