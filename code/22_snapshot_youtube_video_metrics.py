#!/usr/bin/env python3
"""Fetch public YouTube engagement metrics for every matched episode video.

For each video id in the latest data/derived/youtube_match/<snapshot>/matches.csv,
runs the yt-dlp command-line tool (metadata only, no media) and stores the
selected fields in one JSON file per video. Resumable: videos that already
have a file in the run folder are skipped, so the command can be stopped and
restarted. Files are never overwritten. Counts are cumulative at access time.

    python code/22_snapshot_youtube_video_metrics.py               # show the plan
    python code/22_snapshot_youtube_video_metrics.py --yes         # start a new run
    python code/22_snapshot_youtube_video_metrics.py --yes --resume 20261003T110000Z
    python code/22_snapshot_youtube_video_metrics.py --yes --resume <run> --shard 2/3   # one of 3 workers

Output: data/raw/audience_metrics/youtube_videos/<run>/<video_id>.json, run.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATCH_ROOT = ROOT / "data/derived/youtube_match"
OUTPUT_ROOT = ROOT / "data/raw/audience_metrics/youtube_videos"
FIELDS = [
    "id", "title", "channel", "channel_id", "upload_date", "timestamp", "duration", "view_count", "like_count",
    "comment_count", "channel_follower_count", "categories", "tags", "live_status", "was_live", "availability",
    "age_limit", "heatmap", "chapters",
]
PAUSE_SECONDS = 1.0
BACKOFF_SECONDS = 300  # after repeated failures (rate limiting), wait before continuing


def fetch(video_id: str) -> dict:
    result = subprocess.run(
        ["yt-dlp", "-J", "--skip-download", "--no-warnings", "--no-playlist", f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, timeout=180,
    )
    if result.returncode != 0:
        lines = result.stderr.decode(errors="replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"yt-dlp exit {result.returncode}")
    info = json.loads(result.stdout)
    if info.get("id") != video_id:
        raise RuntimeError(f"requested {video_id}, received {info.get('id')}")
    return {field: info.get(field) for field in FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="fetch (otherwise only print the plan)")
    parser.add_argument("--resume", help="existing run folder name to continue")
    parser.add_argument("--limit", type=int, help="fetch at most this many videos in this call")
    parser.add_argument("--shard", default="1/1", help="K/N: fetch only every N-th video starting at K (parallel workers)")
    args = parser.parse_args()

    match_dir = sorted(path.parent for path in MATCH_ROOT.glob("*/matches.csv"))[-1]
    with (match_dir / "matches.csv").open(newline="", encoding="utf-8") as handle:
        video_ids = sorted({row["video_id"] for row in csv.DictReader(handle) if row["video_id"]})
    run = OUTPUT_ROOT / (args.resume or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    done = {path.stem for path in run.glob("*.json") if path.name != "run.json"} if run.exists() else set()
    k, n = (int(x) for x in args.shard.split("/"))
    todo = [v for i, v in enumerate(video_ids) if i % n == k - 1 and v not in done][: args.limit]
    print(f"{len(video_ids):,} matched videos in {match_dir.relative_to(ROOT)}; {len(done):,} done in "
          f"{run.relative_to(ROOT)}; {len(todo):,} to fetch (~{len(todo) * 3 / 3600:.1f} h)")
    if not args.yes:
        print("Plan only. Add --yes to fetch public metadata with yt-dlp (free; no media).")
        return 0
    if args.resume and not run.exists():
        raise SystemExit(f"{run} does not exist")
    run.mkdir(parents=True, exist_ok=True)
    run_file = run / "run.json"
    if not run_file.exists():
        tool = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True).stdout.strip()
        run_file.write_text(json.dumps({
            "schema_version": "0.1", "run": run.name, "tool": f"yt-dlp {tool}", "matches": str(match_dir.relative_to(ROOT)),
            "matches_sha256": hashlib.sha256((match_dir / "matches.csv").read_bytes()).hexdigest(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "fields": FIELDS,
        }, indent=2) + "\n", encoding="utf-8")

    failures_in_row = 0
    errors = run / f"errors_{k}of{n}.log"
    for number, video_id in enumerate(todo, start=1):
        accessed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            record = {"accessed_at": accessed, "status": "ok", **fetch(video_id)}
            failures_in_row = 0
        except Exception as error:
            message = str(error)[:500]
            with errors.open("a", encoding="utf-8") as handle:
                handle.write(f"{accessed}\t{video_id}\t{message}\n")
            unavailable = any(s in message for s in ("Private video", "unavailable", "members", "removed", "terminated",
                                                     "confirm your age"))
            if not unavailable:
                failures_in_row += 1
                if failures_in_row >= 5:
                    print(f"  {failures_in_row} failures in a row; pausing {BACKOFF_SECONDS} s", flush=True)
                    time.sleep(BACKOFF_SECONDS)
                    failures_in_row = 0
                continue  # not recorded: retried on the next --resume
            record = {"accessed_at": accessed, "status": "unavailable", "id": video_id, "error": message}
        with (run / f"{video_id}.json").open("x", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        if number % 100 == 0:
            print(f"  {number:,}/{len(todo):,} fetched", flush=True)
        time.sleep(PAUSE_SECONDS)
    print(f"Finished this call. Run folder: {run.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
