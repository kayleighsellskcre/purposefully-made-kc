"""Remove group stores, schools and districts in bulk, without ever losing an order or a sign-up.

A store with no orders, roster names or sponsor requests is deleted for good. One that has any of those is turned off
and kept (it disappears for shoppers and from the directory, and its orders stay on the books).
"""
from __future__ import annotations

from sqlalchemy import text

from models import (CompanyInvoice, GroupRosterEntry, LedgerEntry, Order, OrderItem, Organization, OrgSection,
                    PaymentCapture, SponsorSubmission, db)


def store_activity(store):
    """What would be lost by deleting this store: {'orders', 'names', 'requests'}."""
    orders = Order.query.filter(db.or_(
        Order.collection_id == store.id,
        Order.id.in_(db.session.query(OrderItem.order_id).filter(OrderItem.collection_id == store.id)),
    )).count()
    return {'orders': orders,
            'names': GroupRosterEntry.query.filter_by(collection_id=store.id).count(),
            'requests': SponsorSubmission.query.filter_by(collection_id=store.id).count()
                        + CompanyInvoice.query.filter_by(collection_id=store.id).count()
                        + PaymentCapture.query.filter_by(collection_id=store.id).count()
                        + LedgerEntry.query.filter_by(collection_id=store.id).count()}


def has_activity(store):
    return any(store_activity(store).values())


def _hard_delete(store):
    cid = store.id
    org_ids = [s.organization_id for s in OrgSection.query.filter_by(collection_id=cid).all()]
    db.session.query(OrgSection).filter(OrgSection.collection_id == cid).delete(synchronize_session=False)
    db.session.execute(text('DELETE FROM collection_products WHERE collection_id = :cid'), {'cid': cid})
    db.session.flush()
    db.session.delete(store)
    db.session.flush()
    return org_ids


def remove_stores(stores):
    """Delete or turn off each store. Returns (names deleted, names kept and turned off). Commits."""
    deleted, kept, touched_orgs = [], [], set()
    for store in stores:
        name = store.name
        if has_activity(store):
            store.is_active = False
            store.show_in_directory = False
            kept.append(name)
        else:
            touched_orgs.update(_hard_delete(store))
            deleted.append(name)
    db.session.commit()
    for org_id in touched_orgs:                       # an organization's Fan Wear store follows its remaining teams
        org = db.session.get(Organization, org_id)
        if org is not None and not org.district_id:
            try:
                from utils.org_fan_store import sync_org_fan_store
                sync_org_fan_store(org)
                db.session.commit()
            except Exception:
                db.session.rollback()
    return deleted, kept


def _org_stores(org):
    return [sec.collection for sec in org.sections.all() if sec.collection is not None]


def remove_organization(org):
    """Delete an organization or school with all its stores, or turn it off when any store has orders.

    Returns ('deleted' | 'kept', stores deleted, stores kept). Commits.
    """
    stores = _org_stores(org)
    deleted, kept = remove_stores(stores)
    if kept:
        org.is_active = False
        db.session.commit()
        return 'kept', deleted, kept
    db.session.query(OrgSection).filter(OrgSection.organization_id == org.id).delete(synchronize_session=False)
    db.session.delete(org)
    db.session.commit()
    return 'deleted', deleted, kept


def remove_district(district):
    """Delete a district with every school and store, or turn off whatever has activity. Commits."""
    schools = district.schools.all()
    results = [remove_organization(school) for school in schools]
    kept_any = any(r[0] == 'kept' for r in results)
    if kept_any:
        district.is_active = False
        db.session.commit()
        return 'kept', sum(len(r[1]) for r in results), sum(len(r[2]) for r in results)
    db.session.delete(district)
    db.session.commit()
    return 'deleted', sum(len(r[1]) for r in results), 0


def summary(deleted, kept, noun='store'):
    """A plain sentence for the flash message."""
    plural = lambda n: f'{n} {noun}' + ('' if n == 1 else 's')
    parts = []
    if deleted:
        parts.append(f'Deleted {plural(len(deleted))}.')
    if kept:
        parts.append(f'{plural(len(kept))} {"has" if len(kept) == 1 else "have"} orders or sign-ups, so '
                     f'{"it was" if len(kept) == 1 else "they were"} turned off and kept: {", ".join(kept[:5])}'
                     f'{"" if len(kept) <= 5 else " and more"}.')
    return ' '.join(parts) or 'Nothing was selected.'
