"""Environment + constants. Secrets come from env (GitHub Actions secrets); never hard-code tokens."""
import os

GRAPH = "https://graph.facebook.com/v21.0"

# Meta (Instagram + Facebook share one Page access token)
META_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")      # @myceliumai.co business id = 17841434173594422
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")       # Mycelium AI Page id

# LinkedIn (organization posting — needs a LinkedIn app + Community Management access)
LINKEDIN_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_ORG_ID = os.environ.get("LINKEDIN_ORG_ID", "")

# Public base URL Instagram/Facebook fetch images from (raw GitHub by default).
# `or` (not a get-default) so an empty env var from an unset secret still falls back.
MEDIA_BASE_URL = os.environ.get("MEDIA_BASE_URL") or \
    "https://raw.githubusercontent.com/ortizia2000/sprig/main/content/media"
