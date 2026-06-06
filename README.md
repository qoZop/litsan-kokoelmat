# BGG Collection Viewer

A private webapp for browsing a shared board game collection across a group of BGG users.
Hosted on GitHub Pages, data refreshed automatically via GitHub Actions.

## Setup

### 1. Create the repository

```bash
git init bgg-collection
cd bgg-collection
# copy these files in, then:
git add .
git commit -m "initial commit"
```

Push to a GitHub repository. Enable GitHub Pages in **Settings → Pages → Source: Deploy from branch → main → / (root)**.

### 2. Change the password

Run the helper script and copy the hash into `index.html`:

```bash
python scripts/generate_password_hash.py
```

Open `index.html` and replace the value of `PASSWORD_HASH` near the top of the `<script>` block.

### 3. First data fetch

Either run the script locally:

```bash
pip install requests
python scripts/fetch_collections.py
git add data/collection.json
git commit -m "initial data"
git push
```

Or trigger it manually from **GitHub Actions → Refresh BGG Collections → Run workflow**.

### 4. Automatic refresh

The GitHub Action runs every Sunday at 04:00 UTC and commits updated data automatically.
You can also trigger it any time from the Actions tab.

## Project structure

```
├── index.html                       ← The webapp (served by GitHub Pages)
├── data/
│   └── collection.json              ← Auto-generated; do not edit manually
├── scripts/
│   ├── fetch_collections.py         ← BGG data fetcher
│   └── generate_password_hash.py    ← Helper to generate a new password hash
└── .github/
    └── workflows/
        └── refresh.yml              ← Weekly GitHub Action
```

## Adding or removing collectors

Edit the `USERNAMES` list in `scripts/fetch_collections.py`, then run a fresh fetch.

## Notes

- The password gate is client-side only (SHA-256 hash in JS). Sufficient to keep
  the site off casual search results; not a security barrier against determined visitors.
- BGG's collection API occasionally returns HTTP 202 ("request queued") on first call.
  The script retries automatically with a short delay.
- Thumbnails are stored in the JSON but not displayed by default (2000+ images = slow).
  They're available for a future hover/modal feature.
