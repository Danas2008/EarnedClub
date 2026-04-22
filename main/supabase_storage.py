import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from django.conf import settings


def storage_enabled():
    return settings.SUPABASE_STORAGE_ENABLED


def _storage_headers(content_type=None):
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _request(url, method="GET", headers=None, data=None):
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def build_object_path(prefix, filename):
    suffix = Path(filename or "").suffix.lower() or ""
    safe_prefix = prefix.strip("/").replace(" ", "-") or "asset"
    return f"{safe_prefix}/{uuid.uuid4().hex}{suffix}"


def upload_content(bucket, object_path, content, content_type=None):
    if not storage_enabled():
        return False

    quoted_path = urllib.parse.quote(object_path, safe="/")
    url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{quoted_path}"
    headers = _storage_headers(content_type or mimetypes.guess_type(object_path)[0] or "application/octet-stream")
    headers["x-upsert"] = "true"
    try:
        _request(url, method="POST", headers=headers, data=content)
        return True
    except urllib.error.URLError:
        return False
    except urllib.error.HTTPError:
        return False


def delete_object(bucket, object_path):
    if not storage_enabled() or not object_path:
        return False

    quoted_path = urllib.parse.quote(object_path, safe="/")
    url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{quoted_path}"
    try:
        _request(url, method="DELETE", headers=_storage_headers())
        return True
    except urllib.error.URLError:
        return False
    except urllib.error.HTTPError:
        return False


def get_public_object_url(bucket, object_path):
    if not object_path or not settings.SUPABASE_URL:
        return ""
    quoted_path = urllib.parse.quote(object_path, safe="/")
    return f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket}/{quoted_path}"


def create_signed_object_url(bucket, object_path, expires_in=None):
    if not storage_enabled() or not object_path:
        return ""

    quoted_path = urllib.parse.quote(object_path, safe="/")
    url = f"{settings.SUPABASE_URL}/storage/v1/object/sign/{bucket}/{quoted_path}"
    payload = json.dumps({"expiresIn": expires_in or settings.SUPABASE_SIGNED_URL_TTL}).encode("utf-8")
    headers = _storage_headers("application/json")
    try:
        raw_response = _request(url, method="POST", headers=headers, data=payload)
        response = json.loads(raw_response.decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return ""

    signed_path = response.get("signedURL") or response.get("signedUrl") or ""
    if not signed_path:
        return ""
    if signed_path.startswith("http://") or signed_path.startswith("https://"):
        return signed_path
    return f"{settings.SUPABASE_URL}/storage/v1{signed_path}"
