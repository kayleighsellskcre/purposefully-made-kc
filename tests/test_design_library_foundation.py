"""Stage 1 of the design library: one taxonomy, one tag vocabulary, protected corrections."""
import json

from models import (Design, DesignCategoryLink, DesignCorrection, DesignTag, DesignTagLink, db)
from utils import design_tags as dt
from utils.design_taxonomy import (COLLECTIONS, collection_for_legacy, is_valid_pair, label_for,
                                   legacy_key_for, subcategory_keys)


def _design(app, **over):
    with app.app_context():
        design = Design(filename='x.png', file_path='designs/x.png', title='Test', is_gallery=True, **over)
        db.session.add(design)
        db.session.commit()
        return design.id


# -- Taxonomy -----------------------------------------------------------------

def test_there_are_ten_collections_and_subcategories_follow_the_plan():
    assert [c.label for c in COLLECTIONS] == [
        'Kansas City', 'Faith & Inspiration', 'Sports & Game Day', 'School Spirit', 'Music & Entertainment',
        'Funny & Sarcastic', 'Family & Relationships', 'Lifestyle & Interests', 'Holidays & Seasons', 'Luxury Basics']
    assert subcategory_keys('kansas-city') == ['kc-chiefs', 'kc-royals', 'kc-current', 'sporting-kc',
                                               'other-kc-teams', 'kansas-city-pride']
    assert 'baseball-and-softball' in subcategory_keys('sports-game-day')
    assert 'valentines-day' in subcategory_keys('holidays-seasons')
    assert is_valid_pair('family-relationships', 'moms') and not is_valid_pair('family-relationships', 'football')
    assert label_for('holidays-seasons', 'valentines-day') == "Valentine's Day"


def test_every_folder_the_site_already_uses_maps_to_a_collection():
    for old in ('kc', 'faith', 'sports', 'school', 'music', 'funny', 'couples', 'family', 'holiday', 'seasonal',
                'luxury_basics', 'luxury'):
        assert collection_for_legacy(old), old
    # Fan Favorites is automatic now, so those old folders map to no collection
    assert collection_for_legacy('evergreen') == '' and collection_for_legacy('custom_orders') == ''
    assert legacy_key_for('sports-game-day') == 'sports' and legacy_key_for('lifestyle-interests') == ''


# -- Vocabulary ---------------------------------------------------------------

def test_the_vocabulary_is_seeded_once_and_never_overwrites_your_edits(app, seed):
    with app.app_context():
        DesignTag.query.delete()
        db.session.commit()
        first = dt.ensure_vocabulary()
        assert first > 80
        mom = DesignTag.query.filter_by(slug='mom').one()
        mom.label = 'Mom (edited)'
        db.session.commit()
        assert dt.ensure_vocabulary() == 0
        assert DesignTag.query.filter_by(slug='mom').one().label == 'Mom (edited)'


def test_synonyms_find_the_canonical_tag_and_nothing_is_invented(app, seed):
    with app.app_context():
        dt.ensure_vocabulary()
        for word in ('Mama', 'mommy', 'Mother', 'MOM'):
            assert dt.canonical_for(word).slug == 'mom', word
        assert dt.canonical_for('Kansas City Chiefs').slug == 'kc-chiefs'
        assert dt.canonical_for('KC Chiefs').slug == 'kc-chiefs'
        assert dt.canonical_for('zzzz unknown') is None
        assert dt.canonical_for('Fall').slug == 'fall'          # a tag's own name beats another tag's synonym


def test_implied_tags_and_clean_tags(app, seed):
    with app.app_context():
        dt.ensure_vocabulary()
        assert set(dt.with_implied(['football-mom'])) == {'football-mom', 'football', 'mom'}
        assert dt.clean_tags(['Football Mama', 'mama', 'Vintage', 'retro', 'not a tag']) == [
            'football-mom', 'football', 'mom', 'vintage']        # deduped, known tags only
        both = dt.clean_tags(['Mama and Mini'])
        assert 'mom' in both and 'matching-set' in both


def test_grandma_search_finds_nana_and_mimi_as_related_not_identical(app, seed):
    with app.app_context():
        dt.ensure_vocabulary()
        terms = dt.search_terms('grandma')
        assert {'grandma', 'grandmother', 'granny'} <= terms['exact']
        assert {'nana', 'mimi'} <= terms['related'] and 'nana' not in terms['exact']
        mama = dt.search_terms('Mama')
        assert {'mom', 'mommy', 'mother'} <= mama['exact']
        assert dt.search_terms('')['exact'] == set()


# -- Your edits are protected -------------------------------------------------

def test_automatic_tags_only_add_and_never_touch_what_you_set(app, seed):
    did = _design(app)
    with app.app_context():
        dt.ensure_vocabulary()
        design = db.session.get(Design, did)
        dt.set_manual_tags(design, ['mom', 'vintage'])
        db.session.commit()
        added = dt.apply_auto_tags(design, ['football-mom', 'mom'], confidence=0.9)     # mom already set by hand
        db.session.commit()
        assert set(added) == {'football-mom', 'football'}
        links = {l.tag.slug: l for l in DesignTagLink.query.filter_by(design_id=did)}
        assert links['mom'].source == 'manual' and links['mom'].locked
        assert links['football'].source == 'auto' and links['football'].confidence == 0.9


def test_removing_an_automatic_tag_is_remembered_in_the_correction_history(app, seed):
    did = _design(app)
    with app.app_context():
        dt.ensure_vocabulary()
        design = db.session.get(Design, did)
        dt.apply_auto_tags(design, ['football', 'vintage'])
        db.session.commit()
        dt.set_manual_tags(design, ['vintage'])                                         # you dropped football
        db.session.commit()
        row = DesignCorrection.query.filter_by(design_id=did).one()
        assert (row.field, row.original_value, row.correction_type) == ('tag', 'football', 'tag_removed')
        assert sorted(dt.design_tag_slugs(design)) == ['vintage']


def test_a_locked_field_is_never_overwritten_by_automation(app, seed):
    did = _design(app)
    with app.app_context():
        design = db.session.get(Design, did)
        design.title = 'Vintage Kansas City Football Mama'
        dt.record_correction(design, 'title', 'Football Design', design.title, 'renamed')
        db.session.commit()
        assert dt.is_locked(design, 'title') and not dt.is_locked(design, 'colors')
        assert dt.set_if_unlocked(design, 'title', 'Something The AI Guessed') is False
        assert design.title == 'Vintage Kansas City Football Mama'
        assert dt.set_if_unlocked(design, 'style', 'Vintage') is True and design.style == 'Vintage'
        row = DesignCorrection.query.filter_by(design_id=did).one()
        assert (row.original_value, row.corrected_value, row.correction_type, row.locked) == (
            'Football Design', 'Vintage Kansas City Football Mama', 'renamed', True)


def test_deleting_a_design_cleans_up_its_tags_categories_and_history(app, seed):
    did = _design(app)
    with app.app_context():
        dt.ensure_vocabulary()
        design = db.session.get(Design, did)
        dt.apply_auto_tags(design, ['mom'])
        db.session.add(DesignCategoryLink(design_id=did, category_key='family-relationships', subcategory_key='moms'))
        dt.record_correction(design, 'title', 'a', 'b', 'renamed')
        db.session.commit()
        db.session.delete(design)
        db.session.commit()
        assert DesignTagLink.query.filter_by(design_id=did).count() == 0
        assert DesignCategoryLink.query.filter_by(design_id=did).count() == 0
        assert DesignCorrection.query.filter_by(design_id=did).count() == 0
        assert DesignTag.query.filter_by(slug='mom').count() == 1                # the tag itself stays


def test_existing_designs_are_untouched_by_the_new_columns(app, seed):
    did = _design(app)
    with app.app_context():
        design = db.session.get(Design, did)
        assert design.ai_status is None and design.ip_status is None and design.locked_fields is None
        assert design.tag_links.count() == 0 and design.category_links.count() == 0


# -- The admin page -----------------------------------------------------------

def test_the_tags_page_lists_the_vocabulary_by_type(admin_client):
    html = admin_client.get('/admin/design-library/tags').get_data(as_text=True)
    for text in ('Design tags', 'Recipient', 'Sport', 'Holiday', 'Football Mom', 'mama, mommy, mother'):
        assert text in html, text
    assert 'href="/admin/design-library/tags"' in html                           # in the Store menu


def test_you_can_add_a_tag_but_never_a_duplicate_or_a_synonym(admin_client, app):
    admin_client.get('/admin/design-library/tags')
    admin_client.post('/admin/design-library/tags', data={'action': 'add', 'label': 'Pickleball', 'tag_type': 'sport',
                                                          'synonyms': 'pickle ball, paddle'}, follow_redirects=True)
    admin_client.post('/admin/design-library/tags', data={'action': 'add', 'label': 'Mommy', 'tag_type': 'recipient'},
                      follow_redirects=True)
    admin_client.post('/admin/design-library/tags', data={'action': 'add', 'label': 'Pickleball', 'tag_type': 'sport'},
                      follow_redirects=True)
    with app.app_context():
        assert DesignTag.query.filter_by(slug='pickleball').count() == 1
        assert dt.canonical_for('Pickle Ball').slug == 'pickleball'
        assert DesignTag.query.filter_by(slug='mommy').count() == 0


def test_you_can_edit_synonyms_turn_a_tag_off_and_deleting_a_used_tag_only_turns_it_off(admin_client, app, seed):
    admin_client.get('/admin/design-library/tags')
    did = _design(app)
    with app.app_context():
        tag_id = DesignTag.query.filter_by(slug='mom').one().id
        dt.apply_auto_tags(db.session.get(Design, did), ['mom'])
        db.session.commit()
    admin_client.post('/admin/design-library/tags', data={'action': 'update', 'tag_id': tag_id, 'label': 'Mom',
                                                          'tag_type': 'recipient', 'synonyms': 'mama, mommy, ma',
                                                          'implies': '', 'related': 'Grandma'}, follow_redirects=True)
    with app.app_context():
        assert dt.canonical_for('ma').slug == 'mom'
        assert json.loads(DesignTag.query.get(tag_id).related) == ['grandma']
    admin_client.post('/admin/design-library/tags', data={'action': 'delete', 'tag_id': tag_id}, follow_redirects=True)
    with app.app_context():
        assert DesignTag.query.get(tag_id) is not None and DesignTag.query.get(tag_id).is_active is False


def test_only_the_admin_can_manage_tags(client):
    assert client.get('/admin/design-library/tags').status_code in (302, 401, 403)
    assert client.post('/admin/design-library/tags', data={'action': 'add', 'label': 'X'}).status_code in (302, 400, 401, 403)
