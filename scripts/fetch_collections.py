"""
fetch_collections.py

Fetches board game collections for all configured BGG usernames,
merges them by objectid, and writes data/collection.json.

Requires BGG credentials (BGG now requires login for collection API access).
Set via environment variables:
    export BGG_USERNAME=your_bgg_username
    export BGG_PASSWORD=your_bgg_password

Or create a .env file in the project root (never commit this file):
    BGG_USERNAME=your_bgg_username
    BGG_PASSWORD=your_bgg_password
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

import requests

# ── Configuration ────────────────────────────────────────────────────────────

USERNAMES = [
    "asaarto",
    "EemilVeemil",
    "EssEss",
    "jhautamaki",
    "jutapo",
    "Luonto",
    "Maradrus",
    "Marttapa",
    "Matthijsjbadmiraal",
    "okram",
    "Rauhis",
    "smartie85",
    "Stannum8",
    "StoneDog",
    "Taateli",
    "tanar",
    "Tatunen",
    "_wjr_",
    "XoDaRi",
]

BGG_LOGIN_URL = "https://boardgamegeek.com/login/api/v1"
BGG_API_URL   = "https://boardgamegeek.com/xmlapi2/collection"
OUTPUT_PATH   = Path(__file__).parent.parent / "data" / "collection.json"

RETRY_DELAY = 6
MAX_RETRIES = 10

HEADERS = {
    "User-Agent": "BGGCollectionViewer/1.0 (private hobby project)",
    "Accept":     "application/xml",
}

# ── .env loader (simple, no dependency) ──────────────────────────────────────

def load_dotenv():
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

# ── BGG authentication ────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    """
    Create a requests.Session logged in to BGG.
    Credentials are read from BGG_USERNAME / BGG_PASSWORD env vars.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    username = os.environ.get("BGG_USERNAME", "").strip()
    password = os.environ.get("BGG_PASSWORD", "").strip()

    if not username or not password:
        print("ERROR: BGG_USERNAME and BGG_PASSWORD environment variables are required.")
        print("       See the README for setup instructions.")
        sys.exit(1)

    print(f"Logging in to BGG as '{username}'…", end=" ")
    resp = session.post(
        BGG_LOGIN_URL,
        json={"credentials": {"username": username, "password": password}},
        headers={**HEADERS, "Content-Type": "application/json"},
        timeout=20,
    )

    if resp.status_code in (200, 204):  # BGG returns 204 on successful login
        print("OK")
    else:
        print(f"FAILED (HTTP {resp.status_code})")
        print("Check your BGG_USERNAME and BGG_PASSWORD and try again.")
        sys.exit(1)

    return session

# ── BGG fetching ─────────────────────────────────────────────────────────────

def fetch_collection(session: requests.Session, username: str) -> list[dict]:
    """
    Fetch owned games for a single BGG user using an authenticated session.
    Handles 202 responses (BGG queues the request server-side on first call).
    """
    params = {
        "username":        username,
        "own":             1,
        "subtype":         "boardgame",
        "excludesubtype":  "boardgameexpansion",
        "stats":           1,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"  [{username}] attempt {attempt}...", end=" ", flush=True)
        response = session.get(BGG_API_URL, params=params, timeout=30)

        if response.status_code == 202:
            print(f"queued, retrying in {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
            continue

        if response.status_code == 429:
            wait = 60 * attempt   # 60s, 120s, 180s... backs off harder each hit
            print(f"rate limited, waiting {wait}s before retry")
            time.sleep(wait)
            continue

        if response.status_code != 200:
            print(f"HTTP {response.status_code} — skipping user")
            return []

        root = ET.fromstring(response.content)

        if root.tag == "errors":
            message = root.findtext(".//message", default="unknown error")
            print(f"API error: {message} — skipping user")
            return []

        items = root.findall("item")
        print(f"OK ({len(items)} games)")
        return [parse_item(item, username) for item in items]

    print(f"gave up after {MAX_RETRIES} attempts")
    return []


def parse_item(item: ET.Element, username: str) -> dict:
    """Extract the fields we care about from a single <item> element."""

    def text(path, default=""):
        el = item.find(path)
        return el.text.strip() if el is not None and el.text else default

    def attr(path, attribute, default=""):
        el = item.find(path)
        return el.get(attribute, default).strip() if el is not None else default

    def float_attr(path, attribute, default=None):
        try:
            return round(float(attr(path, attribute)), 2)
        except (ValueError, TypeError):
            return default

    def int_attr(path, attribute, default=None):
        try:
            return int(attr(path, attribute))
        except (ValueError, TypeError):
            return default

    object_id = item.get("objectid", "")
    thumbnail_raw = text("thumbnail")
    thumbnail = f"https:{thumbnail_raw}" if thumbnail_raw.startswith("//") else thumbnail_raw

    return {
        "objectid":    object_id,
        "name":        text("name"),
        "year":        int(text("yearpublished")) if text("yearpublished").isdigit() else None,
        "minplayers":  int_attr("stats", "minplayers"),
        "maxplayers":  int_attr("stats", "maxplayers"),
        "minplaytime": int_attr("stats", "minplaytime"),
        "maxplaytime": int_attr("stats", "maxplaytime"),
        "bgg_rating":  float_attr("stats/rating/average", "value"),
        "complexity":  float_attr("stats/rating/averageweight", "value"),
        "bgg_url":     f"https://boardgamegeek.com/boardgame/{object_id}",
        "thumbnail":   thumbnail,
        "owner":       username,
    }


# ── Merging ───────────────────────────────────────────────────────────────────

def merge_collections(all_games: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}

    for game in all_games:
        oid = game["objectid"]
        if oid not in merged:
            merged[oid] = {k: game[k] for k in game if k != "owner"}
            merged[oid]["owners"] = []
            merged[oid]["owner_count"] = 0

        if game["owner"] not in merged[oid]["owners"]:
            merged[oid]["owners"].append(game["owner"])

    for record in merged.values():
        record["owners"].sort()
        record["owner_count"] = len(record["owners"])

    return sorted(merged.values(), key=lambda g: g["name"].lower())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    load_dotenv()
    session = make_session()

    print(f"\nFetching collections for {len(USERNAMES)} users…\n")

    all_games    = []
    failed_users = []

    for username in USERNAMES:
        games = fetch_collection(session, username)
        if games:
            all_games.extend(games)
        else:
            failed_users.append(username)
        time.sleep(15)

    print(f"\nFetched {len(all_games)} ownership records.")

    merged = merge_collections(all_games)
    print(f"Merged into {len(merged)} unique games.")

    output = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "users":         USERNAMES,
            "failed_users":  failed_users,
            "game_count":    len(merged),
        },
        "games": merged,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✓ Wrote {OUTPUT_PATH}")

    if failed_users:
        print(f"\n⚠️  Failed users: {', '.join(failed_users)}")


if __name__ == "__main__":
    main()
