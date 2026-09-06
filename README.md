# Litsan kokoelmat

A shared view of the board game collections of a group of 19 [BoardGameGeek](https://boardgamegeek.com) users. A Python job pulls everyone's collection from the BGG API, merges it into one dataset, and a single static HTML page renders it as a filterable, sortable table.

**Live site:** https://qozop.github.io/litsan-kokoelmat/ (behind a shared password)

## How it works

```
BGG API ──▶ scripts/fetch_collections.py ──▶ data/*.json ──▶ index.html ──▶ GitHub Pages
             (weekly GitHub Action)            (committed)     (static)
```

- **`scripts/fetch_collections.py`** — the whole pipeline. Python 3.12, only dependency is `requests`.
  - *Phase 1* calls the BGG `collection` API for each user (owned boardgames, expansions excluded) and merges ownership into one record per game.
  - *Phase 2* calls the BGG `thing` API in batches to add the canonical English name and the community complexity (weight) score, then writes `data/collection.json`.
  - It also diffs ownership against the previous run and appends an entry to `data/changelog.json` when something changed.
- **`index.html`** — one file, all CSS and JS inline, no framework or build step. Tabs: the full collection, games by owner count, the ownership changelog, and a yearly play challenge. Client-side password gate (SHA-256 hash in the page).
- **GitHub Pages** serves the repo root from `main`; every push redeploys.

## Repository layout

```
index.html                     The webapp (served by GitHub Pages)
data/
  collection.json              Merged, enriched dataset — generated, do not hand-edit
  changelog.json               Append-only ownership-change log, newest first
  challenge.json               Yearly play-challenge game list + played dates
  colors.json                  Per-collector pill colour overrides
scripts/
  fetch_collections.py         BGG data pipeline (Phase 1 + Phase 2)
  compare_csv.py               One-off: diff a legacy CSV export into changelog.json
  backfill_changelog.py        One-off: rebuild missed changelog entries from git history
  setup_challenge.py           One-off: (re)build challenge.json's game list from a text file
  generate_password_hash.py    Helper: SHA-256 a new site password / admin PIN
.github/workflows/refresh.yml  Weekly GitHub Action: fetch + commit
```

## Running it locally

```bash
pip install requests

# Serve the site (it fetches ./data/*.json relatively)
python3 -m http.server 8000        # http://localhost:8000

# Run the pipeline
python3 scripts/fetch_collections.py            # both phases
python3 scripts/fetch_collections.py --phase 1  # collections only → data/phase1_cache.json
python3 scripts/fetch_collections.py --phase 2  # names + complexity only, from the cache
```

The pipeline needs BGG credentials in a `.env` file (gitignored) or the environment:

```
BGG_USERNAME=...
BGG_PASSWORD=...
BGG_API_TOKEN=...      # bearer token for the BGG API; enables lighter rate limiting
```

## Automatic refresh

`.github/workflows/refresh.yml` runs every Sunday at 04:00 UTC (and on manual dispatch): it runs the pipeline, uploads the data files as a 90-day build artifact, and commits any changes back to `main`. It requires the same three values as repository secrets — `BGG_USERNAME`, `BGG_PASSWORD`, `BGG_API_TOKEN`. Checkout/push uses the workflow's built-in `GITHUB_TOKEN`.

## Common changes

- **Add or remove a collector** — update the `USERNAMES` list in `scripts/fetch_collections.py`, `scripts/compare_csv.py`, and `scripts/backfill_changelog.py` (all three), then run a full fetch. `index.html` reads the collector list from `collection.json` and needs no change.
- **Change the site password or admin PIN** — run `python3 scripts/generate_password_hash.py` and paste the hash into `PASSWORD_HASH` / `ADMIN_PIN_HASH` in `index.html`.
- **Set up the play challenge** — put one BGG id or game name per line in a text file and run `python3 scripts/setup_challenge.py --games games.txt`. Played dates are set in the site's admin mode and exported back into `data/challenge.json` by hand.

## Notes

- The password gate is a SHA-256 hash in a public page — it keeps the site out of search results and casual view, nothing more. Don't put anything genuinely private in the repo.
- The BGG collection API returns HTTP 202 ("queued") on a first request; the script retries automatically. It also tolerates transient network errors and BGG serving non-XML error pages, and refuses to overwrite good data if every collector fails.
- `data/collection.json` stores a thumbnail URL per game, currently unused by the UI.
