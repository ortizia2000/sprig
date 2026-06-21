"""Pulls performance numbers for already-published posts and writes content/metrics.json.
Run daily by GitHub Actions. Read-only against the Graph API.

    python -m publisher.metrics
"""
import json
import os

import requests

from . import config
from .state import all_refs

METRICS_FILE = os.path.join(os.path.dirname(__file__), "..", "content", "metrics.json")


def _ig_insights(media_id):
    for metric_set in ("reach,likes,comments,saved", "reach,likes,comments,saved,views,plays,shares"):
        r = requests.get(
            f"{config.GRAPH}/{media_id}/insights",
            params={"metric": metric_set, "access_token": config.META_TOKEN},
            timeout=30,
        )
        if r.ok:
            return {m["name"]: m["values"][0]["value"] for m in r.json().get("data", [])}
    return {}


def _fb_basic(post_id):
    r = requests.get(
        f"{config.GRAPH}/{post_id}",
        params={"fields": "reactions.summary(true),comments.summary(true)", "access_token": config.META_TOKEN},
        timeout=30,
    )
    if not r.ok:
        return {}
    j = r.json()
    return {
        "reactions": j.get("reactions", {}).get("summary", {}).get("total_count"),
        "comments": j.get("comments", {}).get("summary", {}).get("total_count"),
    }


def run():
    out = {}
    for pid, platforms in all_refs().items():
        out[pid] = {}
        ig = platforms.get("instagram")
        fb = platforms.get("facebook")
        if isinstance(ig, str):
            out[pid]["instagram"] = _ig_insights(ig)
        if isinstance(fb, str):
            out[pid]["facebook"] = _fb_basic(fb)
    with open(METRICS_FILE, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    print(f"metrics written for {len(out)} post(s)")


if __name__ == "__main__":
    run()
