"""
compare_csv.py

One-off comparison of a legacy Google Sheets CSV export against the
current collection.json. Appends an entry to data/changelog.json.

Usage:
    python3 scripts/compare_csv.py --csv path/to/export.csv
    python3 scripts/compare_csv.py --csv path/to/export.csv --label "Dec 2024 snapshot"

The CSV is expected to have:
  - 'objectid'     — BGG object ID
  - 'originalname' — game name
  - One column per collector username containing 'x' for owned games
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

USERNAMES = [
    "asaarto", "EemilVeemil", "EssEss", "jhautamaki", "jutapo",
    "Luonto", "Maradrus", "Marttapa", "Matthijsjbadmiraal", "okram",
    "Rauhis", "smartie85", "Stannum8", "StoneDog", "Taateli",
    "tanar", "Tatunen", "_wjr_", "XoDaRi",
]

COLLECTION_PATH = Path(__file__).parent.parent / "data" / "collection.json"
CHANGELOG_PATH  = Path(__file__).parent.parent / "data" / "changelog.json"


def load_csv_ownerships(csv_path: Path):
    """
    Parse the Google Sheets CSV export.
    Returns:
        ownerships: {collector: set of objectids}
        names:      {objectid: game name}
    """
    ownerships = {u: set() for u in USERNAMES}
    names      = {}

    username_lookup = {u.lower(): u for u in USERNAMES}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader      = csv.DictReader(f)
        headers     = reader.fieldnames or []

        # Map CSV column → canonical username
        collector_cols = {
            h: username_lookup[h.lower()]
            for h in headers
            if h.lower() in username_lookup
        }

        if not collector_cols:
            print(f"WARNING: No collector columns found in CSV.")
            print(f"  Headers found: {headers}")
            print(f"  Expected columns matching: {USERNAMES}")

        for row in reader:
            oid  = row.get("objectid", "").strip()
            if not oid:
                continue

            name = row.get("originalname", "").strip()
            if name:
                names[oid] = name

            for col, username in collector_cols.items():
                if row.get(col, "").strip().lower() in ("x", "1", "true", "yes"):
                    ownerships[username].add(oid)

    return ownerships, names


def load_json_ownerships(json_path: Path):
    """
    Parse collection.json.
    Returns:
        ownerships: {collector: set of objectids}
        names:      {objectid: game name}
    """
    data       = json.loads(json_path.read_text())
    ownerships = {u: set() for u in USERNAMES}
    names      = {}

    for game in data["games"]:
        oid        = game["objectid"]
        names[oid] = game["name"]
        for owner in game["owners"]:
            if owner in ownerships:
                ownerships[owner].add(oid)

    return ownerships, names


def compute_changes(old_own, new_own, old_names, new_names):
    """
    Compare two ownership maps collector by collector.
    Returns list of change dicts, only for collectors with actual changes.
    """
    changes = []

    for collector in USERNAMES:
        old_ids = old_own.get(collector, set())
        new_ids = new_own.get(collector, set())

        added_ids   = new_ids - old_ids
        removed_ids = old_ids - new_ids

        if not added_ids and not removed_ids:
            continue

        def game_record(oid, primary_names, fallback_names):
            return {
                "objectid": oid,
                "name": primary_names.get(oid) or fallback_names.get(oid) or f"ID {oid}",
            }

        added   = sorted(
            [game_record(oid, new_names, old_names) for oid in added_ids],
            key=lambda g: g["name"].lower()
        )
        removed = sorted(
            [game_record(oid, old_names, new_names) for oid in removed_ids],
            key=lambda g: g["name"].lower()
        )

        changes.append({
            "collector": collector,
            "added":     added,
            "removed":   removed,
        })

    return changes


def append_changelog_entry(entry: dict):
    """Load changelog.json (or start fresh), append entry, save."""
    if CHANGELOG_PATH.exists():
        data = json.loads(CHANGELOG_PATH.read_text())
    else:
        data = {"entries": []}

    data["entries"].insert(0, entry)   # newest first

    CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHANGELOG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"✓ Appended entry to {CHANGELOG_PATH.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",   required=True, help="Path to Google Sheets CSV export")
    parser.add_argument("--label", default="",    help="Human-readable label for this comparison")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        return

    if not COLLECTION_PATH.exists():
        print(f"ERROR: collection.json not found at {COLLECTION_PATH}")
        return

    print(f"Loading CSV from {csv_path.name}…")
    old_own, old_names = load_csv_ownerships(csv_path)

    print(f"Loading current collection.json…")
    new_own, new_names = load_json_ownerships(COLLECTION_PATH)

    # Summary of what we loaded
    csv_total  = sum(len(s) for s in old_own.values())
    json_total = sum(len(s) for s in new_own.values())
    print(f"  CSV:  {csv_total} ownership records across {sum(1 for s in old_own.values() if s)} collectors")
    print(f"  JSON: {json_total} ownership records across {sum(1 for s in new_own.values() if s)} collectors")

    print("\nComputing changes…")
    changes = compute_changes(old_own, new_own, old_names, new_names)

    if not changes:
        print("No changes found between CSV and collection.json.")
        return

    total_added   = sum(len(c["added"])   for c in changes)
    total_removed = sum(len(c["removed"]) for c in changes)

    print(f"\nFound changes in {len(changes)} collectors:")
    for c in changes:
        print(f"  {c['collector']:20s}  +{len(c['added'])} added, -{len(c['removed'])} removed")

    label = args.label or f"Historical: vs. Google Sheets export ({csv_path.stem})"

    entry = {
        "id":     datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-csv",
        "date":   datetime.now(timezone.utc).isoformat(),
        "label":  label,
        "source": "csv",
        "stats": {
            "collectors_changed": len(changes),
            "games_added":        total_added,
            "games_removed":      total_removed,
        },
        "changes": changes,
    }

    append_changelog_entry(entry)
    print(f"\nSummary: {len(changes)} collectors changed, +{total_added} added, -{total_removed} removed")


if __name__ == "__main__":
    main()
