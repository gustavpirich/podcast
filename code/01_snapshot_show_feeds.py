#!/usr/bin/env python3
"""Download the RSS feed of every show in config/popular_show_feeds.csv.

Each feed is saved unchanged as a new raw file; nothing existing is
overwritten. Episode selection and category filtering happen later, in
01_build_popular_episode_frame.py, using only these frozen files. Free.

    python code/01_snapshot_show_feeds.py          # show the plan
    python code/01_snapshot_show_feeds.py --yes    # download

Output: data/raw/rss/<show_id>/<show_id>_rss_<UTC timestamp>.xml
        data/raw/rss/snapshots/<UTC timestamp>.json (manifest)
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
RSS_ROOT = ROOT / "data/raw/rss"
USER_AGENT = "podcast-observational-research/0.1"
SHOW_ID = re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")


def read_feeds() -> list[dict[str, str]]:
    with FEEDS.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["feed_url"]]
    ids = [row["show_id"] for row in rows]
    if len(ids) != len(set(ids)) or not all(SHOW_ID.match(value) for value in ids):
        raise SystemExit("show_id values must be unique lowercase identifiers")
    return rows


def fetch(url: str) -> tuple[bytes, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read(), response.geturl(), response.headers.get("Content-Type", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="download (otherwise only print the plan)")
    args = parser.parse_args()

    feeds = read_feeds()
    print(f"{len(feeds)} feeds in {FEEDS.relative_to(ROOT)}")
    if not args.yes:
        for row in feeds:
            print(f"  {row['show_id']:40} {row['feed_url']}")
        print("Plan only. Add --yes to download (public RSS feeds; free).")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = RSS_ROOT / "snapshots" / f"{stamp}.json"
    manifest = {
        "schema_version": "0.1", "snapshot": stamp,
        "feeds_config_sha256": hashlib.sha256(FEEDS.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "user_agent": USER_AGENT, "feeds": [],
    }
    failures = 0
    for number, row in enumerate(feeds, start=1):
        record = {"show": row["show"], "show_id": row["show_id"], "feed_url": row["feed_url"]}
        path = RSS_ROOT / row["show_id"] / f"{row['show_id']}_rss_{stamp}.xml"
        try:
            content, final_url, content_type = fetch(row["feed_url"])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:  # never overwrite
                handle.write(content)
            record.update(
                status="ok", final_url=final_url, content_type=content_type,
                accessed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                file=str(path.relative_to(ROOT)), bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        except Exception as error:
            record["status"] = f"error: {type(error).__name__}: {error}"
            failures += 1
        manifest["feeds"].append(record)
        size = f"{record.get('bytes', 0) / 1e6:6.1f} MB" if "bytes" in record else "       -"
        print(f"  [{number:3d}/{len(feeds)}] {record['status'][:30]:30} {size} {row['show']}")
        time.sleep(1)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print(f"\nWrote {manifest_path.relative_to(ROOT)} ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
