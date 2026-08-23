"""The cached per-style mockup index.

/shop/ took 2.7 seconds while every other page answered in under 30ms. Resolving
one colour's mockup cost up to 12 stat() calls plus up to 12 directory globs, and
the page renders every colour of every product — roughly 1350 colour/view pairs
on the live catalogue. Each style folder is now listed once and cached.

These tests exist because that rewrite touches how every product image on the
site is resolved: getting the precedence or the cache invalidation wrong shows up
as missing product photos, not as an exception.
"""
import os

import pytest

from utils import mockups


@pytest.fixture()
def mockup_app(app, tmp_path):
    """The real app, pointed at an empty uploads tree we control.

    UPLOAD_FOLDER is what _mockup_dirs() builds `<folder>/mockups` from, so
    redirecting it keeps these tests off the repository's real mockup files.
    """
    uploads = tmp_path / 'uploads'
    (uploads / 'mockups').mkdir(parents=True)

    original = app.config.get('UPLOAD_FOLDER')
    app.config['UPLOAD_FOLDER'] = str(uploads)
    mockups.clear_mockup_cache()
    try:
        yield app
    finally:
        app.config['UPLOAD_FOLDER'] = original
        mockups.clear_mockup_cache()


def style_dir(mockup_app, style):
    path = os.path.join(mockup_app.config['UPLOAD_FOLDER'], 'mockups', str(style))
    os.makedirs(path, exist_ok=True)
    return path


def write(directory, name):
    with open(os.path.join(directory, name), 'wb') as handle:
        handle.write(b'not-really-an-image')


def find(mockup_app, style, colour, view):
    return mockups._find_mockup_file(mockup_app, style, colour, view)


# ── Format A: 3001_Aqua_front.jpg ────────────────────────────────────────────

def test_finds_an_exact_name(mockup_app):
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Aqua_front.jpg')
    assert find(mockup_app, '3001', 'Aqua', 'front') == '3001/3001_Aqua_front.jpg'


def test_spaces_in_the_colour_become_underscores(mockup_app):
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Sport_Grey_front.jpg')
    assert find(mockup_app, '3001', 'Sport Grey', 'front') == '3001/3001_Sport_Grey_front.jpg'


def test_front_and_back_are_separate(mockup_app):
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Aqua_front.jpg')
    write(directory, '3001_Aqua_back.jpg')
    assert find(mockup_app, '3001', 'Aqua', 'front') == '3001/3001_Aqua_front.jpg'
    assert find(mockup_app, '3001', 'Aqua', 'back') == '3001/3001_Aqua_back.jpg'


def test_missing_colour_returns_none(mockup_app):
    style_dir(mockup_app, '3001')
    assert find(mockup_app, '3001', 'Aqua', 'front') is None


def test_blank_colour_returns_none(mockup_app):
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Aqua_front.jpg')
    assert find(mockup_app, '3001', '', 'front') is None
    assert find(mockup_app, '3001', None, 'front') is None


def test_unknown_style_returns_none(mockup_app):
    assert find(mockup_app, '9999', 'Aqua', 'front') is None


@pytest.mark.parametrize('extension', ['.jpg', '.jpeg', '.png', '.webp'])
def test_every_supported_extension_is_found(mockup_app, extension):
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Aqua_front' + extension)
    assert find(mockup_app, '3001', 'Aqua', 'front') == f'3001/3001_Aqua_front{extension}'


def test_jpg_wins_over_png(mockup_app):
    """Extension order decides, matching the original lookup."""
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Aqua_front.png')
    write(directory, '3001_Aqua_front.jpg')
    assert find(mockup_app, '3001', 'Aqua', 'front') == '3001/3001_Aqua_front.jpg'


def test_unsupported_extension_is_ignored(mockup_app):
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Aqua_front.gif')
    assert find(mockup_app, '3001', 'Aqua', 'front') is None


# ── Format B: BELLA_+_CANVAS_3001Y_Ash_Front_High.jpg ────────────────────────

def test_finds_a_descriptive_name(mockup_app):
    directory = style_dir(mockup_app, '3001Y')
    write(directory, 'BELLA_+_CANVAS_3001Y_Ash_Front_High.jpg')
    assert find(mockup_app, '3001Y', 'Ash', 'front') == (
        '3001Y/BELLA_+_CANVAS_3001Y_Ash_Front_High.jpg'
    )


def test_descriptive_name_matches_colour_case_insensitively(mockup_app):
    directory = style_dir(mockup_app, '3001Y')
    write(directory, 'BELLA_+_CANVAS_3001Y_Ash_Front_High.jpg')
    assert find(mockup_app, '3001Y', 'ASH', 'front') is not None
    assert find(mockup_app, '3001Y', 'ash', 'front') is not None


def test_exact_name_wins_over_descriptive_name(mockup_app):
    """Format A is tried in full before Format B, as it always was."""
    directory = style_dir(mockup_app, '3001')
    write(directory, 'BELLA_+_CANVAS_3001_Ash_Front_High.jpg')
    write(directory, '3001_Ash_front.png')
    assert find(mockup_app, '3001', 'Ash', 'front') == '3001/3001_Ash_front.png'


def test_descriptive_name_for_the_wrong_colour_is_not_returned(mockup_app):
    directory = style_dir(mockup_app, '3001Y')
    write(directory, 'BELLA_+_CANVAS_3001Y_Ash_Front_High.jpg')
    assert find(mockup_app, '3001Y', 'Navy', 'front') is None


# ── Caching and invalidation ─────────────────────────────────────────────────

def _expire_and_touch(monkeypatch, directory):
    """Force the next lookup to re-check the folder, and make sure it notices.

    Two things are in the way of testing invalidation. The index is trusted for
    a second before the folder is stat()ed again, so the time-to-live is set to
    zero rather than sleeping. And the fingerprint is the folder's mtime, whose
    resolution can be coarser than the time these operations take, so the mtime
    is moved explicitly instead of relying on the write to change it.
    """
    monkeypatch.setattr(mockups, '_INDEX_TTL_SECONDS', 0)
    stat = os.stat(directory)
    os.utime(directory, (stat.st_atime + 10, stat.st_mtime + 10))


def test_a_new_upload_is_picked_up(mockup_app, monkeypatch):
    """An admin uploading a mockup must not have to wait for a restart."""
    directory = style_dir(mockup_app, '3001')
    assert find(mockup_app, '3001', 'Aqua', 'front') is None

    write(directory, '3001_Aqua_front.jpg')
    _expire_and_touch(monkeypatch, directory)

    assert find(mockup_app, '3001', 'Aqua', 'front') == '3001/3001_Aqua_front.jpg'


def test_a_deleted_mockup_stops_being_returned(mockup_app, monkeypatch):
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Aqua_front.jpg')
    assert find(mockup_app, '3001', 'Aqua', 'front') is not None

    os.remove(os.path.join(directory, '3001_Aqua_front.jpg'))
    _expire_and_touch(monkeypatch, directory)

    assert find(mockup_app, '3001', 'Aqua', 'front') is None


def test_clearing_the_cache_forces_a_rescan(mockup_app):
    directory = style_dir(mockup_app, '3001')
    assert find(mockup_app, '3001', 'Aqua', 'front') is None
    write(directory, '3001_Aqua_front.jpg')
    mockups.clear_mockup_cache()
    assert find(mockup_app, '3001', 'Aqua', 'front') == '3001/3001_Aqua_front.jpg'


def test_repeated_lookups_do_not_relist_the_folder(mockup_app, monkeypatch):
    """The whole point of the change. One listdir should serve every colour."""
    directory = style_dir(mockup_app, '3001')
    for colour in ('Aqua', 'Navy', 'Black', 'White'):
        write(directory, f'3001_{colour}_front.jpg')
        write(directory, f'3001_{colour}_back.jpg')

    mockups.clear_mockup_cache()

    # Counting index builds rather than patching os.listdir, which mockups
    # reaches through the real os module and so would be patched process-wide.
    builds = []
    real_build = mockups._build_style_index

    def counting_build(app, style_number, now):
        builds.append(style_number)
        return real_build(app, style_number, now)

    monkeypatch.setattr(mockups, '_build_style_index', counting_build)

    for colour in ('Aqua', 'Navy', 'Black', 'White'):
        for view in ('front', 'back'):
            assert find(mockup_app, '3001', colour, view) is not None

    assert len(builds) == 1, f'scanned the folder {len(builds)} times, expected once'


def test_two_apps_do_not_share_an_index(app, tmp_path):
    """The cache key includes the search roots.

    app.py builds an app at module scope and the test suite builds another, so
    two apps with different UPLOAD_FOLDERs can share this process. Keying on the
    style alone let the time-to-live shortcut serve one app the other's index,
    because that path skips the fingerprint check on purpose.
    """
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    (first / 'mockups' / '3001').mkdir(parents=True)
    (second / 'mockups' / '3001').mkdir(parents=True)
    write(str(first / 'mockups' / '3001'), '3001_Aqua_front.jpg')

    mockups.clear_mockup_cache()
    original = app.config.get('UPLOAD_FOLDER')
    try:
        app.config['UPLOAD_FOLDER'] = str(first)
        assert mockups._find_mockup_file(app, '3001', 'Aqua', 'front') is not None

        # Immediately, well inside the TTL window.
        app.config['UPLOAD_FOLDER'] = str(second)
        assert mockups._find_mockup_file(app, '3001', 'Aqua', 'front') is None
    finally:
        app.config['UPLOAD_FOLDER'] = original
        mockups.clear_mockup_cache()


# ── Colour discovery reads the same cached listing ───────────────────────────

def test_discovery_finds_both_views_of_a_colour(mockup_app):
    directory = style_dir(mockup_app, '3001')
    write(directory, '3001_Aqua_front.jpg')
    write(directory, '3001_Aqua_back.jpg')

    found = mockups.discover_colors_from_mockup_folder(mockup_app, '3001')
    by_name = {entry['color_name']: entry for entry in found}

    assert 'Aqua' in by_name
    assert by_name['Aqua']['front_image'].endswith('3001_Aqua_front.jpg')
    assert by_name['Aqua']['back_image'].endswith('3001_Aqua_back.jpg')


def test_discovery_lists_every_colour_once(mockup_app):
    directory = style_dir(mockup_app, '3001')
    for colour in ('Aqua', 'Navy'):
        write(directory, f'3001_{colour}_front.jpg')
        write(directory, f'3001_{colour}_back.jpg')

    found = mockups.discover_colors_from_mockup_folder(mockup_app, '3001')
    names = [entry['color_name'] for entry in found]
    assert sorted(names) == ['Aqua', 'Navy']
    assert len(names) == len(set(names))


def test_discovery_on_an_empty_folder_returns_nothing(mockup_app):
    style_dir(mockup_app, '3001')
    assert mockups.discover_colors_from_mockup_folder(mockup_app, '3001') == []
