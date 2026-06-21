"""Facebook Page publishing (photo, multi-photo post, video) via the Graph API."""
import json

import requests

from . import config


def _upload_photo(image_url, published):
    r = requests.post(
        f"{config.GRAPH}/{config.FB_PAGE_ID}/photos",
        data={"url": image_url, "published": str(published).lower(), "access_token": config.META_TOKEN},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["id"]


def publish_images(image_urls, message):
    if len(image_urls) == 1:
        r = requests.post(
            f"{config.GRAPH}/{config.FB_PAGE_ID}/photos",
            data={"url": image_urls[0], "message": message, "published": "true",
                  "access_token": config.META_TOKEN},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()
    ids = [_upload_photo(u, published=False) for u in image_urls]
    attached = json.dumps([{"media_fbid": i} for i in ids])
    r = requests.post(
        f"{config.GRAPH}/{config.FB_PAGE_ID}/feed",
        data={"message": message, "attached_media": attached, "access_token": config.META_TOKEN},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def publish_video(video_url, message):
    r = requests.post(
        f"{config.GRAPH}/{config.FB_PAGE_ID}/videos",
        data={"file_url": video_url, "description": message, "access_token": config.META_TOKEN},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()
