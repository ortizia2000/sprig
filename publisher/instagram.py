"""Instagram publishing via the Instagram Graph API (image, carousel, reel).
Docs: graph.facebook.com /{ig-user-id}/media -> /{ig-user-id}/media_publish."""
import time

import requests

from . import config


def _create(params):
    r = requests.post(
        f"{config.GRAPH}/{config.IG_USER_ID}/media",
        data={**params, "access_token": config.META_TOKEN},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["id"]


def _wait_ready(creation_id, tries=40, delay=6):
    """Images are ready instantly; reels/carousels need processing time."""
    for _ in range(tries):
        s = requests.get(
            f"{config.GRAPH}/{creation_id}",
            params={"fields": "status_code", "access_token": config.META_TOKEN},
            timeout=30,
        ).json()
        code = s.get("status_code")
        if code in (None, "FINISHED"):
            return
        if code == "ERROR":
            raise RuntimeError(f"IG container error: {s}")
        time.sleep(delay)
    raise TimeoutError(f"IG container {creation_id} never finished processing")


def _publish(creation_id):
    _wait_ready(creation_id)
    r = requests.post(
        f"{config.GRAPH}/{config.IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": config.META_TOKEN},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def publish_single(image_url, caption):
    return _publish(_create({"image_url": image_url, "caption": caption}))


def publish_carousel(image_urls, caption):
    children = [_create({"image_url": u, "is_carousel_item": "true"}) for u in image_urls]
    cid = _create({"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
    return _publish(cid)


def publish_reel(video_url, caption):
    return _publish(_create({"media_type": "REELS", "video_url": video_url, "caption": caption}))
