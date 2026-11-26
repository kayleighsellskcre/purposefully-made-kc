"""Record stock that leaves without a sale, and say plainly how it touches the Kansas sales tax return.

Four kinds: donated, given away, used by the owner, thrown out (for example a misprint). Each one keeps what it
actually cost. Whether the cost is reported as "merchandise consumed" on the return depends on whether sales tax was
paid when the item was bought:

* tax already paid on the purchase                 -> not reportable (Kansas already has the tax)
* no tax paid, used by you or given away           -> reportable at cost
* no tax paid, donated or thrown out               -> needs a decision (shown in Needs review)

The owner can change the treatment on any row, so the final call is hers and her CPA's. Money already spent on the
blanks is in the books from when they were bought, so nothing is added to the ledger here.
"""
from __future__ import annotations

from datetime import date

from models import ApparelInventory, InventoryAdjustment, db

KINDS = [('donated', 'Donated'), ('given_away', 'Given away'), ('used_by_me', 'Used by me'), ('discarded', 'Thrown out')]
TREATMENTS = [('reportable', 'Report as merchandise consumed'), ('not_reportable', 'Do not report'), ('review', 'Needs a decision')]


def default_treatment(kind: str, paid_tax: bool) -> str:
    if paid_tax:
        return 'not_reportable'
    if kind in ('used_by_me', 'given_away'):
        return 'reportable'
    return 'review'


def _cents(text):
    cleaned = (text or '').replace('$', '').replace(',', '').strip()
    if not cleaned:
        return None
    return int(round(float(cleaned) * 100))


def _day(text):
    text = (text or '').strip()
    if not text:
        return None
    y, m, d = (int(x) for x in text.split('-'))
    return date(y, m, d)


def record(form, today: date):
    """Save one adjustment from a form. Returns (row, message). Raises ValueError with a plain message."""
    kind = form.get('kind')
    if kind not in dict(KINDS):
        raise ValueError('Pick what happened: donated, given away, used by me or thrown out.')
    inv = None
    inv_id = form.get('inventory_id')
    if inv_id and str(inv_id).isdigit():
        inv = db.session.get(ApparelInventory, int(inv_id))
    item = (form.get('item') or '').strip()
    if not item and inv is not None:
        item = f'{inv.brand} {inv.color} {inv.size}'
    if not item:
        raise ValueError('Say which item it was.')
    try:
        qty = int(form.get('quantity') or 0)
    except ValueError:
        qty = 0
    if qty < 1 or qty > 100000:
        raise ValueError('Enter how many, as a whole number.')
    try:
        cost = _cents(form.get('unit_cost'))
        retail = _cents(form.get('retail_value'))
        when = _day(form.get('occurred_on')) or today
        handed = _day(form.get('handed_over_on'))
    except (ValueError, TypeError):
        raise ValueError('A date or amount was not readable. Dates look like 2026-12-15 and amounts like 4.25.')
    if cost is None:
        cost = int(round(float(inv.cost_per_unit) * 100)) if inv is not None and inv.cost_per_unit else None
    if cost is None or cost < 0:
        raise ValueError('Enter what one of them actually cost.')
    paid = form.get('paid_tax_on_purchase') == '1'
    row = InventoryAdjustment(
        kind=kind, item=item[:200], inventory_id=inv.id if inv is not None else None, quantity=qty, unit_cost_cents=cost,
        occurred_on=when, paid_tax_on_purchase=paid, treatment=default_treatment(kind, paid),
        recipient=(form.get('recipient') or '').strip()[:160] or None, event=(form.get('event') or '').strip()[:160] or None,
        handed_over_on=handed, exemption_certificate=(form.get('exemption_certificate') or '').strip()[:120] or None,
        retail_value_cents=retail, is_misprint=form.get('is_misprint') == '1' or kind == 'discarded' and 'misprint' in item.lower(),
        notes=(form.get('notes') or '').strip() or None)
    db.session.add(row)
    msg = f'Recorded {qty} x {item}.'
    if inv is not None:
        inv.quantity = max(0, int(inv.quantity or 0) - qty)
        msg += f' Stock now shows {inv.quantity}.'
    db.session.commit()
    return row, msg


def for_period(first: date, last: date):
    return (InventoryAdjustment.query.filter(InventoryAdjustment.occurred_on >= first, InventoryAdjustment.occurred_on <= last)
            .order_by(InventoryAdjustment.occurred_on.desc(), InventoryAdjustment.id.desc()).all())


def consumed_cents(rows) -> int:
    """Cost of everything in these rows that is reported as merchandise consumed."""
    return sum(r.total_cost_cents for r in rows if r.treatment == 'reportable')
