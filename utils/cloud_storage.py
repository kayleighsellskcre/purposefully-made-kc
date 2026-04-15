"""Cloud image storage via Cloudflare R2 (S3-compatible).

Falls back to local static/uploads storage when R2 is not configured,
so dev environments work without any setup.

R2 setup (one-time, ~5 minutes):
  1. Cloudflare Dashboard → R2 Object Storage → Create bucket
     Name it something like: kb-apparel-uploads
  2. R2 → Manage R2 API Tokens → Create API Token
     Permission: Object Read & Write  |  Scope: your bucket
     Copy: Account ID, Access Key ID, Secret Access Key
  3. R2 → your bucket → Settings → Public Access → Allow Access
     Copy the  https://pub-xxxx.r2.dev  URL shown
  4. Add these Railway env vars:
       R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
       R2_BUCKET_NAME, R2_PUBLIC_URL
"""
import time
from pathlib import Path
from werkzeug.utils import secure_filename


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def r2_configured(app):
    """True when all five R2 env vars are present."""
    return all([
        app.config.get('R2_ACCOUNT_ID'),
        app.config.get('R2_ACCESS_KEY_ID'),
        app.config.get('R2_SECRET_ACCESS_KEY'),
        app.config.get('R2_BUCKET_NAME'),
        app.config.get('R2_PUBLIC_URL'),
    ])


def upload_image(file_storage, app, subfolder='uploads', public_id_prefix='img'):
    """Upload a FileStorage object and return a persistent URL or relative path.

    Returns:
        str: Full https:// URL when R2 is configured, otherwise a relative
             path like 'uploads/<subfolder>/filename.ext' (local dev fallback).
    """
    if r2_configured(app):
        return _upload_to_r2(file_storage, app, subfolder, public_id_prefix)
    return _save_locally(file_storage, app, subfolder, public_id_prefix)


def image_url(path_or_url):
    """Convert a stored value to a usable <img src> URL.

    Handles:
      - Full https:// R2 (or any CDN) URLs  → returned as-is
      - Legacy relative paths like 'uploads/designs/foo.png' → /static/uploads/...
    Used as a Jinja2 template filter registered in app.py.
    """
    if path_or_url and path_or_url.startswith('http'):
        return path_or_url
    from flask import url_for
    return url_for('static', filename=path_or_url)


# ---------------------------------------------------------------------------
# Internal helpers — not imported by routes directly
# ---------------------------------------------------------------------------

def _make_key(file_storage, subfolder, public_id_prefix):
    """Build the R2 object key, e.g. custom_requests/request_1_1713000000_logo.jpg"""
    filename = secure_filename(file_storage.filename or 'upload')
    name_base = filename.rsplit('.', 1)[0][:50]
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    unique_name = f"{public_id_prefix}_{int(time.time())}_{name_base}.{ext}"
    return f"{subfolder}/{unique_name}"


def _upload_to_r2(file_storage, app, subfolder, public_id_prefix):
    """Upload to Cloudflare R2 and return the public https:// URL."""
    import boto3
    from botocore.config import Config

    account_id = app.config['R2_ACCOUNT_ID']
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

    s3 = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=app.config['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=app.config['R2_SECRET_ACCESS_KEY'],
        region_name='auto',
        config=Config(signature_version='s3v4'),
    )

    key = _make_key(file_storage, subfolder, public_id_prefix)
    bucket = app.config['R2_BUCKET_NAME']

    # Detect content type from extension
    ext = key.rsplit('.', 1)[-1].lower()
    content_types = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png', 'webp': 'image/webp',
        'gif': 'image/gif', 'svg': 'image/svg+xml',
    }
    content_type = content_types.get(ext, 'application/octet-stream')

    s3.upload_fileobj(
        file_storage,
        bucket,
        key,
        ExtraArgs={'ContentType': content_type},
    )

    public_url = app.config['R2_PUBLIC_URL'].rstrip('/')
    return f"{public_url}/{key}"


def _save_locally(file_storage, app, subfolder, public_id_prefix):
    """Fallback: save to local static/uploads/. Works for local dev with no config."""
    filename = secure_filename(file_storage.filename or 'upload')
    name_base = filename.rsplit('.', 1)[0][:50]
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    unique_name = f"{public_id_prefix}_{int(time.time())}_{name_base}.{ext}"

    upload_dir = Path(app.config['UPLOAD_FOLDER']) / subfolder
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_storage.save(str(upload_dir / unique_name))

    return f"uploads/{subfolder}/{unique_name}"
