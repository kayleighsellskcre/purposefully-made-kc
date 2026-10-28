"""The Keep both / Not a duplicate / Hide the extra copy buttons on the duplicates page."""
from models import Design, DesignRelation, db


def _pair(app, seed):
    with app.app_context():
        a = Design(filename='x1.png', file_path='uploads/designs/x1.png', title='One', is_gallery=True, uploaded_by_user_id=seed['admin_id'])
        b = Design(filename='x2.png', file_path='uploads/designs/x2.png', title='Two', is_gallery=True, uploaded_by_user_id=seed['admin_id'])
        db.session.add_all([a, b])
        db.session.flush()
        rel = DesignRelation(design_id=a.id, related_design_id=b.id, relation_type='exact_duplicate', status='suggested',
                             score=1.0, reason='identical file', source='auto')
        db.session.add(rel)
        db.session.commit()
        return rel.id


def test_keep_both_clears_the_pair_from_the_list(app, seed, admin_client):
    rel_id = _pair(app, seed)
    page = admin_client.get('/admin/design-library/matches?tab=duplicates').get_data(as_text=True)
    assert f'name="relation_id" value="{rel_id}"' in page
    resp = admin_client.post('/admin/design-library/matches', data={'relation_id': rel_id, 'action': 'connect'}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(DesignRelation, rel_id).status == 'confirmed'
    assert f'name="relation_id" value="{rel_id}"' not in resp.get_data(as_text=True).split('Recent changes')[0]


def _copies(app, seed, n):
    """n identical designs make n*(n-1)/2 open pairs."""
    with app.app_context():
        designs = [Design(filename=f'c{i}.png', file_path=f'uploads/designs/c{i}.png', title=f'Copy {i}', is_gallery=True,
                          uploaded_by_user_id=seed['admin_id']) for i in range(n)]
        db.session.add_all(designs)
        db.session.flush()
        rows = []
        for i in range(n):
            for j in range(i + 1, n):
                rel = DesignRelation(design_id=designs[i].id, related_design_id=designs[j].id, relation_type='exact_duplicate',
                                     status='suggested', score=1.0, reason='identical file', source='auto')
                db.session.add(rel)
                rows.append(rel)
        db.session.commit()
        return [r.id for r in rows], [d.id for d in designs]


def test_four_identical_copies_show_as_one_card_and_keep_both_settles_them_all(app, seed, admin_client):
    rel_ids, design_ids = _copies(app, seed, 4)                        # six pairs
    page = admin_client.get('/admin/design-library/matches?tab=duplicates').get_data(as_text=True)
    assert page.count('class="dm-card"') == 1 and '4 copies' in page
    first = int(page.split('name="relation_id" value="')[1].split('"')[0])
    admin_client.post('/admin/design-library/matches', data={'relation_id': first, 'action': 'connect'})
    with app.app_context():
        assert {db.session.get(DesignRelation, i).status for i in rel_ids} == {'confirmed'}      # one click settles all six
    assert 'class="dm-card"' not in admin_client.get('/admin/design-library/matches?tab=duplicates').get_data(as_text=True).split('Recent changes')[0]


def test_hiding_an_extra_copy_settles_the_other_pairs_that_included_it(app, seed, admin_client):
    rel_ids, design_ids = _copies(app, seed, 3)
    page = admin_client.get('/admin/design-library/matches?tab=duplicates').get_data(as_text=True)
    first = int(page.split('name="relation_id" value="')[1].split('"')[0])
    admin_client.post('/admin/design-library/matches', data={'relation_id': first, 'action': 'hide_copy'})
    with app.app_context():
        hidden = [d for d in (db.session.get(Design, i) for i in design_ids) if not d.is_gallery]
        assert len(hidden) == 1
        left = [r for r in (db.session.get(DesignRelation, i) for i in rel_ids) if r.status == 'suggested']
        assert all(hidden[0].id not in (r.design_id, r.related_design_id) for r in left)
