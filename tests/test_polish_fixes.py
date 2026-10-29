"""Polish: quieter security reports, names on fields, no empty picture addresses, room to tap."""
import logging
import re


def test_the_same_policy_report_is_logged_once_an_hour(app, guest, caplog):
    from utils import csp_log
    csp_log.reset()
    report = {'csp-report': {'document-uri': 'https://x.test/shop/', 'violated-directive': 'style-src-attr', 'blocked-uri': 'inline'}}
    with caplog.at_level(logging.WARNING):
        for _ in range(40):
            assert guest.post('/csp-report', json=report).status_code == 204
        other = {'csp-report': {'document-uri': 'https://x.test/shop/', 'violated-directive': 'script-src-elem', 'blocked-uri': 'inline'}}
        guest.post('/csp-report', json=other)
    lines = [r for r in caplog.records if 'CSP report-only' in r.getMessage()]
    assert len(lines) == 2                                      # one for each kind, not 41
    from utils.csp_log import should_log
    assert should_log(report['csp-report'], now=10 ** 10) == (True, 39)         # the next hour says how many were skipped


def test_the_upload_and_ai_fields_have_names_for_screen_readers(app, guest, seed):
    html = guest.get(f'/shop/customize/{seed["tee_slug"]}').get_data(as_text=True)
    for field in ('designFileMain', 'designSearchInput', 'designFileBack'):
        assert re.search(r'<input[^>]*id="%s"[^>]*aria-label=|<input[^>]*aria-label=[^>]*id="%s"' % (field, field), html), field
    app.config['OPENAI_API_KEY'] = 'sk-test-not-real'                 # the studio only draws its fields when it is switched on
    ai = guest.get('/custom-design/ai-design').get_data(as_text=True)
    for field in ('aiReferenceInput', 'aiPromptInput', 'aiTweakInput'):
        assert re.search(r'<(input|textarea)[^>]*id="%s"[^>]*aria-label=|<(input|textarea)[^>]*aria-label=[^>]*id="%s"' % (field, field), ai), field


def test_no_picture_tag_has_an_empty_address(app, guest, seed):
    app.config['OPENAI_API_KEY'] = 'sk-test-not-real'
    for path in (f'/shop/customize/{seed["tee_slug"]}', '/custom-design/ai-design', '/custom-design/submit'):
        html = guest.get(path, follow_redirects=True).get_data(as_text=True)
        assert not re.search(r'<img\b[^>]*\bsrc=""', html), path
