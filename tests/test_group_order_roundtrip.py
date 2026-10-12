"""Open a store's edit page and press Save without changing anything: nothing may change."""
import json
from html.parser import HTMLParser

from models import Collection, db
from tests.test_group_order_audit import _slug_of
from tests.test_org_fan_wear import _build, _store

SNAPSHOT = (
    'name', 'slug', 'is_active', 'description', 'team_store_config', 'allowed_colors',
    'allowed_design_ids', 'showcase_design_ids', 'allowed_placements', 'allow_back_design',
    'back_design_type', 'back_design_name_part', 'back_design_font', 'back_design_text_color',
    'back_design_outline', 'back_design_outline_color', 'lock_back_design_style',
    'payment_mode', 'show_in_directory', 'order_deadline', 'order_opens_at',
    'allow_cash_pickup', 'shipping_enabled', 'pickup_address', 'pickup_instructions',
    'restrict_options', 'allow_custom_upload',
)


class _Form(HTMLParser):
    """Collects what a browser would submit from the edit form."""

    def __init__(self):
        super().__init__()
        self.in_form = False
        self.fields = []
        self._select = None
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form' and 'collection-form' in (a.get('class') or ''):
            self.in_form = True
        if not self.in_form:
            return
        name = a.get('name')
        if tag == 'input' and name and not a.get('disabled'):
            kind = (a.get('type') or 'text').lower()
            if kind in ('file', 'submit', 'button', 'image'):
                return
            if kind in ('checkbox', 'radio'):
                if 'checked' in a:
                    self.fields.append((name, a.get('value', 'on')))
            else:
                self.fields.append((name, a.get('value', '')))
        elif tag == 'select' and name and not a.get('disabled'):
            self._select = {'name': name, 'first': None, 'chosen': None}
        elif tag == 'option' and self._select is not None:
            value = a.get('value', '')
            if self._select['first'] is None:
                self._select['first'] = value
            if 'selected' in a:
                self._select['chosen'] = value
        elif tag == 'textarea' and name and not a.get('disabled'):
            self._textarea = {'name': name, 'text': ''}

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea['text'] += data

    def handle_endtag(self, tag):
        if tag == 'select' and self._select is not None:
            value = self._select['chosen'] if self._select['chosen'] is not None else self._select['first']
            self.fields.append((self._select['name'], value or ''))
            self._select = None
        elif tag == 'textarea' and self._textarea is not None:
            self.fields.append((self._textarea['name'], self._textarea['text'].strip('\n')))
            self._textarea = None
        elif tag == 'form':
            self.in_form = False


def _snapshot(app, coll_id):
    with app.app_context():
        coll = db.session.get(Collection, coll_id)
        snap = {field: getattr(coll, field, None) for field in SNAPSHOT}
        snap['products'] = sorted(p.id for p in coll.products)
        return snap


def _meaning(snap):
    """Reduce a snapshot to what it means, ignoring harmless formatting differences."""
    out = dict(snap)
    for key, value in snap.items():
        if value is None:
            out[key] = ''
    cfg = json.loads(snap['team_store_config'] or '{}') if snap['team_store_config'] else {}
    if cfg and not (cfg.get('uniform') or {}).get('enabled'):
        cfg['uniform'] = {'enabled': False}
    out['team_store_config'] = cfg
    placements = json.loads(snap['allowed_placements']) if snap['allowed_placements'] else \
        ['center_chest', 'left_chest', 'right_chest', 'center_back']
    out['allowed_placements'] = sorted(placements)
    # Untouched defaults are written out as the value the form shows.
    for key in ('back_design_text_color', 'back_design_outline_color', 'back_design_font'):
        if not snap[key]:
            out[key] = None
    return out


def _save_untouched(admin_client, app, coll_id):
    page = admin_client.get(f'/admin/collections/{coll_id}/edit').get_data(as_text=True)
    form = _Form()
    form.feed(page)
    assert form.fields, 'could not read the edit form'
    data = {}
    for key, value in form.fields:
        data.setdefault(key, []).append(value)
    resp = admin_client.post(f'/admin/collections/{coll_id}/edit', data=data, follow_redirects=True)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_saving_a_team_store_without_changes_changes_nothing(admin_client, app, seed):
    _build(admin_client, app, seed)
    for name in ('Basketball: Rainbow Cheetahs', 'Soccer: Rainbow Cheetahs', 'Volleyball: Rainbow Cheetahs'):
        coll_id = _store(app, name)[0]
        before = _snapshot(app, coll_id)
        _save_untouched(admin_client, app, coll_id)
        after = _snapshot(app, coll_id)
        b, a = _meaning(before), _meaning(after)
        a_for_compare = {k: (None if k in ('back_design_text_color', 'back_design_outline_color', 'back_design_font')
                             and not before[k] else v) for k, v in a.items()}
        changed = {k: (b[k], a_for_compare[k]) for k in b if b[k] != a_for_compare[k]}
        assert not changed, f'{name}: {changed}'


def test_saving_a_plain_store_only_upgrades_it_to_the_current_format(admin_client, app, seed):
    """An old-style store keeps its products; saving writes them in the current format."""
    coll_id = seed['collection_id']
    before = _snapshot(app, coll_id)
    _save_untouched(admin_client, app, coll_id)
    after = _snapshot(app, coll_id)
    b, a = _meaning(before), _meaning(after)
    for key in ('back_design_text_color', 'back_design_outline_color', 'back_design_font'):
        if not before[key]:
            a[key] = None
    changed = {k: (b[k], a[k]) for k in b if b[k] != a[k]}
    # the two expected upgrades
    assert changed.pop('team_store_config')[1]['fan_product_ids'] == before['products']
    assert changed.pop('restrict_options') == (False, True)
    assert not changed, changed
