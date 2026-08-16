"""Parse product/collection JSON fields that may be JSON, CSV, or already-decoded."""
import json


def parse_json_list(value):
    """Return a list of non-empty strings from JSON, CSV, a list, or a dict's keys."""
    if value is None or value == '':
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [str(key).strip() for key in value.keys() if str(key).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return [part.strip() for part in text.split(',') if part.strip()]
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, dict):
        return [str(key).strip() for key in parsed.keys() if str(key).strip()]
    label = str(parsed).strip()
    return [label] if label else []


def parse_json_object(value):
    """Return a dict from JSON or an existing mapping. Never raises."""
    if isinstance(value, dict):
        return value
    if value is None or value == '':
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def store_json_list(value):
    """Normalize admin form input into a JSON array string."""
    return json.dumps(parse_json_list(value))
