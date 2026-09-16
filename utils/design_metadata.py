"""Automatic, editable gallery-design names and color labels."""
from __future__ import annotations

import base64
import io
import json
import re


_GENERIC_TITLE = re.compile(
    r"^(?:img|image|photo|design|gallery|screenshot|scan)[ _-]*\d*$|"
    r"^[0-9a-f]{8}(?:[ _-][0-9a-f]{4}){3}[ _-][0-9a-f]{12}$",
    re.IGNORECASE,
)


def clean_filename_title(filename: str) -> str:
    """Turn a useful filename into a display title; reject camera/UUID names."""
    stem = re.sub(r"\.[^.]+$", "", filename or "")
    stem = re.sub(r"[_-]+", " ", stem).strip()
    stem = re.sub(r"\s+", " ", stem)
    if not stem or _GENERIC_TITLE.fullmatch(stem):
        return ""
    return " ".join(word.capitalize() if word.islower() else word for word in stem.split())[:200]


def is_generic_title(title: str) -> bool:
    value = re.sub(r"\s+", " ", (title or "").strip())
    return not value or bool(_GENERIC_TITLE.fullmatch(value))


def unique_variant_label(parent, proposed: str, *, exclude_id=None) -> str:
    """Return a label not already used by this design family."""
    base = re.sub(r"\s+", " ", (proposed or "").strip())[:80] or "Color"
    if parent is None:
        return base

    used = set()
    family = [parent] + list(parent.color_variants.all())
    for option in family:
        if exclude_id is not None and getattr(option, "id", None) == exclude_id:
            continue
        label = (getattr(option, "variant_label", None) or "").strip()
        if label:
            used.add(label.casefold())

    if base.casefold() not in used:
        return base
    number = 2
    while f"{base} {number}".casefold() in used:
        number += 1
    return f"{base} {number}"[:80]


def _vision_data_url(file_bytes: bytes) -> str:
    """Create a small PNG suitable for inexpensive vision metadata analysis."""
    from PIL import Image

    image = Image.open(io.BytesIO(file_bytes)).convert("RGBA")
    image.thumbnail((768, 768), Image.Resampling.LANCZOS)
    # A light checkerboard lets white artwork remain visible while preserving
    # enough contrast for the vision model to ignore the background.
    bg = Image.new("RGBA", image.size, (238, 235, 229, 255))
    pixels = bg.load()
    for y in range(image.height):
        for x in range(image.width):
            if ((x // 32) + (y // 32)) % 2:
                pixels[x, y] = (215, 220, 224, 255)
    bg.alpha_composite(image)
    out = io.BytesIO()
    bg.convert("RGB").save(out, format="JPEG", quality=88, optimize=True)
    encoded = base64.b64encode(out.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def suggest_design_metadata(file_bytes: bytes, api_key: str, timeout=18) -> dict:
    """Use the configured OpenAI vision key to suggest title + ink colors.

    Failure is intentionally silent to callers; deterministic filename/pixel
    fallbacks remain available and admin fields are always editable.
    """
    if not file_bytes or not (api_key or "").strip():
        return {}
    try:
        import requests

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "temperature": 0,
                "max_tokens": 120,
                "response_format": {"type": "json_object"},
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this apparel print artwork. Return JSON only with "
                                '{"title":"...","colors":["..."]}. Title must be a concise '
                                "2-8 word customer-facing name based on exact visible wording "
                                "plus a short depicted icon/layout descriptor when useful "
                                "(for example, Best Dad By Par Golfer or Kansas City Skyline). "
                                "Colors must list "
                                "the prominent INK colors only, most prominent first. Ignore "
                                "the light gray checkerboard background. Use familiar names "
                                "such as Black, Cream, Forest Green, Rust, or Gold."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": _vision_data_url(file_bytes), "detail": "low"}},
                    ],
                }],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        data = json.loads(raw)
        title = re.sub(r"\s+", " ", str(data.get("title") or "")).strip()[:200]
        colors = [
            re.sub(r"\s+", " ", str(color)).strip().title()
            for color in (data.get("colors") or [])
            if str(color).strip()
        ][:3]
        return {"title": title, "colors": colors}
    except Exception:
        return {}


def color_label_from_metadata(metadata: dict) -> str:
    colors = list((metadata or {}).get("colors") or [])
    if not colors:
        return ""
    # Two colors distinguish multicolor versions better than one averaged color.
    return " & ".join(colors[:2])[:80]
