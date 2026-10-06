#!/usr/bin/env python3
"""Match RSS episodes of the guest dataset to videos on the show's YouTube channel.

Reads the latest channel listing (20_snapshot_youtube_channels.py) and the
latest guest dataset (18_build_guest_dataset.py). Within each show, every
episode is compared with every channel video:

- episode number: the same number (#2426, Ep. 205, E445, Episode 1412) in both titles;
- title words: share of the episode's distinctive title words found in the video title
  (show-name words and filler removed);
- guest: a guest's full name (from the guest dataset) appears in the video title;
- length: video duration / audio duration, which must lie in [0.7, 1.4] when both are known;
- dates printed in both titles (Monday Morning Podcast 7-15-21) must agree.

A pair is accepted when (number agrees and length fits) or (guest named and length
fits) or (word share >= 0.6 and length fits) or (word share >= 0.85 and length unknown). Pairs are assigned
one-to-one, best score first. Upload dates, fetched later with the metrics,
are used as an independent check (23_build_engagement_dataset.py). No network.

Output: data/derived/youtube_match/<channel snapshot>/matches.csv, summary.md
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CHANNELS = ROOT / "config/youtube_channels.csv"
LISTINGS = ROOT / "data/raw/audience_metrics/youtube_channels"
GUESTS = ROOT / "data/derived/guest_dataset"
OUTPUT_ROOT = ROOT / "data/derived/youtube_match"
MIN_RATIO, MAX_RATIO = 0.7, 1.4
MIN_VIDEO_SECONDS = 600  # shorter uploads are clips or shorts, not episodes
FILLER = set("""
a an the and or of to in on at for with w ft feat featuring is are was be it its this that my our your his her
we i you me us ep eps episode episodes podcast pod show full live part pt vs x
""".split())
DATE = re.compile(r"\b(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})\b")
NUMBER = re.compile(r"(?:#|\bep\.?\s*|\bepisode\s*|\be|\bkt\s*#?)\s*(\d{2,4})\b", re.IGNORECASE)


def words(title: str, show_words: set[str]) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", title.casefold().replace("'", ""))
    return {t for t in tokens if t not in FILLER and t not in show_words and not t.isdigit() and len(t) > 1}


def title_dates(title: str) -> set[tuple[int, int, int]]:
    return {(int(m), int(d), int(y) % 100) for m, d, y in DATE.findall(title)}


def guest_in_title(guests: str, video_title: str) -> bool:
    """Some guest's full name (2+ words) appears in the video title."""
    title = re.sub(r"[^a-z0-9 ]", " ", video_title.casefold())
    for name in filter(None, (g.strip() for g in guests.split(";"))):
        tokens = [t for t in re.sub(r"[^a-z0-9 ]", " ", name.casefold()).split() if t not in {"dr", "jr"}]
        if len(tokens) >= 2 and re.search(r"\b" + r"\s+".join(map(re.escape, tokens)) + r"\b", title):
            return True
    return False


def numbers(title: str) -> set[str]:
    return {n.lstrip("0") for n in NUMBER.findall(title)}


def latest(folder: Path, marker: str) -> Path:
    found = sorted(path.parent for path in folder.glob(f"*/{marker}"))
    if not found:
        raise SystemExit(f"Nothing found in {folder.relative_to(ROOT)}")
    return found[-1]


def main() -> int:
    listing = latest(LISTINGS, "manifest.json")
    dataset = latest(GUESTS, "episodes.csv")
    manifest = json.loads((listing / "manifest.json").read_text(encoding="utf-8"))
    videos_by_channel: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in manifest["listings"]:
        if record["status"] != "ok":
            continue
        for entry in json.loads((listing / record["file"]).read_text(encoding="utf-8")).get("entries") or []:
            if entry.get("id") and entry.get("title"):
                videos_by_channel[record["channel_id"]][entry["id"]] = {
                    "video_id": entry["id"], "video_title": entry["title"],
                    "video_seconds": entry.get("duration"), "tab": record["tab"],
                }
    with CHANNELS.open(newline="", encoding="utf-8") as handle:
        channel_of = {row["show_id"]: row["channel_id"] for row in csv.DictReader(handle)}
    with (dataset / "episodes.csv").open(newline="", encoding="utf-8") as handle:
        episodes = list(csv.DictReader(handle))

    rows, by_show = [], defaultdict(list)
    for episode in episodes:
        by_show[episode["show_id"]].append(episode)
    for show_id, show_episodes in by_show.items():
        channel_id = channel_of.get(show_id, "")
        videos = [v for v in videos_by_channel.get(channel_id, {}).values()
                  if not v["video_seconds"] or v["video_seconds"] >= MIN_VIDEO_SECONDS]
        show_words = words(show_episodes[0]["show"], set()) | {"weekend", "mom", "house", "momshouse", "bears", "cave"}
        prepared = [(v, words(v["video_title"], show_words), numbers(v["video_title"]), title_dates(v["video_title"]))
                    for v in videos]
        candidates = []
        for episode in show_episodes:
            ep_words = words(episode["title"], show_words) | words(episode["guests"].replace(";", " "), set())
            ep_numbers = numbers(episode["title"])
            ep_dates = title_dates(episode["title"])
            seconds = float(episode["duration_minutes"]) * 60 if episode["duration_minutes"] else None
            for video, v_words, v_numbers, v_dates in prepared:
                if ep_dates and v_dates and not ep_dates & v_dates:
                    continue
                ratio = (video["video_seconds"] / seconds) if (seconds and video["video_seconds"]) else None
                length_ok = ratio is not None and MIN_RATIO <= ratio <= MAX_RATIO
                share = len(ep_words & v_words) / len(ep_words) if ep_words else 0.0
                number_ok = bool(ep_numbers & v_numbers)
                guest_ok = length_ok and guest_in_title(episode["guests"], video["video_title"])
                if (number_ok and length_ok) or guest_ok or (share >= 0.6 and length_ok) or (share >= 0.85 and ratio is None):
                    score = (share + (1.0 if number_ok else 0.0) + (0.8 if guest_ok else 0.0)
                             + (0.5 - abs(1 - ratio) if ratio else 0.0))
                    candidates.append((score, episode["episode_id"], video, share, number_ok, ratio))
        candidates.sort(key=lambda item: item[0], reverse=True)
        used_episodes, used_videos = set(), set()
        matched = {}
        for score, episode_id, video, share, number_ok, ratio in candidates:
            if episode_id in used_episodes or video["video_id"] in used_videos:
                continue
            used_episodes.add(episode_id)
            used_videos.add(video["video_id"])
            matched[episode_id] = (score, video, share, number_ok, ratio)
        for episode in show_episodes:
            hit = matched.get(episode["episode_id"])
            score, video, share, number_ok, ratio = hit if hit else (None, {}, None, None, None)
            rows.append({
                "show_id": show_id, "episode_id": episode["episode_id"], "published_date": episode["published_date"],
                "episode_title": episode["title"], "channel_id": channel_id,
                "video_id": video.get("video_id", ""), "video_title": video.get("video_title", ""),
                "match_score": round(score, 3) if score is not None else "",
                "title_word_share": round(share, 2) if share is not None else "",
                "episode_number_agrees": int(number_ok) if number_ok is not None else "",
                "duration_ratio": round(ratio, 3) if ratio else "",
                "match_status": "matched" if hit else ("no_channel" if not channel_id else "no_match"),
            })

    output = OUTPUT_ROOT / listing.name
    output.mkdir(parents=True, exist_ok=True)
    with (output / "matches.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [f"# YouTube matches ({listing.name}, guest dataset {dataset.name})", "",
             "| Show | Episodes | Matched | Share |", "| --- | ---: | ---: | ---: |"]
    for show_id in sorted(by_show):
        show_rows = [r for r in rows if r["show_id"] == show_id]
        n = sum(r["match_status"] == "matched" for r in show_rows)
        lines.append(f"| {show_id} | {len(show_rows)} | {n} | {n / len(show_rows):.0%} |")
    total = sum(r["match_status"] == "matched" for r in rows)
    lines.append(f"| **all** | {len(rows)} | {total} | {total / len(rows):.0%} |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{total:,} of {len(rows):,} episodes matched -> {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
