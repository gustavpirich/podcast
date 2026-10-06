#!/usr/bin/env python3
"""Build the episode list for the popular health / self-help / comedy frame.

Reads only frozen RSS files (from 01_snapshot_show_feeds.py) and applies the
researcher's 2026-10-02 frame. A show is included when it meets all three
criteria:

1. Popular: listed in an Edison ranking Q3 2019 - Q2 2026 (every show
   in config/popular_show_feeds.csv meets this by construction).
2. Genre: its *primary* RSS category (the first <itunes:category>) is Comedy,
   Health & Fitness, or Education > Self-Improvement.
3. Long-form conversation: the median length of its episodes in the window is
   at least MIN_MEDIAN_MINUTES, using the durations declared in the feed.

Episodes: every episode of an included show published in the
window below, except items marked <itunes:episodeType>trailer</itunes:episodeType>.

No network access, no cost. Writes to data/derived/popular_frame/<feed snapshot>/:
    shows.csv      one row per show, with category, inclusion and coverage
    episodes.csv   one row per included episode
    summary.md     counts, hours and the transcription cost estimate
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FEEDS = ROOT / "config/popular_show_feeds.csv"
SNAPSHOTS = ROOT / "data/raw/rss/snapshots"
PRICING = ROOT / "config/assemblyai_pricing_2026-09-15.json"
OUTPUT_ROOT = ROOT / "data/derived/popular_frame"

# Researcher decision 2026-10-02 (see notes/PLAN.md).
WINDOW_START = date(2019, 1, 1)   # inclusive (researcher decision 2026-10-03; was 2021-10-01)
WINDOW_END = date(2026, 10, 1)    # exclusive
INCLUDED_CATEGORIES = {("Comedy", None), ("Health & Fitness", None), ("Education", "Self-Improvement")}
MIN_MEDIAN_MINUTES = 60
ITUNES_NAMESPACES = (
    "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "http://www.itunes.com/DTDs/Podcast-1.0.dtd",
)


def itunes(element: ET.Element, tag: str) -> list[ET.Element]:
    found: list[ET.Element] = []
    for namespace in ITUNES_NAMESPACES:
        found += element.findall(f"{{{namespace}}}{tag}")
    return found


def itunes_text(element: ET.Element, tag: str) -> str:
    matches = itunes(element, tag)
    return (matches[0].text or "").strip() if matches else ""


def categories(channel: ET.Element) -> list[tuple[str, str | None]]:
    """Ordered (category, first subcategory) pairs; the first is the primary."""
    pairs = []
    for top in itunes(channel, "category"):
        subs = itunes(top, "category")
        pairs.append((top.get("text", "").strip(), subs[0].get("text", "").strip() if subs else None))
    return pairs


def genre_included(primary: tuple[str, str | None] | None) -> bool:
    if primary is None:
        return False
    return (primary[0], None) in INCLUDED_CATEGORIES or primary in INCLUDED_CATEGORIES


def parse_duration(value: str) -> float | None:
    """Seconds from '3600', '3600.5', 'MM:SS' or 'HH:MM:SS'; None if absent or unreadable."""
    value = value.strip()
    if not value:
        return None
    try:
        if ":" not in value:
            return float(value)
        parts = [float(part) for part in value.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def parse_items(channel: ET.Element, show_id: str) -> list[dict[str, Any]]:
    items = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        guid = (item.findtext("guid") or "").strip()
        url = enclosure.get("url", "") if enclosure is not None else ""
        key = guid or url
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
        except (TypeError, ValueError):
            published = None
        items.append({
            "show_id": show_id,
            "episode_id": f"{show_id}-{hashlib.sha256(key.encode()).hexdigest()[:12]}" if key else "",
            "rss_guid": guid,
            "title": (item.findtext("title") or "").strip(),
            "published_at": published.isoformat() if published else "",
            "published_date": published.date().isoformat() if published else "",
            "episode_type": itunes_text(item, "episodeType").casefold() or "full",
            "duration_seconds": parse_duration(itunes_text(item, "duration")),
            "enclosure_url": url,
            "enclosure_type": enclosure.get("type", "") if enclosure is not None else "",
        })
    return items


def median(values: list[float]) -> float | None:
    values = sorted(values)
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def in_window(item: dict[str, Any]) -> bool:
    return bool(item["published_date"]) and WINDOW_START <= date.fromisoformat(item["published_date"]) < WINDOW_END


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    manifests = sorted(SNAPSHOTS.glob("*.json"))
    if not manifests:
        raise SystemExit("No feed snapshot; run 01_snapshot_show_feeds.py --yes first")
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    with FEEDS.open(newline="", encoding="utf-8") as handle:
        feed_rows = {row["show_id"]: row for row in csv.DictReader(handle)}
    rate = float(json.loads(PRICING.read_text(encoding="utf-8"))["rates_per_audio_hour"]["configured_total"])

    shows, episodes = [], []
    for record in manifest["feeds"]:
        config = feed_rows[record["show_id"]]
        row: dict[str, Any] = {
            "show": record["show"], "show_id": record["show_id"],
            "edison_releases": config.get("edison_releases", ""), "feed_status": record["status"],
        }
        if record["status"] != "ok":
            shows.append({**row, "included": 0, "reason": "feed download failed"})
            continue
        content = (ROOT / record["file"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise SystemExit(f"Checksum mismatch for {record['file']}")
        try:
            channel = ET.fromstring(content).find("channel")
        except ET.ParseError as error:
            shows.append({**row, "included": 0, "reason": f"invalid XML: {error}"})
            continue
        pairs = categories(channel)
        primary = pairs[0] if pairs else None
        items = parse_items(channel, record["show_id"])
        guids = [item["episode_id"] for item in items if item["episode_id"]]
        if len(guids) != len(set(guids)):
            duplicates = len(guids) - len(set(guids))
            print(f"  note: {record['show_id']} has {duplicates} duplicate GUID(s); keeping first occurrence")
        dated = sorted(item["published_date"] for item in items if item["published_date"])
        window = [item for item in items if in_window(item)]
        selected, seen = [], set()
        for item in window:
            if item["episode_type"] == "trailer" or item["episode_id"] in seen or not item["enclosure_url"]:
                continue
            seen.add(item["episode_id"])
            selected.append(item)
        genre_ok = genre_included(primary)
        median_seconds = median([item["duration_seconds"] for item in selected if item["duration_seconds"]])
        long_form = median_seconds is not None and median_seconds >= MIN_MEDIAN_MINUTES * 60
        included = genre_ok and long_form
        reasons = []
        if not genre_ok:
            reasons.append("primary category outside frame")
        if not long_form:
            reasons.append(f"median episode under {MIN_MEDIAN_MINUTES} min")
        hours = sum(item["duration_seconds"] or 0 for item in selected) / 3600
        types = Counter(item["episode_type"] for item in window)
        row.update({
            "primary_category": primary[0] if primary else "",
            "primary_subcategory": (primary[1] or "") if primary else "",
            "all_categories": " ; ".join(f"{c} > {s}" if s else c for c, s in pairs),
            "genre_in_frame": int(genre_ok),
            "median_minutes": round(median_seconds / 60, 1) if median_seconds else "",
            "long_form": int(long_form),
            "included": int(included),
            "reason": "meets all three criteria" if included else "; ".join(reasons),
            "feed_items": len(items),
            "earliest_item": dated[0] if dated else "",
            "latest_item": dated[-1] if dated else "",
            "feed_reaches_window_start": int(bool(dated) and dated[0] <= WINDOW_START.isoformat()),
            "window_items": len(window),
            "window_full": types.get("full", 0),
            "window_bonus": types.get("bonus", 0),
            "window_trailers": types.get("trailer", 0),
            "episodes_selected": len(selected),
            "missing_duration": sum(item["duration_seconds"] is None for item in selected),
            "hours_selected": round(hours, 1),
            "estimated_cost_usd": round(hours * rate),
            "feed_file": record["file"],
        })
        shows.append(row)
        if included:
            episodes += selected

    output = OUTPUT_ROOT / manifest["snapshot"]
    output.mkdir(parents=True, exist_ok=True)
    columns = list(max(shows, key=len))  # a successfully parsed row has every column
    shows = [{column: row.get(column, "") for column in columns} for row in shows]
    write_csv(output / "shows.csv", shows)
    write_csv(output / "episodes.csv", episodes)

    chosen = [row for row in shows if row["included"] == 1]
    total_hours = sum(float(row["hours_selected"]) for row in chosen)
    lines = [
        "# Popular health / self-help / comedy episode frame",
        "",
        f"Built {datetime.now(timezone.utc).isoformat(timespec='seconds')} by "
        "`code/01_build_popular_episode_frame.py` from feed snapshot "
        f"`{manifest['snapshot']}`.",
        "",
        f"- Window: {WINDOW_START} to {WINDOW_END} (end exclusive); trailers excluded.",
        "- Criteria: (1) in an Edison US ranking Q3 2019 - Q2 2026; (2) primary RSS "
        "category Comedy, Health & Fitness, or Education > Self-Improvement; (3) median "
        f"episode length in the window at least {MIN_MEDIAN_MINUTES} minutes.",
        f"- {len(shows)} shows checked, {len(chosen)} included, "
        f"{len(episodes):,} episodes, {total_hours:,.0f} hours.",
        f"- Transcription estimate: ${total_hours * rate:,.0f} at ${rate:.2f} per audio hour "
        "(`config/assemblyai_pricing_2026-09-15.json`; recheck current prices).",
        "",
        "## Included shows",
        "",
        "| Show | Category | Edison releases | Median min | Episodes | Hours | Est. $ | Feed reaches window start? |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in sorted(chosen, key=lambda r: -float(r["hours_selected"])):
        category = row["primary_category"] + (f" > {row['primary_subcategory']}" if row["primary_subcategory"] else "")
        lines.append(
            f"| {row['show']} | {category} | {row['edison_releases']} | {row['median_minutes']} | "
            f"{row['episodes_selected']} | "
            f"{float(row['hours_selected']):,.0f} | {int(row['estimated_cost_usd']):,} | "
            f"{'yes' if row['feed_reaches_window_start'] == 1 else 'no, starts ' + str(row['earliest_item'])} |"
        )
    lines += ["", "## Excluded shows", "",
              "| Show | Primary category | Median min | Reason |", "| --- | --- | ---: | --- |"]
    for row in sorted((r for r in shows if r["included"] != 1), key=lambda r: r["show"].casefold()):
        category = row["primary_category"] + (f" > {row['primary_subcategory']}" if row["primary_subcategory"] else "")
        lines.append(f"| {row['show']} | {category} | {row['median_minutes']} | {row['reason']} |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[6:10]))
    print(f"Wrote {output.relative_to(ROOT)}/shows.csv, episodes.csv, summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
