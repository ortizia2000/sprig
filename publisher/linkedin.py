"""LinkedIn posting (single image + text) via the versioned Posts API.

Two author modes, picked automatically by which id is configured:

  - organization -> LINKEDIN_ORG_ID set. Posts as the Mycelium AI Page. Needs the
    Community Management API (w_organization_social), which LinkedIn DENIED on app
    78imrbqhk3t1bq (2026-08-30), so this path is dark until that is re-applied for.
  - member -> the default. Posts as Nelly using w_member_social from the "Share on
    LinkedIn" product, already granted on app 78lsrn9iubh388.

Either way the token is the gate: with LINKEDIN_ACCESS_TOKEN unset this module
raises, publish.py catches it, and Instagram/Facebook still go out."""
import requests

from . import config

API = "https://api.linkedin.com/rest"
_author_cache = None


def _raise_api_error(r, what):
    """LinkedIn puts the real reason in the JSON body; surface it, not a bare 4xx."""
    try:
        err = r.json()
    except ValueError:
        r.raise_for_status()
        return
    raise RuntimeError(
        f"LinkedIn {what} failed ({r.status_code}): "
        f"{err.get('message') or err} [code {err.get('serviceErrorCode', '?')}]"
    )


def _headers():
    return {
        "Authorization": f"Bearer {config.LINKEDIN_TOKEN}",
        "LinkedIn-Version": config.LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _member_urn():
    """Member id from config, else one /v2/userinfo lookup (openid scope) per run."""
    if config.LINKEDIN_MEMBER_ID:
        return f"urn:li:person:{config.LINKEDIN_MEMBER_ID}"
    r = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {config.LINKEDIN_TOKEN}"},
        timeout=30,
    )
    if not r.ok:
        _raise_api_error(r, "userinfo lookup")
    return f"urn:li:person:{r.json()['sub']}"


def _author():
    global _author_cache
    if _author_cache is None:
        _author_cache = (
            f"urn:li:organization:{config.LINKEDIN_ORG_ID}"
            if config.LINKEDIN_ORG_ID
            else _member_urn()
        )
    return _author_cache


def _upload_image(image_url, owner):
    init = requests.post(
        f"{API}/images?action=initializeUpload",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"initializeUploadRequest": {"owner": owner}},
        timeout=60,
    )
    if not init.ok:
        _raise_api_error(init, "image upload init")
    v = init.json()["value"]
    binary = requests.get(image_url, timeout=60).content
    put = requests.put(
        v["uploadUrl"], data=binary,
        headers={"Authorization": f"Bearer {config.LINKEDIN_TOKEN}"}, timeout=120,
    )
    if not put.ok:
        _raise_api_error(put, "image upload")
    return v["image"]


def publish_image(image_url, text):
    if not config.LINKEDIN_TOKEN:
        raise RuntimeError("LinkedIn not configured (need LINKEDIN_ACCESS_TOKEN)")
    owner = _author()
    body = {
        "author": owner,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "content": {"media": {"id": _upload_image(image_url, owner)}},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    r = requests.post(f"{API}/posts", headers={**_headers(), "Content-Type": "application/json"},
                      json=body, timeout=60)
    if not r.ok:
        _raise_api_error(r, "post create")
    return r.headers.get("x-restli-id", "posted")
