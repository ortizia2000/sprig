"""Instagram publishing via the Instagram Graph API (image, carousel, reel).
Works with either auth flow in config.py: Direct Login (graph.instagram.com,
IG_ACCESS_TOKEN) or the legacy Page token (graph.facebook.com, META_ACCESS_TOKEN)."""
import time

import requests

from . import config


def _raise_api_error(r):
    """Meta puts the real reason in the JSON body; surface it instead of a bare 400."""
    try:
        err = r.json()["error"]
    except (ValueError, KeyError):
        r.raise_for_status()
        return
    sub = f"/{err['error_subcode']}" if err.get("error_subcode") else ""
    raise RuntimeError(
        f"IG API error {err.get('code')}{sub}: {err.get('message')}"
        f" (fbtrace_id: {err.get('fbtrace_id')})"
    )


def _post(path, data):
    r = requests.post(
        f"{config.IG_GRAPH}/{path}",
        data={**data, "access_token": config.IG_TOKEN},
        timeout=60,
    )
    if not r.ok:
        _raise_api_error(r)
    return r.json()


def _get(path, params):
    r = requests.get(
        f"{config.IG_GRAPH}/{path}",
        params={**params, "access_token": config.IG_TOKEN},
        timeout=30,
    )
    if not r.ok:
        _raise_api_error(r)
    return r.json()


def _create(params):
    return _post(f"{config.IG_USER_ID}/media", params)["id"]


def _wait_ready(creation_id, tries=40, delay=6):
    """Poll a container until FINISHED. Meta downloads the media from
    MEDIA_BASE_URL during this stage; images are quick, reels take longer."""
    for _ in range(tries):
        s = _get(creation_id, {"fields": "status_code"})
        code = s.get("status_code")
        if code in (None, "FINISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG container {creation_id} failed ({code}): {s}")
        time.sleep(delay)
    raise TimeoutError(f"IG container {creation_id} never finished processing")


def _publish(creation_id):
    _wait_ready(creation_id)
    return _post(f"{config.IG_USER_ID}/media_publish", {"creation_id": creation_id})


def publish_single(image_url, caption):
    return _publish(_create({"image_url": image_url, "caption": caption}))


def publish_carousel(image_urls, caption):
    if not 2 <= len(image_urls) <= 10:
        raise ValueError(f"IG carousels take 2-10 items, got {len(image_urls)}")
    children = [_create({"image_url": u, "is_carousel_item": "true"}) for u in image_urls]
    for child in children:  # each child must be FINISHED before the carousel container
        _wait_ready(child)
    cid = _create({"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
    return _publish(cid)


def publish_reel(video_url, caption):
    return _publish(_create({"media_type": "REELS", "video_url": video_url, "caption": caption}))
