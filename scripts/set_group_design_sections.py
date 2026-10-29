"""Put a group's artwork under headings, by design name. Run it against the live database, for example:

    railway run python scripts/set_group_design_sections.py de-soto-mill-valley-school-spirit

Mill Valley School Spirit: Jag Mom Sunglasses, Jag Dad Sunglasses and Mini Jag Cub Head go under Family, every design whose
name starts with "Red Friday" goes under Red Friday, everything else under General Spirit. The designs are also put in that
order. Names are matched without regard to capitals; nothing is renamed or removed. Add --dry-run to only print the plan.
"""
import json
import sys

from app import app as _app
from models import Collection, Design, db

FAMILY = ('jag mom sunglasses', 'jag dad sunglasses', 'mini jag cub head')


def heading_for(title):
    t = (title or '').strip().lower()
    if t in FAMILY:
        return 'Family'
    if t.startswith('red friday'):
        return 'Red Friday'
    return 'General Spirit'


def main(slug, dry_run):
    app = _app
    with app.app_context():
        store = Collection.query.filter_by(slug=slug).first()
        if store is None:
            sys.exit(f'No group with the link name "{slug}".')
        ids = json.loads(store.allowed_design_ids or '[]')
        designs = {d.id: d for d in Design.query.filter(Design.id.in_(ids)).all()}
        heads = {i: heading_for(designs[i].title) for i in ids if i in designs and not designs[i].parent_design_id}
        order = ['General Spirit', 'Family', 'Red Friday']
        ranked = sorted(heads, key=lambda i: (order.index(heads[i]), ids.index(i)))
        rest = [i for i in ids if i not in heads]
        for h in order:
            print(h, [designs[i].title for i in ranked if heads[i] == h])
        if dry_run:
            return
        store.design_sections = json.dumps({str(i): h for i, h in heads.items()})
        store.allowed_design_ids = json.dumps(ranked + rest)
        db.session.commit()
        print('Saved.')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        sys.exit('Usage: python scripts/set_group_design_sections.py <group-link-name> [--dry-run]')
    main(args[0], '--dry-run' in sys.argv)
