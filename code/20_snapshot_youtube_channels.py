#!/usr/bin/env python3
"""List every public upload of each show's YouTube channel (no media, no API key).

Reads config/youtube_channels.csv and, with the yt-dlp command-line tool in
flat mode, stores the raw channel listings (video id, title, duration) of the
'videos' and 'streams' tabs in a new timestamped folder. Existing snapshots are
never modified. View/like/comment counts are fetched separately per video
(22_snapshot_youtube_video_metrics.py).

    python code/20_snapshot_youtube_channels.py          # show the plan
    python code/20_snapshot_youtube_channels.py --yes    # download listings

Output: data/raw/audience_metrics/youtube_channels/<UTC timestamp>/
    <show_id>__<tab>.json, manifest.json
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
CHANNELS = ROOT / "config/youtube_channels.csv"
OUTPUT_ROOT = ROOT / "data/raw/audience_metrics/youtube_channels"
TABS = ("videos", "streams")


def yt_dlp_version() -> str:
    return subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, check=True).stdout.strip()


def list_tab(channel_id: str, tab: str) -> bytes:
    url = f"https://www.youtube.com/channel/{channel_id}/{tab}"
    result = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--no-warnings", url],
                            capture_output=True, timeout=1800)
    if result.returncode != 0:
        message = result.stderr.decode(errors="replace").strip().splitlines()
        raise RuntimeError(message[-1] if message else f"yt-dlp exit {result.returncode}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="download listings (otherwise only print the plan)")
    args = parser.parse_args()

    with CHANNELS.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["channel_id"]]
    channels = sorted({(row["channel_id"], row["channel_name"]) for row in rows})
    print(f"{len(channels)} channels for {len(rows)} shows in {CHANNELS.relative_to(ROOT)}")
    if not args.yes:
        for channel_id, name in channels:
            print(f"  {channel_id}  {name}")
        print("Plan only. Add --yes to list the channels' uploads (public pages; free).")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = OUTPUT_ROOT / stamp
    snapshot.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "0.1", "snapshot": stamp, "tool": f"yt-dlp {yt_dlp_version()}",
        "channels_config_sha256": hashlib.sha256(CHANNELS.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "listings": [],
    }
    failures = 0
    for channel_id, name in channels:
        for tab in TABS:
            record = {"channel_id": channel_id, "channel_name": name, "tab": tab, "file": f"{channel_id}__{tab}.json"}
            try:
                content = list_tab(channel_id, tab)
                with (snapshot / record["file"]).open("xb") as handle:
                    handle.write(content)
                entries = json.loads(content).get("entries") or []
                record.update(status="ok", entries=len(entries), sha256=hashlib.sha256(content).hexdigest(),
                              accessed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            except Exception as error:  # a channel without a 'streams' tab is normal
                record["status"] = f"error: {error}"[:300]
                failures += tab == "videos"
            manifest["listings"].append(record)
            print(f"  {name[:40]:40} {tab:8} {record['status'][:40]:40} {record.get('entries', '')}", flush=True)
            time.sleep(2)
    with (snapshot / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print(f"\nWrote {snapshot.relative_to(ROOT)} ({failures} failed 'videos' listing(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
