"""Round 2 audit item 12, phase one: a strict CSP shipped in report-only
mode so real page loads reveal what would break, before anything is
enforced. The enforcing header is untouched on purpose - a full removal
of unsafe-inline/unsafe-eval touches too much (44 inline <script> blocks,
164 inline event handlers, 670 style="..." attributes) to migrate safely
in one pass on a site that processes real payments.
"""


def test_enforcing_csp_is_unchanged(guest):
    resp = guest.get('/')
    csp = resp.headers.get('Content-Security-Policy', '')
    assert "'unsafe-inline'" in csp
    assert "'unsafe-eval'" in csp


def test_report_only_csp_is_strict(guest):
    resp = guest.get('/')
    report_only = resp.headers.get('Content-Security-Policy-Report-Only', '')
    assert report_only, 'Content-Security-Policy-Report-Only header is missing'
    assert "'unsafe-inline'" not in report_only
    assert "'unsafe-eval'" not in report_only
    assert 'report-uri /csp-report' in report_only


def test_report_only_csp_still_allows_stripe_and_paypal(guest):
    resp = guest.get('/')
    report_only = resp.headers.get('Content-Security-Policy-Report-Only', '')
    assert 'js.stripe.com' in report_only
    assert 'www.paypal.com' in report_only


def test_csp_report_endpoint_accepts_a_violation_report(guest):
    resp = guest.post(
        '/csp-report',
        data='{"csp-report": {"violated-directive": "script-src", "blocked-uri": "inline"}}',
        content_type='application/csp-report',
    )
    assert resp.status_code == 204


def test_csp_report_endpoint_does_not_require_a_csrf_token(guest):
    # Browsers send this with no form and no CSRF token - it must never 400.
    resp = guest.post('/csp-report', data='not json at all', content_type='text/plain')
    assert resp.status_code == 204


def test_both_csp_headers_present_on_every_page(guest):
    for path in ('/', '/shop/', '/contact', '/privacy'):
        resp = guest.get(path)
        assert resp.headers.get('Content-Security-Policy'), path
        assert resp.headers.get('Content-Security-Policy-Report-Only'), path
