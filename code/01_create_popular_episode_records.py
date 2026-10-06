#!/usr/bin/env python3
"""Create raw episode records and transcription samples for the popular frame.

For every episode selected by 01_build_popular_episode_frame.py, writes the
same metadata-only raw record the JRE archive uses
(data/raw/transcripts/<show folder>/<episode_id>/rss_metadata.json) and one
frozen sample file per show (config/popular_frame/<show_id>.json) that
02_transcribe_assemblyai_batch.py can run with --delivery rss-direct.

Existing episode folders are reused when their RSS GUID matches, so episodes
already transcribed (JRE, DOAC) are not transcribed again. Raw files are
never overwritten. Speaker naming follows the 2026-10-02 decision: hosts by
name from config/podcasts.json, every other voice labelled "Guest".

    python code/01_create_popular_episode_records.py          # plan only
    python code/01_create_popular_episode_records.py --yes    # write records
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import runpy
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FRAME = runpy.run_path(str(ROOT / "code/01_build_popular_episode_frame.py"))
FRAME_ROOT = ROOT / "data/derived/popular_frame"
PODCASTS = ROOT / "config/podcasts.json"
RAW_TRANSCRIPTS = ROOT / "data/raw/transcripts"
SAMPLES = ROOT / "config/popular_frame"
GUEST_LABEL = "Guest"
DEFAULT_MAX_SPEAKERS = 4


def existing_guids(show_directory: str) -> dict[str, str]:
    """Map RSS GUID -> existing episode folder for one show."""
    found = {}
    for path in (RAW_TRANSCRIPTS / show_directory).glob("*/rss_metadata.json"):
        guid = (json.loads(path.read_text(encoding="utf-8")).get("episode") or {}).get("guid")
        if guid:
            found[guid] = path.parent.name
    return found


def feed_items(feed_file: str, show_id: str) -> dict[str, dict[str, Any]]:
    """Re-read the frozen feed so records carry the full RSS fields (incl. description)."""
    channel = ET.fromstring((ROOT / feed_file).read_bytes()).find("channel")
    descriptions = {}
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        key = (item.findtext("guid") or "").strip() or (enclosure.get("url", "") if enclosure is not None else "")
        descriptions[key] = item.findtext("description") or ""
    items = {}
    for item in FRAME["parse_items"](channel, show_id):
        key = item["rss_guid"] or item["enclosure_url"]
        items[item["episode_id"]] = {**item, "description": descriptions.get(key, "")}
    return items


def record(item: dict[str, Any], identifier: str, show_id: str, show: dict[str, Any],
           feed: dict[str, str], accessed_at: str) -> dict[str, Any]:
    duration = item["duration_seconds"]
    return {
        "schema_version": "0.2",
        "accessed_at": accessed_at,
        "episode_id": identifier,
        "podcast": {
            "show_id": show_id,
            "name": show["name"],
            "hosts": show["hosts"],
            "guest_label_candidate": GUEST_LABEL,
            "max_speakers_expected": show.get("max_speakers_expected", DEFAULT_MAX_SPEAKERS),
            "speaker_identities_verified": False,
        },
        "episode": {
            "title": item["title"],
            "description": item["description"],
            "published_at": item["published_at"],
            "guid": item["rss_guid"] or item["enclosure_url"],
            "duration_declared": duration,
            "enclosure_url": item["enclosure_url"],
            "enclosure_type": item["enclosure_type"],
            "episode_type": item["episode_type"],
        },
        "episode_metadata_source": "immutable official podcast RSS snapshot",
        "rss_feed_url": show["rss_url"],
        "rss_snapshot": {"relative_path": feed["feed_file"], "sha256": feed["sha256"]},
        "match": {"method": "popular frame 2026-10-02 (Edison Top 50, genre, long form)", "human_verified": False},
        "media": {
            "source": "official podcast RSS enclosure",
            "retained_locally": False,
            "delivery": "rss-direct",
            "duration_seconds": duration if duration is not None else 0.0,
            "duration_missing_in_feed": duration is None,
        },
    }


def write_once(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:  # never overwrite raw records
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="write records and samples")
    args = parser.parse_args()

    frame = sorted(path for path in FRAME_ROOT.iterdir() if (path / "shows.csv").is_file())[-1]
    with (frame / "shows.csv").open(newline="", encoding="utf-8") as handle:
        shows = [row for row in csv.DictReader(handle) if row["included"] == "1"]
    with (frame / "episodes.csv").open(newline="", encoding="utf-8") as handle:
        selected: dict[str, list[str]] = defaultdict(list)
        for row in csv.DictReader(handle):
            selected[row["show_id"]].append(row["episode_id"])
    manifest = json.loads((ROOT / f"data/raw/rss/snapshots/{frame.name}.json").read_text(encoding="utf-8"))
    feeds = {item["show_id"]: item for item in manifest["feeds"]}
    podcasts = json.loads(PODCASTS.read_text(encoding="utf-8"))["podcasts"]
    missing = [row["show_id"] for row in shows if row["show_id"] not in podcasts]
    if missing:
        raise SystemExit(f"Add these shows (name, raw_directory, rss_url, hosts) to config/podcasts.json: {missing}")

    accessed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    totals = {"new": 0, "reused": 0, "hours": 0.0}
    for row in shows:
        show_id = row["show_id"]
        show = podcasts[show_id]
        directory = show["raw_directory"]
        feed = {"feed_file": feeds[show_id]["file"], "sha256": feeds[show_id]["sha256"]}
        items = feed_items(feed["feed_file"], show_id)
        reuse = existing_guids(directory)
        episodes, documents = [], []
        for frame_id in selected[show_id]:
            item = items[frame_id]
            guid = item["rss_guid"] or item["enclosure_url"]
            identifier = reuse.get(guid, frame_id)
            episodes.append({
                "episode_id": identifier, "rss_guid": guid, "published_date": item["published_date"],
                "guest_name": GUEST_LABEL, "duration_seconds": item["duration_seconds"] or 0.0,
            })
            if guid not in reuse:
                documents.append((identifier, record(item, identifier, show_id, show, feed, accessed_at)))
        hours = sum(item["duration_seconds"] for item in episodes) / 3600
        totals["new"] += len(documents)
        totals["reused"] += len(episodes) - len(documents)
        totals["hours"] += hours
        print(f"  {show_id:42} {len(episodes):5} episodes ({len(episodes) - len(documents):4} existing) {hours:7.1f} h")
        if not args.yes:
            continue
        for identifier, document in documents:
            write_once(RAW_TRANSCRIPTS / directory / identifier / "rss_metadata.json", document)
        sample = {
            "schema_version": "0.2",
            "sample_id": f"popular_frame_{show_id}_{frame.name}",
            "show_id": show_id,
            "selected_at": accessed_at[:10],
            "selection_rule": (
                "Popular frame (notes/PLAN.md, 2026-10-02/03): show in an Edison US ranking "
                "Q3 2019-Q2 2026, primary RSS category Comedy, Health & Fitness or Education > "
                "Self-Improvement, median episode >= 60 min; all non-trailer episodes published "
                f"{FRAME['WINDOW_START']} to {FRAME['WINDOW_END'] - timedelta(days=1)}."
            ),
            "source": {"rss_url": show["rss_url"], "snapshot_relative_path": feed["feed_file"],
                       "snapshot_sha256": feed["sha256"], "frame": str(frame.relative_to(ROOT))},
            "storage_strategy": "metadata_only_rss_direct_transcription",
            "episodes": episodes,
        }
        path = SAMPLES / f"{show_id}.json"
        if path.exists():
            raise SystemExit(f"{path.relative_to(ROOT)} exists; refusing to overwrite a frozen sample")
        write_once(path, sample)

    print(f"\n{len(shows)} shows; {totals['new'] + totals['reused']:,} episodes "
          f"({totals['new']:,} new raw records, {totals['reused']:,} existing); {totals['hours']:,.0f} hours")
    if not args.yes:
        print("Plan only. Add --yes to write raw records and config/popular_frame/<show_id>.json samples.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
