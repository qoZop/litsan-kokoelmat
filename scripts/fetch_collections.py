"""
fetch_collections.py

Phase 1: Fetch owned games for all collectors via the collection API.
         Saves intermediate results to data/phase1_cache.json.

Phase 2: Batch-fetch canonical names + complexity via the thing API.
         Reads phase1_cache.json, writes final data/collection.json.

Usage:
    python3 scripts/fetch_collections.py            # run both phases
    python3 scripts/fetch_collections.py --phase 1  # Phase 1 only
    python3 scripts/fetch_collections.py --phase 2  # Phase 2 only (uses cache)

Requires BGG credentials in .env or environment:
    BGG_USERNAME=okram
    BGG_PASSWORD=your_password
"""

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

USERNAMES = [
    "asaarto", "EemilVeemil", "EssEss", "jhautamaki", "jutapo",
    "Luonto", "Maradrus", "Marttapa", "Matthijsjbadmiraal", "okram",
    "Rauhis", "smartie85", "Stannum8", "StoneDog", "Taateli",
    "tanar", "Tatunen", "_wjr_", "XoDaRi",
]

BGG_LOGIN_URL      = "https://boardgamegeek.com/login/api/v1"
BGG_COLLECTION_URL = "https://boardgamegeek.com/xmlapi2/collection"
BGG_THING_URL      = "https://boardgamegeek.com/xmlapi/boardgame"
OUTPUT_PATH        = Path(__file__).parent.parent / "data" / "collection.json"
CACHE_PATH         = Path(__file__).parent.parent / "data" / "phase1_cache.json"
CHANGELOG_PATH     = Path(__file__).parent.parent / "data" / "changelog.json"

RETRY_DELAY = 6
MAX_RETRIES = 10
THING_BATCH = 150

HEADERS = {
    "User-Agent": "BGGCollectionViewer/1.0 (private hobby project)",
    "Accept":     "application/xml",
}

# ── .env loader ────────────────────────────────────────────────────────────────

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

# ── Authentication ─────────────────────────────────────────────────────────────

def login(session: requests.Session) -> bool:
    """Log in to BGG. Returns True on success."""
    username = os.environ.get("BGG_USERNAME", "").strip()
    password = os.environ.get("BGG_PASSWORD", "").strip()

    if not username or not password:
        print("ERROR: BGG_USERNAME and BGG_PASSWORD are required.")
        sys.exit(1)

    print(f"Logging in to BGG as '{username}'…", end=" ", flush=True)
    resp = session.post(
        BGG_LOGIN_URL,
        json={"credentials": {"username": username, "password": password}},
        headers={**HEADERS, "Content-Type": "application/json"},
        timeout=20,
    )
    if resp.status_code in (200, 204):
        print("OK")
        return True
    print(f"FAILED (HTTP {resp.status_code})")
    return False


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    if not login(session):
        sys.exit(1)
    return session

# ── Phase 1: Collection fetch ──────────────────────────────────────────────────

def fetch_collection(session: requests.Session, username: str) -> list[dict]:
    params = {
        "username":       username,
        "own":            1,
        "subtype":        "boardgame",
        "excludesubtype": "boardgameexpansion",
        "stats":          1,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"  [{username}] attempt {attempt}...", end=" ", flush=True)
        resp = session.get(BGG_COLLECTION_URL, params=params, timeout=30)

        if resp.status_code == 202:
            print(f"queued, retrying in {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
            continue
        if resp.status_code == 429:
            wait = 60 * attempt
            print(f"rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code} — skipping")
            return []

        root = ET.fromstring(resp.content)
        if root.tag == "errors":
            print(f"API error: {root.findtext('.//message', 'unknown')} — skipping")
            return []

        items = root.findall("item")
        print(f"OK ({len(items)} games)")
        return [parse_collection_item(item, username) for item in items]

    print(f"gave up after {MAX_RETRIES} attempts")
    return []


def parse_collection_item(item: ET.Element, username: str) -> dict:
    def text(path):
        el = item.find(path)
        return (el.text or "").strip() if el is not None else ""

    def int_attr(path, attr):
        el = item.find(path)
        try:
            return int(el.get(attr, ""))
        except (ValueError, TypeError, AttributeError):
            return None

    def float_attr(path, attr):
        el = item.find(path)
        try:
            return round(float(el.get(attr, "")), 2)
        except (ValueError, TypeError, AttributeError):
            return None

    object_id     = item.get("objectid", "")
    thumbnail_raw = text("thumbnail")
    thumbnail     = f"https:{thumbnail_raw}" if thumbnail_raw.startswith("//") else thumbnail_raw
    year_text     = text("yearpublished")

    return {
        "objectid":    object_id,
        "name":        text("name"),
        "year":        int(year_text) if year_text.lstrip("-").isdigit() else None,
        "minplayers":  int_attr("stats", "minplayers"),
        "maxplayers":  int_attr("stats", "maxplayers"),
        "minplaytime": int_attr("stats", "minplaytime"),
        "maxplaytime": int_attr("stats", "maxplaytime"),
        "bgg_rating":  float_attr("stats/rating/average", "value"),
        "complexity":  None,
        "bgg_url":     f"https://boardgamegeek.com/boardgame/{object_id}",
        "thumbnail":   thumbnail,
        "owner":       username,
    }


def is_ascii(name: str) -> bool:
    try:
        name.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def merge_collections(all_games: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}

    for game in all_games:
        oid = game["objectid"]
        if oid not in merged:
            merged[oid] = {k: game[k] for k in game if k != "owner"}
            merged[oid]["owners"]      = []
            merged[oid]["owner_count"] = 0
        else:
            # Prefer ASCII/English name as a fallback heuristic;
            # Phase 2 will override with the definitive canonical name.
            if not is_ascii(merged[oid]["name"]) and is_ascii(game["name"]):
                merged[oid]["name"] = game["name"]

        if game["owner"] not in merged[oid]["owners"]:
            merged[oid]["owners"].append(game["owner"])

    for record in merged.values():
        record["owners"].sort()
        record["owner_count"] = len(record["owners"])

    return sorted(merged.values(), key=lambda g: g["name"].lower())


def run_phase1(session: requests.Session) -> list[dict]:
    print(f"\nPhase 1: Fetching collections for {len(USERNAMES)} users…\n")
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

    # Save cache so Phase 2 can be run independently later
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({
        "failed_users": failed_users,
        "games": merged,
    }, ensure_ascii=False, indent=2))
    print(f"✓ Phase 1 cache saved to {CACHE_PATH.name}")

    return merged, failed_users

# ── Phase 2: Canonical names + complexity ─────────────────────────────────────

def fetch_game_details(session: requests.Session, object_ids: list[str]) -> dict[str, dict]:
    """
    Fetch canonical (primary) name and complexity via BGG XML API v1.
    Requires the authenticated session (BGG requires login for all XML API calls).

    URL format: /xmlapi/boardgame/ID1,ID2,...?stats=1
    v1 XML uses text content (not value attributes) and <boardgame> elements.
    Returns {objectid: {"name": str, "complexity": float|None}}.
    """
    # Add browser-like headers to the existing authenticated session
    session.headers.update({
        "Accept": "application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://boardgamegeek.com/",
    })

    results = {}
    batches = [object_ids[i:i + THING_BATCH] for i in range(0, len(object_ids), THING_BATCH)]
    total   = len(batches)

    print(f"\nPhase 2: Canonical names + complexity for {len(object_ids)} games in {total} batches…")

    for idx, batch in enumerate(batches, 1):
        print(f"  Batch {idx}/{total}…", end=" ", flush=True)
        ids_str = ",".join(batch)
        url     = f"{BGG_THING_URL}/{ids_str}"

        for attempt in range(1, MAX_RETRIES + 1):
            resp = session.get(url, params={"stats": 1}, timeout=60)

            if resp.status_code == 429:
                wait = 60 * attempt
                print(f"rate limited, waiting {wait}s", end=" ", flush=True)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                snippet = resp.text[:300].replace("\n", " ").strip()
                print(f"HTTP {resp.status_code} — {snippet}")
                break

            root = ET.fromstring(resp.content)
            # v1 uses <boardgame objectid="X"> elements under <boardgames>
            for game in root.findall("boardgame"):
                oid = game.get("objectid", "")

                # Primary name: <name primary="true">Game Name</name>
                name = ""
                for name_el in game.findall("name"):
                    if name_el.get("primary") == "true":
                        name = (name_el.text or "").strip()
                        break

                # Weight: <statistics><ratings><averageweight>3.5</averageweight></ratings></statistics>
                # v1 uses text content, not value attributes
                complexity = None
                w_el = game.find("statistics/ratings/averageweight")
                if w_el is not None and w_el.text:
                    try:
                        val = float(w_el.text.strip())
                        if val > 0:
                            complexity = round(val, 2)
                    except (ValueError, TypeError):
                        pass

                if name or complexity is not None:
                    results[oid] = {"name": name, "complexity": complexity}

            print(f"OK ({len(results)} matched so far)")
            break

        time.sleep(4)

    return results


# ── Changelog ──────────────────────────────────────────────────────────────────

def build_ownership_map(games: list[dict]) -> dict[str, set]:
    """Build {collector: set of objectids} from a games list."""
    own = {u: set() for u in USERNAMES}
    for game in games:
        for owner in game.get("owners", []):
            if owner in own:
                own[owner].add(game["objectid"])
    return own


def compute_changes(old_own: dict, new_own: dict, old_names: dict, new_names: dict) -> list[dict]:
    """Return per-collector change records, only for collectors with actual changes."""
    changes = []
    for collector in USERNAMES:
        added_ids   = new_own.get(collector, set()) - old_own.get(collector, set())
        removed_ids = old_own.get(collector, set()) - new_own.get(collector, set())
        if not added_ids and not removed_ids:
            continue

        def record(oid, primary, fallback):
            return {"objectid": oid, "name": primary.get(oid) or fallback.get(oid) or f"ID {oid}"}

        changes.append({
            "collector": collector,
            "added":   sorted([record(o, new_names, old_names) for o in added_ids],   key=lambda g: g["name"].lower()),
            "removed": sorted([record(o, old_names, new_names) for o in removed_ids], key=lambda g: g["name"].lower()),
        })
    return changes


def append_changelog_entry(entry: dict):
    if CHANGELOG_PATH.exists():
        data = json.loads(CHANGELOG_PATH.read_text())
    else:
        data = {"entries": []}
    data["entries"].insert(0, entry)
    CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHANGELOG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))



def run_phase2(session: requests.Session, merged: list[dict], failed_users: list[str]):
    object_ids   = [g["objectid"] for g in merged]
    game_details = fetch_game_details(session, object_ids)

    name_fixes  = 0
    weight_hits = 0
    for game in merged:
        detail = game_details.get(game["objectid"])
        if not detail:
            continue
        if detail["name"] and detail["name"] != game["name"]:
            game["name"]  = detail["name"]
            name_fixes   += 1
        if detail["complexity"] is not None:
            game["complexity"] = detail["complexity"]
            weight_hits += 1

    print(f"Phase 2 applied: {name_fixes} name corrections, {weight_hits} complexity values.")

    merged.sort(key=lambda g: g["name"].lower())

    output = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "users":         USERNAMES,
            "failed_users":  failed_users,
            "game_count":    len(merged),
        },
        "games": merged,
    }

    # ── Changelog detection ──
    if OUTPUT_PATH.exists():
        old_data   = json.loads(OUTPUT_PATH.read_text())
        old_names  = {g["objectid"]: g["name"] for g in old_data["games"]}
        new_names  = {g["objectid"]: g["name"] for g in merged}
        old_own    = build_ownership_map(old_data["games"])
        new_own    = build_ownership_map(merged)
        changes    = compute_changes(old_own, new_own, old_names, new_names)

        if changes:
            total_added   = sum(len(c["added"])   for c in changes)
            total_removed = sum(len(c["removed"]) for c in changes)
            entry = {
                "id":     datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-refresh",
                "date":   datetime.now(timezone.utc).isoformat(),
                "label":  f"Weekly refresh — {datetime.now(timezone.utc).strftime('%d %b %Y')}",
                "source": "refresh",
                "stats":  {"collectors_changed": len(changes), "games_added": total_added, "games_removed": total_removed},
                "changes": changes,
            }
            append_changelog_entry(entry)
            print(f"Changelog: {len(changes)} collectors changed (+{total_added}/−{total_removed} games).")
        else:
            print("Changelog: no ownership changes detected.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✓ Wrote {OUTPUT_PATH}")

    if failed_users:
        print(f"\n⚠️  Failed users: {', '.join(failed_users)}")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Fetch BGG collections")
    parser.add_argument(
        "--phase", choices=["1", "2", "all"], default="all",
        help="Which phase to run: 1=collections only, 2=names+complexity only (uses cache), all=both (default)"
    )
    args = parser.parse_args()

    session = make_session()

    if args.phase in ("1", "all"):
        merged, failed_users = run_phase1(session)

    if args.phase == "2":
        if CACHE_PATH.exists():
            cache        = json.loads(CACHE_PATH.read_text())
            merged       = cache["games"]
            failed_users = cache.get("failed_users", [])
            print(f"Loaded {len(merged)} games from Phase 1 cache.")
        elif OUTPUT_PATH.exists():
            # No cache yet — fall back to existing collection.json
            existing     = json.loads(OUTPUT_PATH.read_text())
            merged       = existing["games"]
            failed_users = existing["meta"].get("failed_users", [])
            print(f"No cache found — loaded {len(merged)} games from existing collection.json.")
        else:
            print("ERROR: No Phase 1 cache or collection.json found. Run Phase 1 first.")
            sys.exit(1)

    if args.phase in ("2", "all"):
        run_phase2(session, merged, failed_users)


if __name__ == "__main__":
    main()
