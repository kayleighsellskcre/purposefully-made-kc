"""No template may open a <form> while another is still open.

The HTML parser silently discards a <form> that appears inside another form and
keeps its children, so every control in the inner form ends up belonging to the
outer one. That fails in two different ways depending on the button, and neither
one logs anything:

  * A `type="button"` whose script submits the inner form by id does nothing at
    all, because `getElementById` returns null and the call throws. This is how
    the admin product page's "Delete Product" button behaved — first tap changed
    the label to "tap again", second tap did nothing, forever.

  * A `type="submit"` becomes a submit button for the *outer* form, so clicking
    it performs the outer action instead. That is how the group order editor's
    small red x on a design saved the entire group order rather than removing
    the design, and skipped its own confirm() prompt on the way.

The fix in both cases is to move the inner form after the outer form's closing
tag and point the button at it with the `form` attribute.

Known limit: this reads each template on its own, so it cannot see nesting that
only appears once an {% include %} is placed inside a form by its parent.
"""

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'

# Comments may legitimately contain the text "<form" — including the comments
# that explain this very rule — so they come out before counting.
JINJA_COMMENT = re.compile(r'\{#.*?#\}', re.DOTALL)
HTML_COMMENT = re.compile(r'<!--.*?-->', re.DOTALL)
FORM_TAG = re.compile(r'<\s*(/?)form\b', re.IGNORECASE)


def template_files():
    return sorted(TEMPLATES.rglob('*.html'))


def first_nested_form(text):
    """Line number of the first <form> opened while another was open, or None."""
    depth = 0
    for match in FORM_TAG.finditer(text):
        if match.group(1) == '/':
            depth = max(0, depth - 1)
            continue
        depth += 1
        if depth > 1:
            return text.count('\n', 0, match.start()) + 1
    return None


@pytest.mark.parametrize('path', template_files(), ids=lambda p: p.name)
def test_template_has_no_nested_form(path):
    raw = path.read_text(encoding='utf-8', errors='ignore')
    text = HTML_COMMENT.sub('', JINJA_COMMENT.sub('', raw))

    line = first_nested_form(text)
    assert line is None, (
        f'{path.relative_to(TEMPLATES.parent)} opens a <form> on line {line} '
        f'while another is still open. The browser will discard it and hand its '
        f'buttons to the outer form.'
    )


def test_the_detector_actually_catches_nesting():
    """Guards the guard: the shape both real bugs had must be reported."""
    bad = '<form id="outer"><div><form id="inner"><button/></form></div></form>'
    assert first_nested_form(bad) == 1

    good = '<form id="outer"><button form="inner"/></form><form id="inner"></form>'
    assert first_nested_form(good) is None


def test_comments_do_not_count_as_markup():
    """The explanatory comments left at both fix sites mention <form> in prose."""
    commented = (
        '<form id="outer">'
        '{# a <form> here would be discarded by the parser #}'
        '<!-- <form> again, in HTML this time -->'
        '</form>'
    )
    text = HTML_COMMENT.sub('', JINJA_COMMENT.sub('', commented))
    assert first_nested_form(text) is None
