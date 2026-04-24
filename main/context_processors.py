from urllib.parse import urljoin

from django.conf import settings


def site_metadata(request):
    site_url = settings.SITE_URL
    canonical_url = urljoin(f"{site_url}/", request.path.lstrip("/"))
    return {
        "site_url": site_url,
        "canonical_url": canonical_url,
        "og_image_url": urljoin(f"{site_url}/", "static/favicon.png"),
    }
