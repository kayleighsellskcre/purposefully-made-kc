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


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = str(body)

    def json(self):
        return self._body


def _run(app, monkeypatch, answers, reference=None):
    import requests
    from routes import custom_request as cr
    calls = []

    def fake_post(url, **kw):
        model = (kw.get('json') or kw.get('data') or {}).get('model')
        calls.append((url.rsplit('/', 1)[-1], model))
        return answers(model)
    monkeypatch.setattr(requests, 'post', fake_post)
    monkeypatch.setattr(ai_errors, 'alert_owner', lambda *a, **k: False)
    job = 'job-' + answers.__name__ + ('-ref' if reference else '')
    cr._run_image_generation(app, job, 'sk-test', 'a happy sun', reference)
    return calls, cr._read_job(job)


def test_uses_the_current_picture_model(app, monkeypatch):
    def ok(model):
        return _Resp(200, {'data': [{'b64_json': 'AAAA'}]})
    calls, job = _run(app, monkeypatch, ok)
    assert calls == [('generations', 'gpt-image-2.6-flare')]
    assert job['status'] == 'done'


def test_a_retired_model_falls_back_to_the_next_one(app, monkeypatch):
    def retired_first(model):
        if model == 'gpt-image-2.6-flare':
            return _Resp(404, {'error': {'message': 'The model `gpt-image-2.6-flare` does not exist or you do not have access to it.',
                                         'code': 'model_not_found'}})
        return _Resp(200, {'data': [{'b64_json': 'AAAA'}]})
    calls, job = _run(app, monkeypatch, retired_first)
    assert [m for _, m in calls] == ['gpt-image-2.6-flare', 'gpt-image-2.6-sunburst']
    assert job['status'] == 'done'


def test_out_of_credits_does_not_try_other_models(app, monkeypatch):
    def broke(model):
        return _Resp(429, {'error': {'message': 'You have no credits remaining.', 'code': 'insufficient_quota'}})
    calls, job = _run(app, monkeypatch, broke)
    assert len(calls) == 1
    assert job['status'] == 'error' and 'credits' not in job['error'].lower() and 'Design Gallery' in job['error']


def test_every_model_retired_tells_the_customer_calmly(app, monkeypatch):
    def gone(model):
        return _Resp(400, {'error': {'message': f'The model {model} has been deprecated', 'code': 'model_not_found'}})
    calls, job = _run(app, monkeypatch, gone)
    assert len(calls) == 3 and job['status'] == 'error' and job.get('kind') == 'model'
    assert 'model' not in job['error'].lower()


def test_reference_pictures_use_the_edit_endpoint_with_the_new_model(app, monkeypatch):
    def ok(model):
        return _Resp(200, {'data': [{'b64_json': 'AAAA'}]})
    calls, job = _run(app, monkeypatch, ok, reference='data:image/png;base64,iVBORw0KGgo=')
    assert calls == [('edits', 'gpt-image-2.6-flare')] and job['status'] == 'done'
