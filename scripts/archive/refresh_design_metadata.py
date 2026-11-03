"""AI-refresh public gallery names and distinct color-variant labels.

Uses the OpenAI key already configured for the site's AI design feature.
Admin fields remain editable after this one-time cleanup.

    py -3.12 scripts/refresh_design_metadata.py          # preview
    py -3.12 scripts/refresh_design_metadata.py --apply  # save
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ.setdefault("SCHEDULER_ENABLED", "0")


def _bytes_for(path: str) -> bytes:
    if not path:
        return b""
    if path.startswith(("http://", "https://")):
        response = requests.get(path, timeout=20)
        response.raise_for_status()
        return response.content
    local = ROOT / "static" / path.lstrip("/")
    return local.read_bytes() if local.is_file() else b""


def _distinct_label(proposed: str, used: set[str]) -> str:
    base = " ".join((proposed or "Color").split())[:80] or "Color"
    candidate = base
    number = 2
    while candidate.casefold() in used:
        candidate = f"{base} {number}"[:80]
        number += 1
    used.add(candidate.casefold())
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from app import create_app
    from models import db, Design
    from utils.design_metadata import color_label_from_metadata, suggest_design_metadata
    from utils.design_variants import color_options_for, gallery_mains_query
    from routes.admin import _detect_image_color

    app = create_app()
    api_key = (app.config.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not configured; no metadata was changed.")

    changed = 0
    failures = 0
    with app.app_context():
        mains = gallery_mains_query(Design).all()
        for family_number, main in enumerate(mains, 1):
            options = color_options_for(main)
            analyses = {}
            for option in options:
                try:
                    raw = _bytes_for(option.file_path or "")
                    analyses[option.id] = (
                        suggest_design_metadata(raw, api_key)
                        if raw else {}
                    )
                    if not analyses[option.id]:
                        failures += 1
                except Exception as exc:
                    analyses[option.id] = {}
                    failures += 1
                    print(f"  WARN design {option.id}: {exc}")

            main_meta = analyses.get(main.id) or {}
            suggested_title = (main_meta.get("title") or "").strip()
            title = suggested_title or main.title or main.original_filename or "Design"
            title = " ".join(title.replace("_", " ").split())[:200]
            print(f"\n[{family_number}/{len(mains)}] {main.title!r} -> {title!r}")

            used = set()
            for option in options:
                meta = analyses.get(option.id) or {}
                label = color_label_from_metadata(meta)
                if not label:
                    try:
                        label = _detect_image_color(_bytes_for(option.file_path or ""))
                    except Exception:
                        label = ""
                label = _distinct_label(label or option.variant_label or "Color", used)
                print(f"  {option.id}: {option.variant_label!r} -> {label!r}")

                if option.title != title or option.variant_label != label:
                    changed += 1
                if args.apply:
                    option.title = title
                    option.variant_label = label

        if args.apply:
            db.session.commit()

    mode = "Saved" if args.apply else "Would update"
    print(f"\n{mode} {changed} design rows; AI fallbacks used: {failures}.")


if __name__ == "__main__":
    main()
