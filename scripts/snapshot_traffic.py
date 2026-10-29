"""Snapshot the GitHub traffic API (rolling 14-day window) so history isn't lost.

Run any time:  py -3 scripts/snapshot_traffic.py
Needs gh authenticated for juzorei/game-re-skills. Output: .traffic/<date>.json.
"""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path

REPO = "juzorei/game-re-skills"
OUT = Path(__file__).resolve().parent.parent / ".traffic"


def gh(path: str) -> dict:
    url = f"repos/{REPO}" + (f"/{path}" if path else "")
    out = subprocess.check_output(["gh", "api", url])
    return json.loads(out)


def main() -> int:
    today = datetime.date.today().isoformat()
    data = {
        "date": today,
        "repo": REPO,
        "clones": {k: v for k, v in gh("traffic/clones").items() if k != "clones"},
        "views": {k: v for k, v in gh("traffic/views").items() if k != "views"},
        "daily_clones": gh("traffic/clones")["clones"],
        "daily_views": gh("traffic/views")["views"],
        "stars": gh("")["stargazers_count"],
    }
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{today}.json"
    path.write_text(json.dumps(data, indent=2) + "\n")

    history = []
    for old in sorted(OUT.glob("*.json")):
        d = json.loads(old.read_text())
        history.append((d["date"], d["clones"]["count"], d["clones"]["uniques"],
                        d["views"]["count"], d["views"]["uniques"], d["stars"]))
    print(f"{'date':<12}{'clones':>8}{'uniq':>6}{'views':>7}{'uniq':>6}{'stars':>7}")
    for row in history:
        print(f"{row[0]:<12}{row[1]:>8}{row[2]:>6}{row[3]:>7}{row[4]:>6}{row[5]:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
