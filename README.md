# Sprig

A tiny, self-owned social auto-publisher. Schedules and **auto-publishes** posts to
**Instagram, Facebook, and LinkedIn** straight from a YAML file, run for free by GitHub Actions.
No monthly fee, no third-party scheduler. (Working name — rename freely.)

> Built as a standalone project. Could become a product later.

## How it works

```
content/posts.yaml   ->   GitHub Actions (hourly cron)   ->   publisher/publish.py   ->   IG / FB / LinkedIn
content/media/        (raw image + video URLs Instagram fetches)
```

- Each post lists a date, time, timezone, platforms, media files, and bilingual captions.
- The Action runs every hour and publishes anything that is **due and not yet sent**.
- A small `content/state/published.json` is committed back so nothing ever double-posts.
- The Instagram Graph API is free; the only "cost" is GitHub Actions minutes (free tier covers this easily).

## One-time setup (~30–45 min, no coding)

### 1. Meta app + token (covers Instagram + Facebook)
1. [developers.facebook.com](https://developers.facebook.com) → **Create App** → type **Business**.
2. Add the **Instagram Graph API** + **Facebook Login** products.
3. Connect the **Mycelium AI** Page and **@myceliumai.co** (already linked) to the app.
4. Generate a **Page access token** with: `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`.
   - Best: create a **System User** in Business Settings and give it a **never-expiring** token (no refresh ever).
5. Grab the **Page ID** (Page → About) and confirm the **IG business id** (`17841434173594422`).
   - Self-publishing to your own account does **not** need Meta App Review — just add your account
     as a role/tester on the app while it's in Development mode.

### 2. LinkedIn (optional, do later)
LinkedIn is stricter: create a LinkedIn app, request **Community Management API** access (an approval
step, can take a few days), then get an OAuth token with `w_organization_social`. Once you have the
token + your organization id, add `linkedin` to a post's `platforms`. Until then, IG + FB run fine.

### 3. Add the secrets in GitHub
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `META_ACCESS_TOKEN` | the Page / System User token |
| `IG_USER_ID` | `17841434173594422` |
| `FB_PAGE_ID` | your Mycelium AI Page id |
| `MEDIA_BASE_URL` | `https://raw.githubusercontent.com/ortizia2000/sprig/main/content/media` |
| `LINKEDIN_ACCESS_TOKEN` | (later) |
| `LINKEDIN_ORG_ID` | (later) |

### 4. Test it
Repo → **Actions → publish → Run workflow**. Check the logs for `PUBLISHED ...`. Then it runs hourly on its own.

## Dashboard

A static dashboard lives in `docs/` and shows every post, its status, and (once live)
performance numbers pulled from the IG/FB APIs. It reads `docs/data.json`, which the
publish + metrics workflows rebuild and commit automatically.

Turn it on once: repo → **Settings → Pages → Source: Deploy from a branch → `main` / `/docs` → Save**.
It will be served at **https://ortizia2000.github.io/sprig/**. "Edit the queue" on the page links
straight to the GitHub editor for `posts.yaml`.

## Adding posts
Drop the image(s)/video in `content/media/`, add an entry to `content/posts.yaml`, commit. Done.

## Run locally (optional)
```bash
pip install -r requirements.txt
cp .env.example .env   # fill in tokens
set -a && source .env && set +a
python -m publisher.publish
```

## Notes
- Repo is public so Instagram can fetch the images. No tokens live in the code — they're GitHub secrets.
  To go private later, move `content/media/` to a public host and update `MEDIA_BASE_URL`.
- v1 is untested against live tokens; expect to debug a Meta gotcha or two on the first real run.
