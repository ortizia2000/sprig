"""Pre-flight check: verifies tokens/account ids and that Meta can actually fetch
your media URLs. Read-only, publishes nothing. Run it before the first live publish:

    python tools/check_auth.py            (locally, with .env loaded)

or from the repo's Actions tab -> "check" -> Run workflow."""
import os
import sys

import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from publisher import config  # noqa: E402

POSTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "content", "posts.yaml")


def _err(r):
    try:
        return r.json()["error"].get("message", "")
    except (ValueError, KeyError):
        return ""


def _li_err(r):
    try:
        return r.json().get("message", "")
    except ValueError:
        return ""


def check_instagram():
    if not (config.IG_TOKEN and config.IG_USER_ID):
        print("SKIP instagram: IG token / IG_USER_ID not configured")
        return None
    r = requests.get(
        f"{config.IG_GRAPH}/{config.IG_USER_ID}",
        params={"fields": "username,id", "access_token": config.IG_TOKEN},
        timeout=30,
    )
    if r.ok:
        flow = "Direct Login" if config.IG_ACCESS_TOKEN else "Page token"
        print(f"OK   instagram: token valid ({flow}), account @{r.json().get('username')}")
        return True
    print(f"FAIL instagram: {r.status_code} {_err(r)}")
    return False


def check_facebook():
    if not (config.META_TOKEN and config.FB_PAGE_ID):
        print("SKIP facebook: META_ACCESS_TOKEN / FB_PAGE_ID not configured")
        return None
    r = requests.get(
        f"{config.GRAPH}/{config.FB_PAGE_ID}",
        params={"fields": "name", "access_token": config.META_TOKEN},
        timeout=30,
    )
    if r.ok:
        print(f"OK   facebook: token valid, Page \"{r.json().get('name')}\"")
        return True
    print(f"FAIL facebook: {r.status_code} {_err(r)}")
    return False


def check_linkedin():
    """Read-only: proves the token works and shows exactly who Sprig would post as."""
    if not config.LINKEDIN_TOKEN:
        print("SKIP linkedin: LINKEDIN_ACCESS_TOKEN not configured")
        return None
    if config.LINKEDIN_ORG_ID:
        r = requests.get(
            "https://api.linkedin.com/rest/organizationAcls",
            params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
            headers={"Authorization": f"Bearer {config.LINKEDIN_TOKEN}",
                     "LinkedIn-Version": config.LINKEDIN_VERSION,
                     "X-Restli-Protocol-Version": "2.0.0"},
            timeout=30,
        )
        if r.ok:
            orgs = [e.get("organization", "") for e in r.json().get("elements", [])]
            target = f"urn:li:organization:{config.LINKEDIN_ORG_ID}"
            if target in orgs:
                print(f"OK   linkedin: token admins {target}")
                return True
            print(f"FAIL linkedin: token does not admin {target} (sees: {orgs or 'none'})")
            return False
        print(f"FAIL linkedin (org): {r.status_code} {_li_err(r)}")
        return False
    r = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {config.LINKEDIN_TOKEN}"},
        timeout=30,
    )
    if r.ok:
        me = r.json()
        print(f"OK   linkedin: token valid, posts as {me.get('name')} "
              f"(urn:li:person:{me.get('sub')})")
        return True
    print(f"FAIL linkedin: {r.status_code} {_li_err(r)}")
    return False


def _media_urls():
    with open(POSTS_FILE) as f:
        posts = yaml.safe_load(f)["posts"]
    base = config.MEDIA_BASE_URL.rstrip("/")
    files = []
    for post in posts:
        files.extend(post.get("media", []))
        if post.get("cover"):
            files.append(post["cover"])
    return [f"{base}/{os.path.basename(m)}" for m in dict.fromkeys(files)]


def check_media(urls=None):
    """Meta downloads media server-side, so every URL must be publicly fetchable
    with an image/* or video/* content-type — otherwise: 400 Image url is invalid."""
    ok = True
    for url in (urls if urls is not None else _media_urls()):
        r = requests.head(url, allow_redirects=True, timeout=30)
        ctype = r.headers.get("Content-Type", "")
        video_ext = url.rsplit(".", 1)[-1].lower() in ("mp4", "mov")
        if r.ok and (ctype.startswith("image/") or ctype.startswith("video/")):
            print(f"OK   media: {url} ({ctype})")
        elif r.ok and video_ext and ctype == "application/octet-stream":
            # raw.githubusercontent serves mp4 this way; Meta usually accepts it
            print(f"WARN media: {url} served as {ctype} — if the reel fails to "
                  f"publish, host the video somewhere that serves video/mp4")
        else:
            print(f"FAIL media: {url} -> {r.status_code} {ctype or 'no content-type'}")
            ok = False
    return ok


def main():
    results = [check_instagram(), check_facebook(), check_linkedin(), check_media()]
    if False in results:
        print("\nPre-flight FAILED — fix the FAIL lines above before publishing.")
        return 1
    print("\nPre-flight passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
