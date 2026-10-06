#!/usr/bin/env python3
"""Snapshot public YouTube audience metrics for frozen episode samples.

Reads view, like and comment counts with yt-dlp (no media download) and writes
one new, timestamped raw snapshot. Existing snapshots are never overwritten.
Counts are cumulative at the access time; analysis must account for episode age.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yt_dlp
except ImportError:  # pragma: no cover - checked at runtime
    yt_dlp = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = [
    ROOT / "config/jre_starter_sample.json",
    ROOT / "config/doac_starter_sample.json",
]
OUTPUT_ROOT = ROOT / "data/raw/audience_metrics/youtube"
FIELDS = [
    "id", "title", "channel", "channel_id", "upload_date", "timestamp",
    "duration", "view_count", "like_count", "comment_count",
    "channel_follower_count", "live_status", "availability", "webpage_url",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_episodes(paths: list[Path]) -> list[dict[str, str]]:
    episodes: list[dict[str, str]] = []
    for path in paths:
        sample = json.loads(path.read_text(encoding="utf-8"))
        for episode in sample["episodes"]:
            if not episode.get("youtube_id"):
                raise ValueError(f"{path.name}: episode without youtube_id: {episode}")
            episodes.append({
                "show": sample["show_id"],
                "sample_id": sample["sample_id"],
                "youtube_id": episode["youtube_id"],
                "guest_name": episode.get("guest_name") or "",
                "published_date": episode.get("published_date") or "",
            })
    ids = [episode["youtube_id"] for episode in episodes]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate YouTube IDs across samples")
    return episodes


def fetch_metrics(youtube_id: str) -> dict[str, Any]:
    options = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=False)
    if info.get("_type") == "playlist":
        raise ValueError("Expected one video, but YouTube returned a playlist")
    if info.get("id") != youtube_id:
        raise ValueError(f"Requested {youtube_id}, received {info.get('id')}")
    return {field: info.get(field) for field in FIELDS}


def write_once(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", type=Path,
                        help="Frozen sample config; repeatable (default: JRE and DOAC starter samples)")
    parser.add_argument("--yes", action="store_true", help="Fetch and write; otherwise list only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = [path if path.is_absolute() else ROOT / path for path in (args.sample or DEFAULT_SAMPLES)]
    episodes = load_episodes(samples)
    print(f"{len(episodes)} episodes from {len(samples)} sample(s)")
    if not args.yes:
        for episode in episodes:
            print(f"  {episode['show']:5} {episode['youtube_id']:12} {episode['guest_name']}")
        print("Dry run; add --yes to fetch public metrics.")
        return 0
    if yt_dlp is None:
        raise SystemExit("yt-dlp is not installed; activate the podcast_observational environment")

    started = utc_now()
    records = []
    for episode in episodes:
        accessed = utc_now().isoformat()
        try:
            record = {**episode, "accessed_at": accessed, "status": "ok", **fetch_metrics(episode["youtube_id"])}
        except Exception as exc:  # recorded, not hidden
            record = {**episode, "accessed_at": accessed, "status": "error", "error": str(exc)}
        records.append(record)
        print(f"  {record['status']:5} {episode['youtube_id']:12} views={record.get('view_count')}")

    snapshot_id = started.strftime("%Y%m%dT%H%M%SZ")
    document = {
        "schema_version": "0.1",
        "snapshot_id": snapshot_id,
        "started_at": started.isoformat(),
        "finished_at": utc_now().isoformat(),
        "source": "YouTube public video metadata via yt-dlp (no media downloaded)",
        "yt_dlp_version": yt_dlp.version.__version__,
        "samples": {str(path.relative_to(ROOT)): sha256(path) for path in samples},
        "notes": "Counts are cumulative at accessed_at and change over time; like_count may be hidden (null).",
        "episodes": records,
    }
    path = OUTPUT_ROOT / snapshot_id / "metrics.json"
    write_once(path, document)
    failures = sum(record["status"] != "ok" for record in records)
    print(f"Wrote {path.relative_to(ROOT)}; {len(records) - failures} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
