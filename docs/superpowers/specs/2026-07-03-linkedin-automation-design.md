# LinkedIn Company-Page Automation — Design (DRAFT, pending approval)

**Date:** 2026-07-03
**Status:** Draft — awaiting user approval before implementation planning
**Decisions made:** post as the Mycelium AI **company page** (not personal profile); scope = ready kit **+ automatic token refresh**; metrics deferred.

## Context

Sprig already has LinkedIn plumbing half-built:

- `publisher/linkedin.py` posts a single image + English-only caption as an organization via `POST /rest/posts` (Community Management API).
- `publisher/publish.py` already routes `linkedin` entries in a post's `platforms:` list to it.
- `.github/workflows/publish.yml` already injects `LINKEDIN_ACCESS_TOKEN` / `LINKEDIN_ORG_ID` secrets.

What's missing: real credentials (no LinkedIn app exists yet), a current API version, pre-flight checks, token refresh, docs, and tests.

Verified against current LinkedIn docs (2026-07):

- Org posting requires the **Community Management API** product: create an app, associate + verify it with the company page, submit the access form, wait for LinkedIn review (days). Development tier is enough for self-posting.
- Access tokens live **60 days**; approved apps get **programmatic refresh tokens valid 365 days**.
- `LinkedIn-Version` headers use `YYYYMM`; the code's pinned `202405` is past LinkedIn's ~12-month sunset window and must be bumped.

## Design

### 1. Existing plumbing (no changes)

The publish path, platform routing, and workflow secret injection stay as they are.

### 2. `publisher/linkedin.py` fixes

- Bump `LinkedIn-Version` to a current `2026xx` release; move it to a constant in `publisher/config.py`.
- Reel-type posts: raise a clear error ("LinkedIn video posting not supported — keep `linkedin` off reel posts") instead of trying to upload an mp4 as an image. Video support is future work.

### 3. New: `tools/linkedin_auth.py` — OAuth + refresh helper

Three subcommands, matching the style of existing tools:

- `url` — prints the browser authorize URL with the right scopes (`w_organization_social` + read/admin scopes to list orgs; exact scope names verified against current docs during implementation).
- `exchange <code>` — swaps the OAuth code for the 60-day access token + 365-day refresh token, prints both with expiry dates, and lists the org IDs the user administers (copy-paste `LINKEDIN_ORG_ID`).
- `refresh` — mints a fresh access token from the refresh token (used manually and by the workflow below).

Reads `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` / `LINKEDIN_REFRESH_TOKEN` from env (same `.env` pattern as the rest of the repo).

### 4. New: `.github/workflows/linkedin-refresh.yml` — auto-refresh

- Monthly cron (60-day tokens refreshed every ~30 days = 2× safety margin) + `workflow_dispatch`.
- Runs `linkedin_auth.py refresh`, masks the token in logs, rotates the `LINKEDIN_ACCESS_TOKEN` secret via `gh secret set`.
- Auth for secret rotation: a fine-grained PAT (this repo only, secrets: write) stored as `SECRETS_ADMIN_PAT`.
- Failure → red run → GitHub email notification.
- Warns when the 365-day refresh token is within ~30 days of expiry (the one yearly manual re-auth).

### 5. Pre-flight: `check_linkedin()` in `tools/check_auth.py`

Follows the existing OK/FAIL/SKIP pattern:

- Verifies the token via LinkedIn's introspection endpoint; prints days-until-expiry, warns under 14 days.
- Confirms the token can see the configured org.
- Wired into `.github/workflows/check.yml` with the new env vars.

### 6. README runbook + `.env.example`

Replace the thin "LinkedIn (optional, do later)" README section with the real 2026 steps:

1. Create app at developers.linkedin.com; associate + verify it with the Mycelium AI company page.
2. Products → request **Community Management API** access (form + review, can take days).
3. Once approved: `python tools/linkedin_auth.py url` → authorize in browser → `exchange <code>`.
4. Add GitHub secrets: `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_ORG_ID`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_REFRESH_TOKEN`, `SECRETS_ADMIN_PAT`.
5. Run the check workflow; once green, add `linkedin` to `platforms:` on posts.

`.env.example` gains the new variables.

### 7. Rollout + warning

- LinkedIn goes on **future posts only**.
- **Warning:** the 5 existing posts are all past-due; adding `linkedin` to them would fire all 5 into the page in a single hourly run. Do not backfill via `platforms:`.

### 8. Testing

Mock-based tests (no live API calls), following the existing pytest + conftest patterns:

- `linkedin.py` publish path (upload init → binary PUT → post creation), including the reel error.
- `linkedin_auth.py` exchange/refresh response parsing.
- `check_linkedin()` OK/FAIL/SKIP behavior.

## Out of scope (deferred)

- LinkedIn metrics (likes/comments via `r_organization_social`) in `metrics.py` + dashboard.
- LinkedIn video posting.
- Multi-image LinkedIn posts (carousels keep posting the first/English image).
