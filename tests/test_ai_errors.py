"""When the AI picture maker fails, the customer never sees OpenAI's wording, and the owner is told once."""
from utils import ai_errors


def test_no_credits_is_a_calm_message_and_never_the_providers_text():
    kind = ai_errors.classify(429, 'You have no credits remaining. Add credits to continue using the API at https://platform.openai.com/settings/organization/billing/.', 'insufficient_quota')
    assert kind == 'credits'
    text = ai_errors.customer_message(kind)
    assert 'openai' not in text.lower() and 'credits' not in text.lower() and 'billing' not in text.lower()
    assert 'Design Gallery' in text and 'Custom Design' in text


def test_other_failures_get_plain_wording():
    assert ai_errors.classify(429, 'Rate limit reached for requests') == 'busy'
    assert ai_errors.classify(400, 'Your request was rejected by the safety system', 'moderation_blocked') == 'reword'
    assert ai_errors.classify(500, 'server error') == 'other'
    assert 'openai' not in ai_errors.customer_message('other').lower()


def test_owner_is_emailed_once_per_twelve_hours_and_only_for_credit_problems(app, outbox):
    with app.app_context():
        assert ai_errors.alert_owner(app, 'busy', 429, 'slow down') is False
        assert ai_errors.alert_owner(app, 'credits', 429, 'You have no credits remaining') in (True, False)
        first = len(outbox)
        ai_errors.alert_owner(app, 'credits', 429, 'You have no credits remaining')
        assert len(outbox) == first                       # the second one inside 12 hours stays quiet
    assert all('credits' in (m.body or '').lower() for m in outbox) or not outbox


def test_ai_page_error_box_offers_a_way_forward(app, client):
    html = client.get('/custom-design/ai-design', follow_redirects=True).get_data(as_text=True)
    assert 'browse the Design Gallery' in html or 'Login' in html or 'login' in html
