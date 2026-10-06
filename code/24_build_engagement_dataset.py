#!/usr/bin/env python3
"""Add audience engagement measures to the episode and guest datasets.

Joins, by episode_id:
- the guest dataset with health/science flags (18_, 19_);
- the episode-to-video matches (21_match_youtube_videos.py);
- the per-video YouTube metrics snapshot (22_snapshot_youtube_video_metrics.py);
- the show-level Apple Podcasts ratings snapshot (23_snapshot_apple_ratings.py).
No network. YouTube counts are cumulative at the snapshot time, so rates per
day online are added; they are crude because views are not spread evenly.

    python code/24_build_engagement_dataset.py [--videos <youtube_videos run>]

Output, next to the guest dataset (data/derived/guest_dataset/<frame>/):
    episodes_engagement.csv        one row per episode
    episode_guests_engagement.csv  one row per episode-guest pair
    engagement_summary.md          coverage and medians per show
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GUESTS = ROOT / "data/derived/guest_dataset"
MATCHES = ROOT / "data/derived/youtube_match"
VIDEOS = ROOT / "data/raw/audience_metrics/youtube_videos"
APPLE = ROOT / "data/raw/audience_metrics/apple_ratings"
MAX_DATE_GAP_DAYS = 7  # upload more than this many days from the RSS date is flagged


def latest(folder: Path, marker: str) -> Path:
    return sorted(path.parent for path in folder.glob(f"*/{marker}"))[-1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def ratio(numerator: Any, denominator: Any, scale: float = 1.0) -> Any:
    if numerator in (None, "") or not denominator:
        return ""
    return round(scale * float(numerator) / float(denominator), 4)


def replay_peak_minute(heatmap: list[dict[str, Any]] | None) -> Any:
    """Minute of the most re-watched part of the video (YouTube 'most replayed')."""
    if not heatmap:
        return ""
    peak = max(heatmap, key=lambda point: point.get("value") or 0)
    return round(float(peak.get("start_time") or 0) / 60, 1)


def match_check(gap: int | None, match: dict[str, str]) -> str:
    """ok: uploaded within MAX_DATE_GAP_DAYS of the RSS date; reupload_likely: later/earlier upload but the
    episode number or nearly the whole title agrees (e.g. back catalogue uploaded in bulk); date_gap_check:
    neither, so the match may be a different episode (e.g. another visit by a recurring guest)."""
    if gap is not None and abs(gap) <= MAX_DATE_GAP_DAYS:
        return "ok"
    if match.get("episode_number_agrees") == "1" or float(match.get("title_word_share") or 0) >= 0.85:
        return "reupload_likely"
    return "date_gap_check"


def youtube_columns(match: dict[str, str], video: dict[str, Any] | None, rss_date: str) -> dict[str, Any]:
    empty = {
        "yt_video_id": "", "yt_url": "", "yt_match_score": "", "yt_match_check": match.get("match_status", "no_match"),
        "yt_upload_date": "", "yt_date_gap_days": "", "yt_snapshot_at": "", "yt_days_online": "",
        "yt_views": "", "yt_likes": "", "yt_comments": "", "yt_views_per_day": "",
        "yt_likes_per_1k_views": "", "yt_comments_per_1k_views": "", "yt_channel_subscribers": "",
        "yt_views_per_subscriber": "", "yt_duration_minutes": "", "yt_category": "", "yt_replay_peak_minute": "",
    }
    if not match.get("video_id"):
        return empty
    row = {**empty, "yt_video_id": match["video_id"], "yt_url": f"https://www.youtube.com/watch?v={match['video_id']}",
           "yt_match_score": match["match_score"]}
    if video is None:
        row["yt_match_check"] = "metrics_not_fetched"
        return row
    if video.get("status") != "ok":
        row["yt_match_check"] = "video_unavailable"
        return row
    uploaded = datetime.strptime(video["upload_date"], "%Y%m%d").date() if video.get("upload_date") else None
    accessed = datetime.fromisoformat(video["accessed_at"]).date()
    gap = (uploaded - date.fromisoformat(rss_date)).days if uploaded and rss_date else None
    days_online = max((accessed - uploaded).days, 1) if uploaded else None
    views, likes, comments = video.get("view_count"), video.get("like_count"), video.get("comment_count")
    subscribers = video.get("channel_follower_count")
    row.update({
        "yt_match_check": match_check(gap, match),
        "yt_upload_date": uploaded.isoformat() if uploaded else "", "yt_date_gap_days": gap if gap is not None else "",
        "yt_snapshot_at": video["accessed_at"], "yt_days_online": days_online or "",
        "yt_views": views if views is not None else "", "yt_likes": likes if likes is not None else "",
        "yt_comments": comments if comments is not None else "",
        "yt_views_per_day": ratio(views, days_online), "yt_likes_per_1k_views": ratio(likes, views, 1000),
        "yt_comments_per_1k_views": ratio(comments, views, 1000), "yt_channel_subscribers": subscribers or "",
        "yt_views_per_subscriber": ratio(views, subscribers),
        "yt_duration_minutes": round(video["duration"] / 60, 1) if video.get("duration") else "",
        "yt_category": "; ".join(video.get("categories") or []), "yt_replay_peak_minute": replay_peak_minute(video.get("heatmap")),
    })
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--videos", help="youtube_videos run folder name (default: latest)")
    args = parser.parse_args()

    dataset = latest(GUESTS, "episode_guests_topics.csv")
    match_dir = latest(MATCHES, "matches.csv")
    video_dir = VIDEOS / args.videos if args.videos else latest(VIDEOS, "run.json")
    apple_dir = latest(APPLE, "ratings.csv")

    matches = {row["episode_id"]: row for row in read_csv(match_dir / "matches.csv")}
    videos = {}
    for path in video_dir.glob("*.json"):
        if path.name != "run.json":
            record = json.loads(path.read_text(encoding="utf-8"))
            videos[record["id"]] = record
    apple = {row["show_id"]: row for row in read_csv(apple_dir / "ratings.csv")}
    topics = {row["episode_id"]: row for row in read_csv(dataset / "episode_topics.csv")}

    episode_rows, by_episode = [], {}
    for episode in read_csv(dataset / "episodes.csv"):
        match = matches.get(episode["episode_id"], {})
        topic = topics[episode["episode_id"]]
        row = {
            **{k: episode[k] for k in ("show", "show_id", "episode_id", "published_date", "year", "title", "guests",
                                       "n_guests", "duration_minutes", "show_edison_ranked_this_year",
                                       "show_edison_best_rank_this_year")},
            "episode_health_related": topic["health_related"], "episode_science_related": topic["science_related"],
            **youtube_columns(match, videos.get(match.get("video_id", "")), episode["published_date"]),
            "apple_show_rating": apple.get(episode["show_id"], {}).get("apple_rating", ""),
            "apple_show_rating_count": apple.get(episode["show_id"], {}).get("apple_rating_count", ""),
        }
        episode_rows.append(row)
        by_episode[episode["episode_id"]] = row

    engagement_keys = [k for k in episode_rows[0] if k.startswith(("yt_", "apple_", "show_edison"))]
    guest_rows = [{**row, **{k: by_episode[row["episode_id"]][k] for k in engagement_keys}}
                  for row in read_csv(dataset / "episode_guests_topics.csv")]

    for name, rows in (("episodes_engagement.csv", episode_rows), ("episode_guests_engagement.csv", guest_rows)):
        with (dataset / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    by_show = defaultdict(list)
    for row in episode_rows:
        by_show[row["show"]].append(row)
    median = lambda values: f"{statistics.median(values):,.0f}" if values else ""
    lines = [
        f"# Engagement coverage ({dataset.name})", "",
        f"Matches `{match_dir.relative_to(ROOT)}`, YouTube metrics `{video_dir.relative_to(ROOT)}` "
        f"({len(videos):,} videos), Apple ratings `{apple_dir.relative_to(ROOT)}`. `yt_match_check` = ok when the "
        f"upload date is within {MAX_DATE_GAP_DAYS} days of the RSS date; reupload_likely when it is not but the "
        "episode number or nearly the whole title agrees; date_gap_check otherwise (verify before use).", "",
        "| Show | Episodes | YouTube metrics | of which ok or reupload | Median views | Median likes | Median comments | Apple rating (count) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for show, rows in sorted(by_show.items(), key=lambda item: item[0].casefold()):
        have = [r for r in rows if r["yt_views"] != ""]
        ok = [r for r in have if r["yt_match_check"] in ("ok", "reupload_likely")]
        lines.append(
            f"| {show} | {len(rows)} | {len(have)} | {len(ok)} | {median([int(r['yt_views']) for r in ok])} | "
            f"{median([int(r['yt_likes']) for r in ok if r['yt_likes'] != ''])} | "
            f"{median([int(r['yt_comments']) for r in ok if r['yt_comments'] != ''])} | "
            f"{rows[0]['apple_show_rating']} ({rows[0]['apple_show_rating_count']}) |")
    (dataset / "engagement_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    have = sum(r["yt_views"] != "" for r in episode_rows)
    print(f"{len(episode_rows):,} episodes ({have:,} with YouTube metrics), {len(guest_rows):,} guest rows "
          f"-> {dataset.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
