"""The stylesheet link changes when the file changes, so no browser or CDN keeps a stale copy."""
import os
import re


def test_stylesheet_link_carries_the_file_version(client):
    html = client.get('/').get_data(as_text=True)
    match = re.search(r'css/main\.css\?v=(\d+)', html)
    assert match, 'main.css link should end in ?v=<number>'
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'css', 'main.css')
    assert match.group(1) == str(int(os.path.getmtime(path)))
