"""Environment + constants. Secrets come from env (GitHub Actions secrets); never hard-code tokens."""
import os

GRAPH = "https://graph.facebook.com/v21.0"

# Meta (Instagram + Facebook share one Page access token)
META_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")      # @myceliumai.co business id = 17841434173594422
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")       # Mycelium AI Page id

# LinkedIn — two author modes, see publisher/linkedin.py:
#  - member (live today): "Share on LinkedIn" + w_member_social are granted on app
#    78lsrn9iubh388, so posts go out as Nelly. LINKEDIN_MEMBER_ID is optional; when
#    unset it is resolved from /v2/userinfo using the openid scope on the same app.
#  - organization (Mycelium AI Page): needs the Community Management API, which was
#    denied on app 78imrbqhk3t1bq. Set LINKEDIN_ORG_ID only once that is approved.
LINKEDIN_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_ORG_ID = os.environ.get("LINKEDIN_ORG_ID", "")
LINKEDIN_MEMBER_ID = os.environ.get("LINKEDIN_MEMBER_ID", "")
# Versioned-API date. LinkedIn retires versions about a year out, so this needs an
# occasional bump; override by env when calls start coming back 426 instead of 200.
LINKEDIN_VERSION = os.environ.get("LINKEDIN_VERSION") or "202508"

# Instagram auth — two flows, pick one:
#  - Direct Login (easiest, no Facebook Page needed): set IG_ACCESS_TOKEN and all
#    IG calls go to graph.instagram.com. Scopes: instagram_business_basic +
#    instagram_business_content_publish. Token is long-lived (60 days, refreshable).
#  - Legacy Page token: leave IG_ACCESS_TOKEN unset; the shared META_ACCESS_TOKEN
#    + graph.facebook.com are used (IG account must be linked to the FB Page).
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_TOKEN = IG_ACCESS_TOKEN or META_TOKEN
IG_GRAPH = os.environ.get("IG_API_BASE") or \
    ("https://graph.instagram.com/v22.0" if IG_ACCESS_TOKEN else GRAPH)

# TikTok (Content Posting API). Video-only. Until TikTok's app audit is passed,
# keep TIKTOK_MODE=inbox: videos land in her TikTok inbox as drafts and she taps
# publish in-app (direct public posting is audit-gated). See publisher/tiktok.py.
TIKTOK_CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
TIKTOK_REFRESH_TOKEN = os.environ.get("TIKTOK_REFRESH_TOKEN", "")
TIKTOK_MODE = os.environ.get("TIKTOK_MODE") or "inbox"          # inbox | direct
TIKTOK_PRIVACY = os.environ.get("TIKTOK_PRIVACY") or "SELF_ONLY"  # direct mode only

# Public base URL Instagram/Facebook fetch images from (raw GitHub by default).
# `or` (not a get-default) so an empty env var from an unset secret still falls back.
MEDIA_BASE_URL = os.environ.get("MEDIA_BASE_URL") or \
    "https://raw.githubusercontent.com/ortizia2000/sprig/main/content/media"
