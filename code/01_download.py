#!/usr/bin/env python3
"""Download selected YouTube podcast episodes and document them from RSS.

The YouTube URL selects the media file. The podcast's official RSS feed is the
authoritative source for episode title, publication date, description, GUID,
and the regular host. The input can be one video or a frozen JSON sample. Raw
files are created once and never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

try:
    import yt_dlp
except ModuleNotFoundError:  # Give a clearer message than a Python traceback.
    yt_dlp = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "podcasts.json"
RAW_TRANSCRIPTS = PROJECT_ROOT / "data" / "raw" / "transcripts"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
EPISODE_NUMBER_PATTERN = re.compile(r"#\s*(\d+)\b")
USER_AGENT = "podcast-observational-research/0.1"


class DownloadError(RuntimeError):
    """An expected download or matching failure with a readable message."""


@dataclass(frozen=True)
class PodcastConfig:
    show_id: str
    name: str
    raw_directory: str
    rss_url: str
    youtube_channels: tuple[str, ...]
    hosts: tuple[str, ...]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_youtube_id(value: str) -> str:
    """Extract the stable 11-character ID from common YouTube URLs."""

    from urllib.parse import parse_qs, urlparse

    value = value.strip()
    if VIDEO_ID_PATTERN.fullmatch(value):
        return value

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            candidate = parsed.path.split("/")[2]
        else:
            candidate = ""
    elif host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    else:
        candidate = ""

    if not VIDEO_ID_PATTERN.fullmatch(candidate):
        raise DownloadError(f"Not a recognized YouTube URL or video ID: {value}")
    return candidate


def load_config(show_id: str) -> PodcastConfig:
    try:
        document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        item = document["podcasts"][show_id]
        return PodcastConfig(
            show_id=show_id,
            name=item["name"],
            raw_directory=item["raw_directory"],
            rss_url=item["rss_url"],
            youtube_channels=tuple(item["youtube_channels"]),
            hosts=tuple(item["hosts"]),
        )
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        raise DownloadError(f"Invalid or missing show '{show_id}' in {CONFIG_PATH}") from exc


def youtube_metadata(url: str) -> dict[str, Any]:
    """Read only the YouTube fields needed to validate and match the video."""

    if yt_dlp is None:
        raise DownloadError(
            "yt-dlp is not installed in this Python environment. Run: "
            "python -m pip install yt-dlp==2026.8.19"
        )

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(f"yt-dlp could not read the YouTube video: {exc}") from exc

    if info.get("_type") == "playlist":
        raise DownloadError("Expected one video, but YouTube returned a playlist")
    return {
        "video_id": info["id"],
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration_seconds": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
    }


def fetch_rss_items(feed_url: str) -> list[dict[str, Any]]:
    """Retrieve episode records from the podcast publisher's RSS feed."""

    request = urllib.request.Request(feed_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            root = ET.fromstring(response.read())
    except (urllib.error.URLError, ET.ParseError) as exc:
        raise DownloadError(f"Could not read RSS feed {feed_url}: {exc}") from exc

    duration_tag = "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration"
    items: list[dict[str, Any]] = []
    for element in root.findall("./channel/item"):
        enclosure = element.find("enclosure")
        published = element.findtext("pubDate")
        try:
            published_at = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            published_at = None

        items.append(
            {
                "title": element.findtext("title"),
                "description": element.findtext("description"),
                "published_at": published_at,
                "guid": element.findtext("guid"),
                "duration_declared": element.findtext(duration_tag),
                "enclosure_url": enclosure.get("url") if enclosure is not None else None,
                "enclosure_type": enclosure.get("type") if enclosure is not None else None,
            }
        )
    return items


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = re.sub(r"\b(the )?joe rogan experience\b", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def match_rss_episode(youtube_title: str, items: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Require one unambiguous RSS match; never silently choose among candidates."""

    episode_number = EPISODE_NUMBER_PATTERN.search(youtube_title)
    if episode_number:
        number = episode_number.group(1)
        candidates = [
            item
            for item in items
            if item["title"] and re.search(rf"#\s*{re.escape(number)}\b", item["title"])
        ]
        if len(candidates) == 1:
            return candidates[0], f"unique episode number #{number}"
        if len(candidates) > 1:
            raise DownloadError(f"RSS contains multiple items for episode #{number}")

    normalized = normalize_title(youtube_title)
    candidates = [
        item for item in items if item["title"] and normalize_title(item["title"]) == normalized
    ]
    if len(candidates) == 1:
        return candidates[0], "unique normalized title"
    raise DownloadError("No unique RSS match; inspect this episode manually")


def match_rss_guid(rss_guid: str, items: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Match a pre-registered RSS GUID and require it to be unique."""

    candidates = [item for item in items if item["guid"] == rss_guid]
    if len(candidates) == 1:
        return candidates[0], "pre-registered unique RSS GUID"
    if not candidates:
        raise DownloadError(f"RSS GUID is not present in the current feed: {rss_guid}")
    raise DownloadError(f"RSS GUID occurs more than once in the feed: {rss_guid}")


def guest_label(title: str) -> str | None:
    """Extract a metadata candidate, not a verified voice identity."""

    match = re.search(r"#\s*\d+\s*[-–—]\s*(.+)$", title)
    return match.group(1).strip() if match else None


def download_youtube_audio(url: str, episode_dir: Path, video_id: str) -> Path:
    """Download the best available M4A using the user's requested yt-dlp method."""

    if yt_dlp is None:
        raise DownloadError("yt-dlp is not installed in this Python environment")

    episode_dir.mkdir(parents=True, exist_ok=True)
    destination = episode_dir / f"{video_id}.m4a"
    if destination.exists():
        print(f"Reusing existing raw audio: {destination.relative_to(PROJECT_ROOT)}")
        return destination

    # This is the same core configuration as the researcher's example. The
    # stable video ID replaces the title so filenames cannot change over time.
    ydl_options = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(episode_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "overwrites": False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(f"yt-dlp could not download the YouTube audio: {exc}") from exc

    if not destination.exists():
        alternatives = [
            path
            for path in episode_dir.glob(f"{video_id}.*")
            if not path.name.endswith((".part", ".json"))
        ]
        if len(alternatives) == 1:
            raise DownloadError(
                f"YouTube did not provide M4A; downloaded {alternatives[0].suffix} instead"
            )
        raise DownloadError("yt-dlp finished, but the expected M4A file was not found")
    return destination


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_audio(path: Path) -> dict[str, Any]:
    """Measure the actual file instead of trusting platform duration fields."""

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return {"status": "not_run", "reason": "ffprobe not installed"}
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration,size,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DownloadError(f"ffprobe could not validate {path}: {result.stderr.strip()}")
    raw = json.loads(result.stdout)["format"]
    return {
        "status": "ok",
        "format_name": raw.get("format_name"),
        "duration_seconds": float(raw["duration"]),
        "bytes": int(raw["size"]),
        "bit_rate": int(raw["bit_rate"]),
    }


def write_metadata_once(path: Path, document: dict[str, Any]) -> None:
    """Create immutable raw metadata and fail rather than overwrite it."""

    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError:
        print(f"Raw metadata already exists; not overwritten: {path.relative_to(PROJECT_ROOT)}")


def project_config_path(value: str) -> Path:
    """Resolve a configuration path without allowing reads outside this project."""

    path = (PROJECT_ROOT / value).resolve()
    if not path.is_relative_to(PROJECT_ROOT):
        raise DownloadError("The sample configuration must be inside this project")
    return path


def load_sample(path: Path) -> tuple[str, list[dict[str, str]]]:
    """Load and validate a frozen list of YouTube IDs and RSS GUIDs."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        show_id = document["show_id"]
        episodes = document["episodes"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError, TypeError) as exc:
        raise DownloadError(f"Invalid sample configuration: {path}") from exc

    if not isinstance(episodes, list) or not episodes:
        raise DownloadError("The sample must contain at least one episode")

    requests: list[dict[str, str]] = []
    video_ids: set[str] = set()
    rss_guids: set[str] = set()
    for number, episode in enumerate(episodes, start=1):
        try:
            video_id = extract_youtube_id(episode["youtube_id"])
            rss_guid = episode["rss_guid"].strip()
        except (KeyError, AttributeError) as exc:
            raise DownloadError(f"Invalid episode {number} in sample configuration") from exc
        if not rss_guid:
            raise DownloadError(f"Episode {number} has an empty RSS GUID")
        if video_id in video_ids or rss_guid in rss_guids:
            raise DownloadError(f"Episode {number} duplicates a video ID or RSS GUID")
        video_ids.add(video_id)
        rss_guids.add(rss_guid)
        requests.append(
            {
                "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
                "rss_guid": rss_guid,
            }
        )
    return show_id, requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("youtube_url", nargs="?", help="One YouTube video URL")
    inputs.add_argument("--sample", help="Frozen sample JSON inside this project")
    parser.add_argument("--show", help="Show ID in config/podcasts.json")
    parser.add_argument(
        "--rss-guid",
        help="Pre-registered RSS GUID for a single video whose title is not an exact match",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm downloading every episode in a sample",
    )
    return parser.parse_args()


def acquire_episode(
    podcast: PodcastConfig,
    rss_items: list[dict[str, Any]],
    youtube_url: str,
    rss_guid: str | None = None,
) -> None:
    """Validate and acquire one episode without overwriting accepted raw files."""

    video_id = extract_youtube_id(youtube_url)
    youtube = youtube_metadata(youtube_url)
    if youtube["video_id"] != video_id:
        raise DownloadError("The returned YouTube ID differs from the requested ID")
    if youtube["channel"] not in podcast.youtube_channels:
        raise DownloadError(
            f"YouTube channel '{youtube['channel']}' is not configured for {podcast.name}"
        )

    if rss_guid:
        rss, match_method = match_rss_guid(rss_guid, rss_items)
    else:
        rss, match_method = match_rss_episode(youtube["title"], rss_items)
    episode_dir = RAW_TRANSCRIPTS / podcast.raw_directory / video_id
    audio_path = download_youtube_audio(youtube_url, episode_dir, video_id)
    measured = probe_audio(audio_path)

    metadata = {
        "schema_version": "0.1",
        "accessed_at": utc_now(),
        "podcast": {
            "show_id": podcast.show_id,
            "name": podcast.name,
            "hosts": list(podcast.hosts),
            "guest_label_candidate": guest_label(rss["title"]),
            "speaker_identities_verified": False,
        },
        "episode": rss,
        "episode_metadata_source": "official podcast RSS feed",
        "rss_feed_url": podcast.rss_url,
        "youtube": youtube,
        "match": {"method": match_method, "human_verified": False},
        "media": {
            "source": "YouTube",
            "relative_path": str(audio_path.relative_to(PROJECT_ROOT)),
            "sha256": sha256_file(audio_path),
            "yt_dlp_version": yt_dlp.version.__version__,
            "measured": measured,
        },
    }
    metadata_path = episode_dir / "rss_metadata.json"
    write_metadata_once(metadata_path, metadata)

    print(f"Episode: {rss['title']}")
    print(f"Published: {rss['published_at']}")
    print(f"RSS match: {match_method}")
    print(f"Audio: {audio_path.relative_to(PROJECT_ROOT)}")
    print(f"Metadata: {metadata_path.relative_to(PROJECT_ROOT)}")
    print(f"SHA-256: {metadata['media']['sha256']}")
    print(f"Measured duration: {measured.get('duration_seconds')} seconds")


def main() -> int:
    args = parse_args()
    try:
        if args.sample:
            if args.rss_guid:
                raise DownloadError("--rss-guid applies only to a single YouTube URL")
            sample_path = project_config_path(args.sample)
            sample_show, requests = load_sample(sample_path)
            if args.show and args.show != sample_show:
                raise DownloadError("--show does not match the sample configuration")
            show_id = sample_show
            print("Podcast acquisition plan")
            print(f"  Sample:      {sample_path.relative_to(PROJECT_ROOT)}")
            print(f"  Episodes:    {len(requests)}")
            print("  Destination: data/raw/transcripts/ (local; ignored by Git)")
            if not args.yes:
                print("No files downloaded. Add --yes after reviewing this plan.")
                return 0
        else:
            if not args.show:
                raise DownloadError("--show is required with a single YouTube URL")
            show_id = args.show
            requests = [{"youtube_url": args.youtube_url, "rss_guid": args.rss_guid}]

        podcast = load_config(show_id)
        rss_items = fetch_rss_items(podcast.rss_url)
        failures: list[str] = []
        for number, request in enumerate(requests, start=1):
            print(f"\n[{number}/{len(requests)}] {request['youtube_url']}")
            try:
                acquire_episode(
                    podcast,
                    rss_items,
                    request["youtube_url"],
                    request.get("rss_guid"),
                )
            except DownloadError as exc:
                failures.append(f"{request['youtube_url']}: {exc}")
                print(f"ERROR: {exc}", file=sys.stderr)

        print(f"\nCompleted: {len(requests) - len(failures)}/{len(requests)} episodes")
        if failures:
            print("Failed episodes:", file=sys.stderr)
            for failure in failures:
                print(f"  {failure}", file=sys.stderr)
            return 2
        return 0
    except DownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
