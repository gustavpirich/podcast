#!/usr/bin/env python3
"""Freeze the eligible Diary of a CEO RSS archive and create metadata-only raw records.

Reads an existing immutable DOAC RSS snapshot (nothing is downloaded) and
applies the full-length interview rule: RSS episode type "full", a declared
duration of at least 60 minutes, and no clip title ("Moment", "Most Replayed
Moment", "Highlight", "CEO Diaries", ...). Existing episode directories are
reused by RSS GUID (the ten 2026-09-10 YouTube-ID episodes); new episodes get
the identifier doac-<publication date>-<GUID hash>. Raw files are never
overwritten. Free.

    python code/01_build_doac_rss_archive.py \\
        --snapshot data/raw/rss/doac/doac_rss_20261003T092332Z.xml          # plan
    python code/01_build_doac_rss_archive.py \\
        --snapshot data/raw/rss/doac/doac_rss_20261003T092332Z.xml --yes    # write
"""

from __future__ import annotations

import argparse
import json
import re
import runpy
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PODCAST_CONFIG = PROJECT_ROOT / "config" / "podcasts.json"
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
JRE = runpy.run_path(str(PROJECT_ROOT / "code/01_build_jre_rss_archive.py"))
ArchiveError = JRE["ArchiveError"]
MIN_MINUTES = 60
CLIP = re.compile(
    r"^(moment\b|most (replayed|shared|played) (moment|clip)|key moment|highlight|notable moment"
    r"|top moment|best moment|this stuck with me|your 1% boost|life lesson|ceo diaries|.*\btrailer\b)",
    re.IGNORECASE,
)
SELECTION_RULE = (
    "Include DOAC RSS items with episode type 'full', a declared duration of at least "
    f"{MIN_MINUTES} minutes and no clip title (Moment, Most Replayed/Shared/Played Moment, Key/"
    "Notable/Top/Best Moment, Highlight, This Stuck With Me, Your 1% Boost, Life Lesson, CEO "
    "Diaries, trailer)."
)


def eligible(title: str, episode_type: str | None, duration_seconds: float) -> bool:
    return episode_type == "full" and duration_seconds >= MIN_MINUTES * 60 and not CLIP.match(title)


def guest_label(title: str) -> str:
    """Best-effort guest name from a DOAC title ('Name: topic' or 'topic | Name'); unverified."""
    if " | " in title:
        return title.rsplit(" | ", 1)[1].strip()
    head = title.split(":", 1)[0].strip()
    if ":" in title and len(head.split()) <= 5:
        return head
    return "Guest not encoded in RSS title"


def episode_id(published_date: str, guid: str) -> str:
    return f"doac-{published_date}-{JRE['sha256_bytes'](guid.encode('utf-8'))[:12]}"


def parse_rss(xml_bytes: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ArchiveError(f"RSS snapshot is invalid XML: {exc}") from exc
    itunes = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
    rows: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        declared = item.findtext(f"{itunes}duration")
        duration = JRE["parse_duration"](declared) if declared else 0.0
        if not eligible(title, item.findtext(f"{itunes}episodeType"), duration):
            continue
        enclosure = item.find("enclosure")
        guid = (item.findtext("guid") or "").strip()
        published = item.findtext("pubDate")
        enclosure_url = enclosure.get("url") if enclosure is not None else None
        if not guid or not enclosure_url or not published:
            raise ArchiveError(f"Eligible RSS item is incomplete: {title}")
        published_at = parsedate_to_datetime(published).astimezone(timezone.utc)
        rows.append({
            "title": title,
            "description": item.findtext("description"),
            "published_at": published_at.isoformat(),
            "published_date": published_at.date().isoformat(),
            "guid": guid,
            "duration_declared": declared,
            "duration_seconds": duration,
            "enclosure_url": enclosure_url,
            "enclosure_type": enclosure.get("type") if enclosure is not None else None,
            "guest_name": guest_label(title),
        })
    if not rows:
        raise ArchiveError("RSS snapshot contains no eligible DOAC episodes")
    guids = [row["guid"] for row in rows]
    if len(set(guids)) != len(guids):
        raise ArchiveError("Eligible RSS GUIDs are not unique")
    return sorted(rows, key=lambda row: row["published_at"], reverse=True)


def build_documents(rows: list[dict[str, Any]], *, show: dict[str, Any], accessed_at: str,
                    snapshot_path: Path, snapshot_sha256: str,
                    existing: dict[str, str]) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    episodes: list[dict[str, Any]] = []
    metadata_documents: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        identifier = existing.get(row["guid"], episode_id(row["published_date"], row["guid"]))
        episodes.append({
            "episode_id": identifier,
            "rss_guid": row["guid"],
            "published_date": row["published_date"],
            "guest_name": row["guest_name"],
            "duration_seconds": row["duration_seconds"],
        })
        if row["guid"] in existing:
            continue
        episode = {key: row[key] for key in ("title", "description", "published_at", "guid",
                                             "duration_declared", "enclosure_url", "enclosure_type")}
        metadata_documents.append((identifier, {
            "schema_version": "0.2",
            "accessed_at": accessed_at,
            "episode_id": identifier,
            "podcast": {
                "show_id": "doac",
                "name": show["name"],
                "hosts": show["hosts"],
                "guest_label_candidate": row["guest_name"],
                "speaker_identities_verified": False,
            },
            "episode": episode,
            "episode_metadata_source": "immutable official podcast RSS snapshot",
            "rss_feed_url": show["rss_url"],
            "rss_snapshot": {"relative_path": str(snapshot_path.relative_to(PROJECT_ROOT)),
                             "sha256": snapshot_sha256},
            "match": {"method": "RSS inclusion rule", "human_verified": False},
            "media": {
                "source": "official podcast RSS enclosure",
                "retained_locally": False,
                "delivery": "rss-direct",
                "duration_seconds": row["duration_seconds"],
            },
        }))
    manifest = {
        "schema_version": "0.2",
        "sample_id": f"doac_full_rss_archive_{snapshot_path.stem.rsplit('_', 1)[-1]}",
        "show_id": "doac",
        "selected_at": accessed_at[:10],
        "selection_rule": SELECTION_RULE,
        "source": {
            "rss_url": show["rss_url"],
            "snapshot_relative_path": str(snapshot_path.relative_to(PROJECT_ROOT)),
            "snapshot_sha256": snapshot_sha256,
        },
        "storage_strategy": "metadata_only_rss_direct_transcription",
        "episodes": episodes,
    }
    return manifest, metadata_documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, required=True, help="existing raw DOAC RSS snapshot")
    parser.add_argument("--yes", action="store_true", help="write the manifest and raw records")
    args = parser.parse_args()
    try:
        snapshot_path = (args.snapshot if args.snapshot.is_absolute() else PROJECT_ROOT / args.snapshot).resolve()
        if not snapshot_path.is_file() or not snapshot_path.is_relative_to(RAW_ROOT / "rss"):
            raise ArchiveError("--snapshot must be an existing file under data/raw/rss/")
        show = json.loads(PODCAST_CONFIG.read_text(encoding="utf-8"))["podcasts"]["doac"]
        raw_episode_root = RAW_ROOT / "transcripts" / show["raw_directory"]
        xml_bytes = snapshot_path.read_bytes()
        rows = parse_rss(xml_bytes)
        manifest, metadata_documents = build_documents(
            rows, show=show, accessed_at=JRE["utc_now"](), snapshot_path=snapshot_path,
            snapshot_sha256=JRE["sha256_bytes"](xml_bytes), existing=JRE["existing_guid_map"](raw_episode_root),
        )
        manifest_path = PROJECT_ROOT / "config" / f"{manifest['sample_id']}.json"
        ids = [episode["episode_id"] for episode in manifest["episodes"]]
        if len(set(ids)) != len(ids):
            raise ArchiveError("Episode identifiers are not unique")
        years: dict[str, int] = {}
        for row in rows:
            years[row["published_date"][:4]] = years.get(row["published_date"][:4], 0) + 1
        print("DOAC metadata-only archive plan")
        print(f"  Eligible episodes: {len(rows):,} ({sum(r['duration_seconds'] for r in rows) / 3600:,.1f} hours)")
        print(f"  By year:           {dict(sorted(years.items()))}")
        print(f"  Existing records:  {len(rows) - len(metadata_documents):,}")
        print(f"  New raw metadata:  {len(metadata_documents):,}")
        print(f"  RSS snapshot:      {snapshot_path.relative_to(PROJECT_ROOT)}")
        print(f"  Manifest:          {manifest_path.relative_to(PROJECT_ROOT)}")
        if not args.yes:
            print("\nDry run only. Add --yes to write immutable metadata and the manifest.")
            return 0
        JRE["write_json_once"](manifest_path, manifest)
        for identifier, document in metadata_documents:
            JRE["write_json_once"](raw_episode_root / identifier / "rss_metadata.json", document)
        print(f"\nCreated {len(metadata_documents):,} metadata-only episode records.")
        return 0
    except (ArchiveError, KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
