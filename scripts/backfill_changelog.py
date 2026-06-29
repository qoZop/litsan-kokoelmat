import subprocess
import json
from datetime import datetime


def git_show_json(commit_hash, path):
    result = subprocess.run(
        ["git", "show", f"{commit_hash}:{path}"],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def get_commits(n=5):
    result = subprocess.run(
        ["git", "log", f"-{n}", "--format=%H %aI", "--", "data/collection.json"],
        capture_output=True, text=True, check=True
    )
    commits = []
    for line in result.stdout.strip().splitlines():
        if line:
            h, date = line.split(" ", 1)
            commits.append({"hash": h, "date": date})
    return commits  # newest first


def build_ownership(collection):
    ownership = {}
    for game in collection["games"]:
        ownership[game["objectid"]] = {
            "name": game["name"],
            "owners": set(game.get("owners", [])),
        }
    return ownership


def diff_ownership(old_ownership, new_ownership):
    all_collectors = set()
    for g in old_ownership.values():
        all_collectors.update(g["owners"])
    for g in new_ownership.values():
        all_collectors.update(g["owners"])

    changes = {}
    for collector in sorted(all_collectors):
        added, removed = [], []

        for oid, new_info in new_ownership.items():
            if collector in new_info["owners"]:
                old_info = old_ownership.get(oid)
                if old_info is None or collector not in old_info["owners"]:
                    added.append({"objectid": oid, "name": new_info["name"]})

        for oid, old_info in old_ownership.items():
            if collector in old_info["owners"]:
                new_info = new_ownership.get(oid)
                if new_info is None or collector not in new_info["owners"]:
                    removed.append({"objectid": oid, "name": old_info["name"]})

        added.sort(key=lambda x: x["name"])
        removed.sort(key=lambda x: x["name"])

        if added or removed:
            changes[collector] = {"added": added, "removed": removed}

    return changes


def format_label(date_str):
    dt = datetime.fromisoformat(date_str)
    return f"Weekly refresh — {dt.strftime('%-d %b %Y')}"


commits = get_commits(5)
print(f"Last {len(commits)} commits touching data/collection.json:")
for c in commits:
    print(f"  {c['hash'][:8]}  {c['date']}")

changelog_path = "data/changelog.json"
with open(changelog_path) as f:
    changelog = json.load(f)

existing_ids = {e["id"] for e in changelog["entries"]}
new_entries = []

for i in range(len(commits) - 1):
    newer = commits[i]
    older = commits[i + 1]
    entry_id = f"{newer['hash'][:8]}-refresh"

    print(f"\n--- {older['hash'][:8]} → {newer['hash'][:8]}  ({newer['date'][:10]}) ---")

    if entry_id in existing_ids:
        print("  Already in changelog, skipping.")
        continue

    old_data = git_show_json(older["hash"], "data/collection.json")
    new_data = git_show_json(newer["hash"], "data/collection.json")

    changes = diff_ownership(build_ownership(old_data), build_ownership(new_data))

    if not changes:
        print("  No ownership changes.")
        continue

    total_added = sum(len(v["added"]) for v in changes.values())
    total_removed = sum(len(v["removed"]) for v in changes.values())
    print(f"  {len(changes)} collector(s) changed — +{total_added} added, -{total_removed} removed")

    for collector, delta in changes.items():
        if delta["added"]:
            names = ", ".join(g["name"] for g in delta["added"])
            print(f"    {collector}  +{len(delta['added'])}: {names}")
        if delta["removed"]:
            names = ", ".join(g["name"] for g in delta["removed"])
            print(f"    {collector}  -{len(delta['removed'])}: {names}")

    new_entries.append({
        "id": entry_id,
        "date": newer["date"],
        "label": format_label(newer["date"]),
        "source": "refresh",
        "stats": {
            "collectors_changed": len(changes),
            "games_added": total_added,
            "games_removed": total_removed,
        },
        "changes": [
            {"collector": c, "added": v["added"], "removed": v["removed"]}
            for c, v in changes.items()
        ],
    })

if new_entries:
    changelog["entries"] = new_entries + changelog["entries"]
    with open(changelog_path, "w") as f:
        json.dump(changelog, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nAppended {len(new_entries)} new entry/entries to changelog.json.")
else:
    print("\nNo new entries to add.")
