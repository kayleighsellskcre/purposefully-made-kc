"""One Fan Wear store for each organization.

Fan Wear belongs to the whole organization, not to Basketball or Volleyball, so
it gets a store of its own. That keeps every team's orders and Excel file about
that team only, and gives Fan Wear its own orders and its own Excel file.

The store is kept in step with what the organizer set on the Fan Wear page
(styles, colors, designs) and with the teams' dates, so nobody has to manage it
by hand. Everything here adds to the current transaction; the caller commits.
A problem in here is logged and swallowed: it must never block a team or Fan
Wear save.
"""
import json

from models import Collection, OrgSection, Product, db

FAN_LABEL = 'Fan Wear'
FAN_ICON = '👕'
_FLAG = 'org_fan_store'


def _config(collection):
    try:
        parsed = json.loads(collection.team_store_config or '{}')
    except (TypeError, ValueError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def is_auto_fan_store(collection):
    """True for a Fan Wear store this module built (a hand-made one is never touched)."""
    return bool(collection is not None and _config(collection).get(_FLAG))


def _fan_section(org):
    from utils.group_orders import _is_fan_label
    for sec in org.sections.order_by(OrgSection.sort_order).all():
        if sec.collection and _is_fan_label(sec.label):
            return sec
    return None


def fan_store_for(org):
    """The org's Fan Wear store (made by us or by hand), or None."""
    sec = _fan_section(org)
    return sec.collection if sec else None


def _span(teams):
    """(opens, closes) for Fan Wear: it opens with the first team and closes with the last.

    A team with no date means no limit, so Fan Wear gets no date either.
    """
    opens = [t.order_opens_at for t in teams]
    closes = [t.order_deadline for t in teams]
    return (min(opens) if opens and all(opens) else None,
            max(closes) if closes and all(closes) else None)


def _fill(store, org, teams, state, lead):
    from utils.group_orders import team_store_config

    lead_cfg = team_store_config(lead)
    fan_ids = state['fan_product_ids']
    cfg = _config(store)
    # Designs added on the Fan Wear store itself belong to Fan Wear alone. They are told apart from designs that merely
    # came from a team (and were later taken off it) by remembering which ones were pooled at the last sync. The first sync
    # only records that baseline, so nothing already there is ever kept by mistake.
    pooled_now = sorted({int(i) for i in state['design_ids']})
    own = []
    if 'fan_pooled_ids' in cfg:
        before = {int(i) for i in cfg.get('fan_pooled_ids') or []}
        try:
            current = [int(i) for i in json.loads(store.allowed_design_ids or '[]') if str(i).isdigit()]
        except (TypeError, ValueError):
            current = []
        own = [i for i in current if i not in pooled_now and i not in before]
    cfg['fan_pooled_ids'] = pooled_now
    cfg.update({
        'version': 1,
        _FLAG: True,
        'uniform': {'enabled': False},
        'fan_product_ids': list(fan_ids),
        'fan_show_jersey_logo': True,
        'fanwear_excluded_ids': sorted({
            i for i in state['design_ids'] if i not in state['shown_design_ids']
        }),
        'fan_personalization_enabled': bool(lead_cfg['fan_personalization_enabled']),
    })
    store.team_store_config = json.dumps(cfg, separators=(',', ':'))
    by_id = {p.id: p for p in Product.query.filter(Product.id.in_(fan_ids)).all()} if fan_ids else {}
    store.products = [by_id[i] for i in fan_ids if i in by_id]
    store.allowed_colors = lead.allowed_colors
    shown = list(state['shown_design_ids'])
    shown = own + [i for i in shown if i not in own]      # Fan Wear's own artwork first, then the teams' pooled designs
    store.allowed_design_ids = json.dumps(shown) if shown else None
    store.showcase_design_ids = None
    store.order_opens_at, store.order_deadline = _span(teams)
    store.description = org.description or lead.description
    store.cover_image = None
    store.back_design_id = None
    store.allow_back_design = bool(
        lead.allow_back_design
        and (not lead_cfg['uniform']['enabled'] or lead_cfg['fan_personalization_enabled'])
    )
    store.is_password_protected = lead.is_password_protected
    store.password_hash = lead.password_hash
    store.show_in_directory = False       # shoppers find it from the organization page
    store.is_active = bool(fan_ids)


def sync_org_fan_store(org):
    """Create or refresh the org's Fan Wear store. Returns it, or None.

    Never raises. Safe to call after any team or Fan Wear change.
    """
    try:
        # A savepoint: if anything in here fails, only this part is undone and the
        # team or Fan Wear save that called us still goes through.
        with db.session.begin_nested():
            return _sync(org)
    except Exception:
        from flask import current_app
        current_app.logger.exception('could not sync the Fan Wear store for organization %s',
                                     getattr(org, 'id', '?'))
        return None


def _sync(org):
    from utils.group_org import _unique_slug
    from utils.group_orders import _team_sections, org_fan_wear_state

    existing = fan_store_for(org)
    if existing is not None and not is_auto_fan_store(existing):
        return existing                      # someone built Fan Wear by hand: leave it alone

    teams = [sec.collection for sec in _team_sections(org)]
    state = org_fan_wear_state(org)
    lead = state['lead']
    if lead is None:
        if existing is not None:
            existing.is_active = False       # no teams left: nothing to sell
        return existing

    if existing is None:
        if not state['fan_product_ids']:
            return None                      # nothing for fans yet: no store needed
        from utils.group_org import _copy_store
        existing = _copy_store(
            lead,
            name=f'{FAN_LABEL}: {org.name}',
            slug=_unique_slug(Collection, f'{org.name}-fan-wear'),
        )
        db.session.add(existing)
        db.session.flush()
        last = db.session.query(db.func.max(OrgSection.sort_order)).filter_by(
            organization_id=org.id).scalar() or 0
        db.session.add(OrgSection(
            organization_id=org.id, collection_id=existing.id,
            label=FAN_LABEL, icon=FAN_ICON, sort_order=last + 1,
        ))
    _fill(existing, org, teams, state, lead)
    db.session.flush()
    return existing


def retire_org_fan_store(org):
    """Take the Fan Wear store off the site when its organization is deleted (orders stay)."""
    store = fan_store_for(org)
    if store is not None and is_auto_fan_store(store):
        store.is_active = False
        store.show_in_directory = False


def managing_org(collection):
    """The organization when ``collection`` is its automatic Fan Wear store, else None.

    That store's styles and colors follow the Fan Wear page (and the teams), so its own edit page points there.
    """
    try:
        if collection is None or not is_auto_fan_store(collection):
            return None
        from utils.group_orders import org_for_collection
        return org_for_collection(collection)[0]
    except Exception:
        return None
