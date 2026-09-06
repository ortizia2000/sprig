# Sprig

A tiny, self-owned social auto-publisher. Schedules and **auto-publishes** posts to
**Instagram, Facebook, and LinkedIn** straight from a YAML file, run for free by GitHub Actions.
No monthly fee, no third-party scheduler. (Working name — rename freely.)

> Built as a standalone project. Could become a product later.

## Dashboard buttons (approve · edit · delete · upload) and slide rendering

The dashboard at `docs/` (GitHub Pages) can now change the queue without touching
`posts.yaml`. Click a post to open its preview; the buttons live there.

| Button | What it writes | Notes |
|---|---|---|
| **✓ Aprobar** | `review: false` + a **new** date/time | Only on posts held with `review: true`. Always asks for the date; never reuses the stale one in the YAML. |
| **✎ Editar** | `caption_en`, `caption_es`, `hashtags`, optionally date/time | Character counter; refuses to save past Instagram's 2,200. |
| **🗑 Borrar** | `deleted: true` | Leaves the queue, nothing is deleted from the repo. **↩ Restaurar** undoes it. Filter *Deleted* shows them. |
| **⇄ Reemplazar / + Añadir / − Quitar** | `media: [...]` | Uploads go to `docs/media/` **and** `content/media/`. Images are converted in the browser to JPEG ≤1440px (Instagram rejects PNG); video must already be `.mp4`. Every upload gets a new filename, old files stay. |
| **⬆ Subir media** (toolbar) | a file only | For a post you will write by hand in `posts.yaml`; shows the URL and the YAML line. |

Everything lands in `content/schedule.json` (see `publisher/overrides.py` for the keys the
publisher honours). `posts.yaml` remains the source; the override file is the layer you touch
from the browser. Writes need the same fine-grained GitHub token as drag-and-drop
(*Enable editing*); it is stored only in your browser.

### Slides rendered by GitHub Actions

Carousel slides that are built as HTML live in `slides/<post-id>/s1.html … sN.html`
(+ `tpl.css` + images). Editing any of those files on `main` — the GitHub web editor is
enough — triggers `.github/workflows/render.yml`, which screenshots them with headless
Chrome and commits `docs/media/<post-id>-<n>.jpg` + `content/media/<post-id>-<n>.jpg`
(1440×1800 JPEG, the same output as `tools/add-media.sh`). About two minutes later the
post shows the new images.

`slides/<post-id>/manifest.json` records a hash of the sources: an unchanged set is never
re-rendered, so images approved from a macOS render are not replaced by a Linux render
under a post that is already scheduled. Locally:

```bash
python tools/render_slides.py --check          # STALE / FRESH per set
python tools/render_slides.py banquete-mta     # render one set with your Chrome
python tools/render_slides.py --record <set>   # pin the manifest to the JPEGs already on disk
```

Linux has no Georgia / Helvetica Neue / Courier New; the workflow maps them to Gelasio /
Liberation Sans / Liberation Mono (metric-compatible), so line breaks hold. Check the first
Linux render of a set before trusting it blindly.

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

### 1a. Instagram — Direct Login (recommended: no Facebook Page, no System User)
The easiest way to get Instagram working, using ["API setup with Instagram Login"](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login) (launched July 2024):
1. Make the IG account **Creator** or **Business**: Instagram app → Settings → Account type and tools → Switch to Professional.
2. [developers.facebook.com](https://developers.facebook.com) → **Create App** → use case **Other** → type **Business**.
3. Add the **Instagram** product → **API setup with Instagram Login** → connect **@myceliumai.co**.
   Add a placeholder OAuth Redirect URI (e.g. `https://localhost.local/cb`). Note the App ID + App Secret.
4. Authorize in the browser (`api.instagram.com/oauth/authorize`) with scopes
   **`instagram_business_basic` + `instagram_business_content_publish`**
   — the old names (`instagram_basic`, `instagram_content_publish`) **stopped working 2025-01-27**.
   The redirect lands on a 404; that's expected — copy the `code` from the URL.
5. Exchange the code for a short-lived token (`POST api.instagram.com/oauth/access_token` — also
   returns your `user_id`, which is `IG_USER_ID`), then exchange that for a **long-lived 60-day token**
   (`GET graph.instagram.com/access_token?grant_type=ig_exchange_token`). Save it as `IG_ACCESS_TOKEN`.
6. **Refresh before day 60** (calendar reminder at ~day 55):
   ```bash
   curl -G https://graph.instagram.com/refresh_access_token \
     -d grant_type=ig_refresh_token -d access_token=$CURRENT_TOKEN
   ```

### 1b. Facebook — Page token (required for FB posting; can also cover IG if linked)
1. In the same (or a separate) Meta app, add **Facebook Login for Business**.
2. Connect the **Mycelium AI** Page and generate a **Page access token** with
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`.
   - Best: create a **System User** in Business Settings and give it a **never-expiring** token (no refresh ever).
3. Grab the **Page ID** (Page → About) → `FB_PAGE_ID`, token → `META_ACCESS_TOKEN`.
   - If the IG account is linked to this Page and the token also has the Instagram permissions,
     you can skip 1a entirely and leave `IG_ACCESS_TOKEN` unset — IG calls then use this token.
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
| `IG_ACCESS_TOKEN` | the Direct Login 60-day token (path 1a; leave unset if using the Page token for IG) |
| `IG_USER_ID` | `17841434173594422` |
| `META_ACCESS_TOKEN` | the Page / System User token (path 1b) |
| `FB_PAGE_ID` | your Mycelium AI Page id |
| `MEDIA_BASE_URL` | `https://raw.githubusercontent.com/ortizia2000/sprig/main/content/media` |
| `LINKEDIN_ACCESS_TOKEN` | (later) |
| `LINKEDIN_ORG_ID` | (later) |

### 4. Pre-flight check, then test it
Repo → **Actions → check → Run workflow**. It verifies the tokens against the live API
(prints the IG username / FB Page name it's about to post as) and HEAD-requests every media
URL to confirm Meta will be able to fetch it — without publishing anything.
Once it's green: **Actions → publish → Run workflow**, check the logs for `PUBLISHED ...`.
Then it runs hourly on its own.

## Dashboard

A static dashboard lives in `docs/` and shows every post, its status, and (once live)
performance numbers pulled from the IG/FB APIs. It reads `docs/data.json`, which the
publish + metrics workflows rebuild and commit automatically.

Turn it on once: repo → **Settings → Pages → Source: Deploy from a branch → `main` / `/docs` → Save**.
It will be served at **https://ortizia2000.github.io/sprig/**. "Edit the queue" on the page links
straight to the GitHub editor for `posts.yaml`.

## Rescheduling from the dashboard (drag-and-drop)

The dashboard can change *when* a post goes live, no editing files by hand:
1. Click **Enable editing** and paste a GitHub **fine-grained token** (Repository access: only this repo, Permissions → Contents → Read and write). It's stored only in your browser, never in the code.
2. In **Calendar** view, **drag a post to another day**, or **double-click** it (or click the When cell in the table) to set the exact **time**.
3. That writes `content/schedule.json` (per-post date/time overrides) via the GitHub API. The publisher and dashboard both respect it.

Captions/media still live in `posts.yaml`; the schedule overrides only the date/time.

## Adding posts
Drop the image(s)/video in `content/media/`, add an entry to `content/posts.yaml`, commit. Done.

## Run locally (optional)
```bash
pip install -r requirements.txt
cp .env.example .env   # fill in tokens
set -a && source .env && set +a
python tools/check_auth.py     # pre-flight: tokens + media reachability
python -m publisher.publish
```
Tests (no network, no tokens needed): `pip install pytest && python -m pytest tests/`

## Instagram limits & gotchas

Hard limits (Meta):
- Carousels take **2–10** items; images **≤ 8 MB**, aspect ratio between **4:5 and 1.91:1**.
- JPEG is the documented format; PNG works in practice. Max 100 published posts per 24 h.

| Symptom | Likely cause | Fix |
|---|---|---|
| `Invalid OAuth access token` / scope error | Token expired or made with the pre-2025 scope names | Redo path 1a (or refresh if < 60 days old) |
| `400 Image url is invalid` | Meta can't fetch the media URL | Run the **check** workflow; verify `MEDIA_BASE_URL` and that the repo/host is public |
| `Subject must be a business account` | IG account is still Personal | Switch it to Creator/Business in the IG app |
| Container stuck `IN_PROGRESS`, then timeout | Image too big or wrong ratio | Keep ≤ 8 MB and 4:5–1.91:1; re-export |
| Reel container slow | Normal — video processing | The publisher polls up to ~4 min before giving up |

## Notes
- Repo is public so Instagram can fetch the images. No tokens live in the code — they're GitHub secrets.
  To go private later, move `content/media/` to a public host and update `MEDIA_BASE_URL`.
- v1 is untested against live tokens; run the **check** workflow first — it catches the common
  Meta gotchas (bad token, wrong account type, unfetchable media) before anything goes out.
