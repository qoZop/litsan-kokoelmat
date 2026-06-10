"""
setup_challenge.py

Initialise data/challenge.json from a list of games.

Usage:
    python3 scripts/setup_challenge.py --games games.txt

Input file format (one game per line — BGG object ID or game name):
    174430
    Gloomhaven
    7 Wonders Duel
    312484

BGG IDs are used directly. Names are matched against collection.json.
Any existing played_date values in challenge.json are preserved.
"""

import argparse
import json
from pathlib import Path

COLLECTION_PATH = Path(__file__).parent.parent / "data" / "collection.json"
CHALLENGE_PATH  = Path(__file__).parent.parent / "data" / "challenge.json"


def load_collection() -> list[dict]:
    if not COLLECTION_PATH.exists():
        print(f"ERROR: {COLLECTION_PATH} not found. Run fetch_collections.py first.")
        raise SystemExit(1)
    return json.loads(COLLECTION_PATH.read_text())["games"]


def match_game(query: str, collection: list[dict]) -> dict | None:
    query = query.strip()
    if not query or query.startswith("#"):
        return None

    # Pure numeric → treat as BGG object ID
    if query.isdigit():
        for game in collection:
            if game["objectid"] == query:
                return game
        # ID not in collection — create a stub (game may have been sold)
        return {"objectid": query, "name": f"[Unknown — ID {query}]"}

    # Exact name match (case-insensitive)
    ql = query.lower()
    for game in collection:
        if game["name"].lower() == ql:
            return game

    # Partial match — only accept if exactly one result
    partial = [g for g in collection if ql in g["name"].lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        print(f"  AMBIGUOUS '{query}': {[g['name'] for g in partial[:4]]}")
        return None

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", required=True, help="Text file with one game ID or name per line")
    args = parser.parse_args()

    games_path = Path(args.games)
    if not games_path.exists():
        print(f"ERROR: File not found: {games_path}")
        raise SystemExit(1)

    collection = load_collection()
    lines      = [l.strip() for l in games_path.read_text(encoding="utf-8-sig").splitlines()]

    # Load existing challenge.json to preserve played_dates
    existing_played = {}
    if CHALLENGE_PATH.exists():
        existing = json.loads(CHALLENGE_PATH.read_text())
        for g in existing.get("games", []):
            if g.get("played_date"):
                existing_played[g["objectid"]] = g["played_date"]

    games     = []
    matched   = 0
    unmatched = []

    for line in lines:
        if not line or line.startswith("#"):
            continue
        result = match_game(line, collection)
        if result:
            games.append({
                "objectid":   result["objectid"],
                "name":       result["name"],
                "played_date": existing_played.get(result["objectid"], None),
            })
            matched += 1
        else:
            print(f"  NO MATCH: '{line}'")
            unmatched.append(line)

    print(f"\nMatched {matched} games, {len(unmatched)} unmatched.")

    # Load existing challenge.json to keep metadata
    if CHALLENGE_PATH.exists():
        challenge = json.loads(CHALLENGE_PATH.read_text())
    else:
        challenge = {
            "year": 2026, "title": "Satunnaishaaste 2026",
            "target": 201, "tiers": {"bronze": 75, "silver": 100, "gold": 125},
        }

    challenge["games"] = games
    CHALLENGE_PATH.write_text(json.dumps(challenge, ensure_ascii=False, indent=2))
    print(f"✓ Wrote {CHALLENGE_PATH} with {len(games)} games.")

    if existing_played:
        preserved = sum(1 for g in games if g["played_date"])
        print(f"  Preserved {preserved} existing played dates.")

    if unmatched:
        print(f"\nUnmatched games (add manually or check spelling):")
        for u in unmatched:
            print(f"  - {u}")


if __name__ == "__main__":
    main()
