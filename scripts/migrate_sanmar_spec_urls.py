#!/usr/bin/env python3
"""Replace legacy sanmar.com/p/ spec URLs with CDN PDF URLs in script files.

Pattern:
    https://www.sanmar.com/p/STYLE  or  https://sanmar.com/p/STYLE
→   https://cdnm.sanmar.com/SpecSheetMeasurements/STYLE.pdf

Style codes are preserved (uppercased for CDN path consistency).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / 'scripts'

_LEGACY_SPEC_URL = re.compile(
    r'https?://(?:www\.)?sanmar\.com/p/([^/?#"\'\s]+)',
    re.IGNORECASE,
)

# Explicit targets first; scan all scripts/ for any others with /p/ links.
DEFAULT_TARGETS = [
    SCRIPTS_DIR / 'update_product_data.py',
    SCRIPTS_DIR / 'add_sanmar_tiedye.py',
    SCRIPTS_DIR / 'add_sanmar_gildan.py',
    SCRIPTS_DIR / 'ensure_youth_crew_and_pc147yls.py',
    SCRIPTS_DIR / 'ensure_pc146_tiedye_hoodies.py',
]


def cdn_spec_url(style: str) -> str:
    style = style.rstrip('/').upper()
    return f'https://cdnm.sanmar.com/SpecSheetMeasurements/{style}.pdf'


def migrate_text(text: str) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []

    def repl(match: re.Match[str]) -> str:
        old = match.group(0)
        new = cdn_spec_url(match.group(1))
        if old != new:
            changes.append((old, new))
        return new

    return _LEGACY_SPEC_URL.sub(repl, text), changes


def migrate_file(path: Path, dry_run: bool = False) -> list[tuple[str, str]]:
    original = path.read_text(encoding='utf-8')
    updated, changes = migrate_text(original)
    if changes and not dry_run:
        path.write_text(updated, encoding='utf-8')
    return changes


def discover_targets() -> list[Path]:
    seen: set[Path] = set()
    targets: list[Path] = []
    for path in DEFAULT_TARGETS:
        resolved = path.resolve()
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            targets.append(path)
    for path in sorted(SCRIPTS_DIR.glob('*.py')):
        if path.name == Path(__file__).name:
            continue
        if path.resolve() in seen:
            continue
        if _LEGACY_SPEC_URL.search(path.read_text(encoding='utf-8')):
            seen.add(path.resolve())
            targets.append(path)
    return targets


def main(argv: list[str] | None = None) -> int:
    dry_run = '--dry-run' in (argv or sys.argv[1:])
    targets = discover_targets()
    if not targets:
        print('No script files with sanmar.com/p/ URLs found.')
        return 0

    total = 0
    for path in targets:
        changes = migrate_file(path, dry_run=dry_run)
        if not changes:
            continue
        total += len(changes)
        rel = path.relative_to(ROOT)
        print(f'{rel}: {len(changes)} URL(s) updated')
        for old, new in changes[:3]:
            print(f'  {old} -> {new}')
        if len(changes) > 3:
            print(f'  ... and {len(changes) - 3} more')

    action = 'would update' if dry_run else 'updated'
    print(f'\n{action} {total} URL(s) across {len(targets)} file(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
