#!/usr/bin/env python3
"""Snapshot the public Apple Podcasts star rating and rating count of each show.

For every show in the latest guest dataset, downloads its public Apple
Podcasts page (collection id from config/popular_show_feeds.csv), keeps the
raw HTML, and reads the schema.org aggregateRating (ratingValue, reviewCount).
Show-level only: Apple publishes no per-episode audience numbers. Free.

    python code/23_snapshot_apple_ratings.py          # show the plan
    python code/23_snapshot_apple_ratings.py --yes    # download

Output: data/raw/audience_metrics/apple_ratings/<UTC timestamp>/<show_id>.html, ratings.csv, manifest.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEEDS = ROOT / "config/popular_show_feeds.csv"
GUESTS = ROOT / "data/derived/guest_dataset"
OUTPUT_ROOT = ROOT / "data/raw/audience_metrics/apple_ratings"
USER_AGENT = "Mozilla/5.0 (academic research; podcast_observational)"
RATING = re.compile(r'"aggregateRating"\s*:\s*\{[^}]*?"ratingValue"\s*:\s*([0-9.]+)[^}]*?"reviewCount"\s*:\s*(\d+)')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="download (otherwise only print the plan)")
    args = parser.parse_args()

    dataset = sorted(path.parent for path in GUESTS.glob("*/shows.csv"))[-1]
    with (dataset / "shows.csv").open(newline="", encoding="utf-8") as handle:
        show_ids = [row["show_id"] for row in csv.DictReader(handle)]
    with FEEDS.open(newline="", encoding="utf-8") as handle:
        apple = {row["show_id"]: row["apple_collection_id"] for row in csv.DictReader(handle)}
    print(f"{len(show_ids)} shows from {dataset.relative_to(ROOT)}")
    if not args.yes:
        print("Plan only. Add --yes to download the public Apple Podcasts pages (free).")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = OUTPUT_ROOT / stamp
    snapshot.mkdir(parents=True, exist_ok=False)
    rows, records = [], []
    for show_id in show_ids:
        url = f"https://podcasts.apple.com/us/podcast/id{apple[show_id]}"
        record = {"show_id": show_id, "apple_collection_id": apple[show_id], "url": url}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read()
            with (snapshot / f"{show_id}.html").open("xb") as handle:
                handle.write(content)
            match = RATING.search(content.decode("utf-8", errors="replace"))
            record.update(status="ok" if match else "no_rating_found", sha256=hashlib.sha256(content).hexdigest(),
                          accessed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            rows.append({"show_id": show_id, "apple_rating": match.group(1) if match else "",
                         "apple_rating_count": match.group(2) if match else "", "accessed_at": record["accessed_at"]})
        except Exception as error:
            record["status"] = f"error: {error}"[:300]
            rows.append({"show_id": show_id, "apple_rating": "", "apple_rating_count": "", "accessed_at": ""})
        records.append(record)
        print(f"  {show_id[:45]:45} {record['status'][:30]:30} {rows[-1]['apple_rating']} {rows[-1]['apple_rating_count']}")
        time.sleep(2)
    with (snapshot / "ratings.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (snapshot / "manifest.json").write_text(json.dumps({
        "schema_version": "0.1", "snapshot": stamp, "user_agent": USER_AGENT,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "pages": records,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {snapshot.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
