"""LinkedIn organization posting (single image + text) via the Posts API.

NOTE: LinkedIn is the hard one. It needs its own LinkedIn app with the
Community Management API approved, plus an OAuth token with w_organization_social.
Until that app is approved + LINKEDIN_ACCESS_TOKEN / LINKEDIN_ORG_ID are set,
this module no-ops with a clear error (caught by publish.py, so IG/FB still go out)."""
import requests

from . import config

API = "https://api.linkedin.com/rest"


def _headers():
    return {
        "Authorization": f"Bearer {config.LINKEDIN_TOKEN}",
        "LinkedIn-Version": "202405",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _upload_image(image_url):
    owner = f"urn:li:organization:{config.LINKEDIN_ORG_ID}"
    init = requests.post(
        f"{API}/images?action=initializeUpload",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"initializeUploadRequest": {"owner": owner}},
        timeout=60,
    )
    init.raise_for_status()
    v = init.json()["value"]
    binary = requests.get(image_url, timeout=60).content
    requests.put(v["uploadUrl"], data=binary,
                 headers={"Authorization": f"Bearer {config.LINKEDIN_TOKEN}"}, timeout=120).raise_for_status()
    return v["image"]


def publish_image(image_url, text):
    if not config.LINKEDIN_TOKEN or not config.LINKEDIN_ORG_ID:
        raise RuntimeError("LinkedIn not configured (need LINKEDIN_ACCESS_TOKEN + LINKEDIN_ORG_ID)")
    owner = f"urn:li:organization:{config.LINKEDIN_ORG_ID}"
    image_urn = _upload_image(image_url)
    body = {
        "author": owner,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "content": {"media": {"id": image_urn}},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    r = requests.post(f"{API}/posts", headers={**_headers(), "Content-Type": "application/json"},
                      json=body, timeout=60)
    r.raise_for_status()
    return r.headers.get("x-restli-id", "posted")
