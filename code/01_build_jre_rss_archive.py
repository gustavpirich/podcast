#!/usr/bin/env python3
"""Freeze the eligible JRE RSS archive and create metadata-only raw records.

The official RSS XML is saved once as an immutable raw snapshot. The generated
manifest includes numbered JRE and JRE MMA Show releases and excludes Fight
Companion and unnumbered specials. Existing episode directories are reused by
RSS GUID; new episodes receive stable, readable RSS-based identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PODCAST_CONFIG = PROJECT_ROOT / "config" / "podcasts.json"
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
USER_AGENT = "podcast-observational-research/0.1"
NUMBERED = re.compile(r"^#\s*(\d+)\b", re.IGNORECASE)
MMA = re.compile(r"^JRE MMA Show #\s*(\d+)\b", re.IGNORECASE)


class ArchiveError(RuntimeError):
    """An expected archive-building failure with a readable message."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_duration(value: str | None) -> float:
    """Parse RSS duration expressed as seconds or HH:MM:SS."""

    if not value:
        raise ArchiveError("Eligible RSS item has no duration")
    value = value.strip()
    if value.isdigit():
        return float(value)
    parts = value.split(":")
    if not all(part.isdigit() for part in parts) or len(parts) not in {2, 3}:
        raise ArchiveError(f"Unsupported RSS duration: {value}")
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        return float(minutes * 60 + seconds)
    hours, minutes, seconds = numbers
    return float(hours * 3600 + minutes * 60 + seconds)


def episode_kind_and_number(title: str) -> tuple[str, int] | None:
    """Apply the documented JRE archive inclusion rule."""

    if "fight companion" in title.casefold():
        return None
    match = MMA.match(title)
    if match:
        return "mma", int(match.group(1))
    match = NUMBERED.match(title)
    if match:
        return "numbered", int(match.group(1))
    return None


def episode_id(title: str, guid: str | None = None) -> str:
    kind_number = episode_kind_and_number(title)
    if kind_number is None:
        raise ArchiveError(f"Cannot identify ineligible episode: {title}")
    kind, number = kind_number
    base = f"jre-mma-{number}" if kind == "mma" else f"jre-{number}"
    if not guid:
        return base
    return f"{base}-{sha256_bytes(guid.encode('utf-8'))[:12]}"


def guest_label(title: str) -> str:
    if " with " in title:
        return title.split(" with ", 1)[1].strip()
    match = re.search(r"\s[-–—]\s(.+)$", title)
    if match:
        return match.group(1).strip()
    return "Guest not encoded in RSS title"


def parse_rss(xml_bytes: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ArchiveError(f"RSS snapshot is invalid XML: {exc}") from exc
    duration_tag = "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration"
    rows: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        kind_number = episode_kind_and_number(title)
        if kind_number is None:
            continue
        enclosure = item.find("enclosure")
        guid = (item.findtext("guid") or "").strip()
        published = item.findtext("pubDate")
        enclosure_url = enclosure.get("url") if enclosure is not None else None
        if not guid or not enclosure_url or not published:
            raise ArchiveError(f"Eligible RSS item is incomplete: {title}")
        try:
            published_at = parsedate_to_datetime(published).astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise ArchiveError(f"Invalid publication date for {title}") from exc
        kind, number = kind_number
        rows.append(
            {
                "title": title,
                "description": item.findtext("description"),
                "published_at": published_at.isoformat(),
                "published_date": published_at.date().isoformat(),
                "guid": guid,
                "duration_declared": item.findtext(duration_tag),
                "duration_seconds": parse_duration(item.findtext(duration_tag)),
                "enclosure_url": enclosure_url,
                "enclosure_type": enclosure.get("type") if enclosure is not None else None,
                "episode_kind": kind,
                "episode_number": number,
                "guest_name": guest_label(title),
            }
        )
    if not rows:
        raise ArchiveError("RSS snapshot contains no eligible JRE episodes")
    guids = [row["guid"] for row in rows]
    semantic_ids = [episode_id(row["title"], row["guid"]) for row in rows]
    if len(set(guids)) != len(guids):
        raise ArchiveError("Eligible RSS GUIDs are not unique")
    if len(set(semantic_ids)) != len(semantic_ids):
        raise ArchiveError("Eligible episode numbers are not unique")
    return sorted(rows, key=lambda row: row["published_at"], reverse=True)


def fetch_rss(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise ArchiveError(f"Could not fetch official RSS feed: {exc}") from exc


def existing_guid_map(raw_episode_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not raw_episode_root.is_dir():
        return result
    for metadata_path in raw_episode_root.glob("*/rss_metadata.json"):
        try:
            document = json.loads(metadata_path.read_text(encoding="utf-8"))
            guid = str(document["episode"]["guid"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ArchiveError(f"Invalid existing raw metadata: {metadata_path}") from exc
        prior = result.setdefault(guid, metadata_path.parent.name)
        if prior != metadata_path.parent.name:
            raise ArchiveError(f"RSS GUID occurs in multiple raw directories: {guid}")
    return result


def write_bytes_once(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise ArchiveError(f"Existing immutable file differs: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(value)
    except FileExistsError as exc:
        raise ArchiveError(f"Refusing to overwrite existing file: {path}") from exc


def write_json_once(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ArchiveError(f"Existing JSON is invalid: {path}") from exc
        if existing != document:
            raise ArchiveError(f"Existing immutable JSON differs: {path}")
        return
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError as exc:
        raise ArchiveError(f"Refusing to overwrite existing file: {path}") from exc


def build_documents(
    rows: list[dict[str, Any]],
    *,
    show: dict[str, Any],
    accessed_at: str,
    snapshot_path: Path,
    snapshot_sha256: str,
    existing: dict[str, str],
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    episodes: list[dict[str, Any]] = []
    metadata_documents: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        identifier = existing.get(row["guid"], episode_id(row["title"], row["guid"]))
        episodes.append(
            {
                "episode_id": identifier,
                "rss_guid": row["guid"],
                "published_date": row["published_date"],
                "guest_name": row["guest_name"],
                "duration_seconds": row["duration_seconds"],
                "episode_kind": row["episode_kind"],
                "episode_number": row["episode_number"],
            }
        )
        if row["guid"] in existing:
            continue
        episode = {
            key: row[key]
            for key in (
                "title", "description", "published_at", "guid",
                "duration_declared", "enclosure_url", "enclosure_type",
            )
        }
        metadata_documents.append(
            (
                identifier,
                {
                    "schema_version": "0.2",
                    "accessed_at": accessed_at,
                    "episode_id": identifier,
                    "podcast": {
                        "show_id": "jre",
                        "name": show["name"],
                        "hosts": show["hosts"],
                        "guest_label_candidate": row["guest_name"],
                        "speaker_identities_verified": False,
                    },
                    "episode": episode,
                    "episode_metadata_source": "immutable official podcast RSS snapshot",
                    "rss_feed_url": show["rss_url"],
                    "rss_snapshot": {
                        "relative_path": str(snapshot_path.relative_to(PROJECT_ROOT)),
                        "sha256": snapshot_sha256,
                    },
                    "match": {"method": "RSS inclusion rule", "human_verified": False},
                    "media": {
                        "source": "official podcast RSS enclosure",
                        "retained_locally": False,
                        "delivery": "rss-direct",
                        "duration_seconds": row["duration_seconds"],
                    },
                },
            )
        )
    manifest = {
        "schema_version": "0.2",
        "sample_id": f"jre_full_rss_archive_{accessed_at[:10]}",
        "show_id": "jre",
        "selected_at": accessed_at[:10],
        "selection_rule": (
            "Include numbered JRE and JRE MMA Show releases in the official RSS "
            "snapshot; exclude Fight Companion and unnumbered specials."
        ),
        "source": {
            "rss_url": show["rss_url"],
            "snapshot_relative_path": str(snapshot_path.relative_to(PROJECT_ROOT)),
            "snapshot_sha256": snapshot_sha256,
        },
        "storage_strategy": "metadata_only_rss_direct_transcription",
        "episodes": episodes,
    }
    return manifest, metadata_documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-date", required=True, help="Access date in YYYY-MM-DD")
    parser.add_argument(
        "--manifest",
        help="Output manifest path inside the project (default: dated config file)",
    )
    parser.add_argument(
        "--latest",
        type=int,
        help="Freeze only the most recent eligible RSS episodes",
    )
    parser.add_argument("--yes", action="store_true", help="Write the frozen files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        try:
            datetime.strptime(args.snapshot_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ArchiveError("--snapshot-date must use YYYY-MM-DD") from exc
        if args.latest is not None and args.latest < 1:
            raise ArchiveError("--latest must be a positive integer")
        config = json.loads(PODCAST_CONFIG.read_text(encoding="utf-8"))
        show = config["podcasts"]["jre"]
        raw_episode_root = RAW_ROOT / "transcripts" / show["raw_directory"]
        snapshot_path = (
            RAW_ROOT / "rss" / show["raw_directory"] / f"jre_rss_{args.snapshot_date}.xml"
        )
        manifest_path = (
            (PROJECT_ROOT / args.manifest).resolve()
            if args.manifest
            else PROJECT_ROOT / "config" / f"jre_full_archive_{args.snapshot_date}.json"
        )
        if not manifest_path.is_relative_to(PROJECT_ROOT):
            raise ArchiveError("Manifest path must stay inside this project")
        xml_bytes = snapshot_path.read_bytes() if snapshot_path.is_file() else fetch_rss(
            show["rss_url"]
        )
        rows = parse_rss(xml_bytes)
        if args.latest is not None:
            rows = rows[: args.latest]
        accessed_at = utc_now()
        manifest, metadata_documents = build_documents(
            rows,
            show=show,
            accessed_at=accessed_at,
            snapshot_path=snapshot_path,
            snapshot_sha256=sha256_bytes(xml_bytes),
            existing=existing_guid_map(raw_episode_root),
        )
        if args.latest is not None:
            manifest["sample_id"] = (
                f"jre_latest_{args.latest}_rss_archive_{accessed_at[:10]}"
            )
            manifest["selection_rule"] += (
                f" Freeze the {args.latest} most recent eligible releases in that snapshot."
            )
        total_hours = sum(row["duration_seconds"] for row in rows) / 3600
        print("JRE metadata-only archive plan")
        print(f"  Eligible episodes: {len(rows):,}")
        print(f"  Duration:          {total_hours:,.2f} hours")
        print(f"  Existing records:  {len(rows) - len(metadata_documents):,}")
        print(f"  New raw metadata:  {len(metadata_documents):,}")
        print(f"  RSS snapshot:      {snapshot_path.relative_to(PROJECT_ROOT)}")
        print(f"  Manifest:          {manifest_path.relative_to(PROJECT_ROOT)}")
        if not args.yes:
            print("\nDry run only. Add --yes to write immutable metadata and the manifest.")
            return 0
        write_bytes_once(snapshot_path, xml_bytes)
        write_json_once(manifest_path, manifest)
        for identifier, document in metadata_documents:
            write_json_once(raw_episode_root / identifier / "rss_metadata.json", document)
        print(f"\nCreated {len(metadata_documents):,} metadata-only episode records.")
        return 0
    except (ArchiveError, KeyError, json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
