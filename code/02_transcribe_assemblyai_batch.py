#!/usr/bin/env python3
"""Submit and collect a frozen podcast sample with AssemblyAI.

This orchestrator keeps the single-episode transcription script authoritative.
It first submits every unfinished episode so AssemblyAI can process the jobs in
parallel, then resumes each job and writes its diarized transcript. Completed
episodes are skipped, and the API key is inherited from the terminal environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PODCAST_CONFIG = PROJECT_ROOT / "config" / "podcasts.json"
SINGLE_EPISODE_SCRIPT = PROJECT_ROOT / "code" / "02_transcribe_assemblyai.py"
RAW_TRANSCRIPTS = PROJECT_ROOT / "data" / "raw" / "transcripts"
DERIVED_TRANSCRIPTS = PROJECT_ROOT / "data" / "derived" / "transcripts"
DEFAULT_SAMPLE = "config/doac_starter_sample.json"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
FINAL_FILENAMES = (
    "transcript.md",
    "transcript.json",
    "assemblyai_response.json",
)


class BatchError(RuntimeError):
    """An expected batch configuration or input error."""


@dataclass(frozen=True)
class BatchEpisode:
    video_id: str
    rss_guid: str
    guest_name: str
    title: str
    duration_seconds: float
    state: str


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    if not path.is_relative_to(PROJECT_ROOT):
        raise BatchError("The sample configuration must be inside this project")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_state(show_directory: str, video_id: str) -> str:
    output_dir = DERIVED_TRANSCRIPTS / show_directory / video_id
    finals = [output_dir / name for name in FINAL_FILENAMES]
    existing = [path for path in finals if path.exists()]
    if len(existing) == len(finals):
        return "complete"
    if existing:
        names = ", ".join(path.name for path in existing)
        raise BatchError(f"Episode {video_id} has incomplete final outputs: {names}")
    if (output_dir / "assemblyai_job.json").exists():
        return "submitted/resumable"
    return "ready"


def load_batch(
    sample_path: Path,
) -> tuple[str, str, tuple[str, ...], list[BatchEpisode]]:
    """Validate the frozen sample against its immutable local audio metadata."""

    try:
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        podcasts = json.loads(PODCAST_CONFIG.read_text(encoding="utf-8"))["podcasts"]
        show_id = sample["show_id"]
        show = podcasts[show_id]
        show_directory = show["raw_directory"]
        hosts = tuple(str(value).strip() for value in show["hosts"])
        rows = sample["episodes"]
    except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BatchError(f"Invalid sample or podcast configuration: {sample_path}") from exc

    if not isinstance(rows, list) or not rows:
        raise BatchError("The sample contains no episodes")
    if not hosts or any(not value for value in hosts):
        raise BatchError(f"Show {show_id} has no valid configured host")

    episodes: list[BatchEpisode] = []
    video_ids: set[str] = set()
    rss_guids: set[str] = set()
    for number, row in enumerate(rows, start=1):
        try:
            video_id = row["youtube_id"].strip()
            rss_guid = row["rss_guid"].strip()
            guest_name = row["guest_name"].strip()
        except (KeyError, AttributeError) as exc:
            raise BatchError(f"Sample episode {number} is missing a required value") from exc
        if not VIDEO_ID_PATTERN.fullmatch(video_id):
            raise BatchError(f"Sample episode {number} has an invalid YouTube ID")
        if not rss_guid or not guest_name:
            raise BatchError(f"Sample episode {number} has an empty GUID or guest name")
        if video_id in video_ids or rss_guid in rss_guids:
            raise BatchError(f"Sample episode {number} duplicates an identifier")
        video_ids.add(video_id)
        rss_guids.add(rss_guid)

        episode_dir = RAW_TRANSCRIPTS / show_directory / video_id
        audio_path = episode_dir / f"{video_id}.m4a"
        metadata_path = episode_dir / "rss_metadata.json"
        if not audio_path.is_file() or not metadata_path.is_file():
            raise BatchError(f"Episode {video_id} is missing local audio or metadata")
        try:
            metadata: dict[str, Any] = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
            title = str(metadata["episode"]["title"])
            recorded_guid = metadata["episode"]["guid"]
            recorded_video_id = metadata["youtube"]["video_id"]
            expected_hash = metadata["media"]["sha256"]
            duration = float(metadata["media"]["measured"]["duration_seconds"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BatchError(f"Episode {video_id} has invalid raw metadata") from exc
        if recorded_guid != rss_guid or recorded_video_id != video_id:
            raise BatchError(f"Episode {video_id} does not match the frozen sample")
        if sha256_file(audio_path) != expected_hash:
            raise BatchError(f"Episode {video_id} failed its immutable-audio checksum")

        episodes.append(
            BatchEpisode(
                video_id=video_id,
                rss_guid=rss_guid,
                guest_name=guest_name,
                title=title,
                duration_seconds=duration,
                state=output_state(show_directory, video_id),
            )
        )
    return show_id, show_directory, hosts, episodes


def episode_command(
    show_directory: str,
    episode: BatchEpisode,
    *,
    submit_only: bool,
    retry_failed: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(SINGLE_EPISODE_SCRIPT),
        "--show-directory",
        show_directory,
        "--video-id",
        episode.video_id,
        "--guest-name",
        episode.guest_name,
        "--delivery",
        "local-upload",
        "--yes",
    ]
    if submit_only:
        command.append("--submit-only")
    if retry_failed:
        command.append("--retry-failed")
    return command


def run_phase(
    phase: str,
    show_directory: str,
    episodes: list[BatchEpisode],
    *,
    submit_only: bool,
    retry_failed: bool,
) -> tuple[list[BatchEpisode], list[tuple[str, int]]]:
    successful: list[BatchEpisode] = []
    failures: list[tuple[str, int]] = []
    for number, episode in enumerate(episodes, start=1):
        print(f"\n{phase} [{number}/{len(episodes)}]: {episode.video_id} — {episode.title}")
        result = subprocess.run(
            episode_command(
                show_directory,
                episode,
                submit_only=submit_only,
                retry_failed=retry_failed,
            ),
            check=False,
        )
        if result.returncode == 0:
            successful.append(episode)
        else:
            failures.append((episode.video_id, result.returncode))
    return successful, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        default=DEFAULT_SAMPLE,
        help=f"Frozen sample JSON inside this project (default: {DEFAULT_SAMPLE})",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the external, potentially billable AssemblyAI requests",
    )
    parser.add_argument(
        "--submit-only",
        action="store_true",
        help="Submit/resume all jobs but do not wait for or collect results",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Preserve failed job records and submit replacements",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        sample_path = project_path(args.sample)
        show_id, show_directory, hosts, episodes = load_batch(sample_path)
        total_hours = sum(item.duration_seconds for item in episodes) / 3600
        complete = [item for item in episodes if item.state == "complete"]
        unfinished = [item for item in episodes if item.state != "complete"]

        print("AssemblyAI batch transcription plan")
        print(f"  Sample:       {sample_path.relative_to(PROJECT_ROOT)}")
        print(f"  Show:         {show_id} ({show_directory})")
        print(f"  Episodes:     {len(episodes)} ({len(complete)} already complete)")
        print(f"  Audio:        {total_hours:.2f} hours")
        print("  Delivery:     local M4A upload")
        print("  Model:        universal-3-5-pro; universal-2 fallback")
        print("  Speakers:     diarization plus curated host/guest names")
        print("  Identification effort: medium (machine-inferred)")
        print("  Region:       US")
        print("  Output:       data/derived/transcripts/ (local; ignored by Git)")
        for episode in episodes:
            print(
                f"    {episode.video_id} | {episode.state:19} | "
                f"{' + '.join(hosts)} + {episode.guest_name}"
            )

        if not unfinished:
            print("\nAll sample transcripts are already complete.")
            return 0
        if not args.yes:
            print(
                "\nDry run only. Add --yes after checking your AssemblyAI balance "
                "and API key."
            )
            return 0
        if not os.environ.get("ASSEMBLYAI_API_KEY", "").strip():
            raise BatchError(
                "ASSEMBLYAI_API_KEY is not set in this terminal. Export it and rerun; "
                "never paste it into source code or chat."
            )

        submitted, submit_failures = run_phase(
            "Submit",
            show_directory,
            unfinished,
            submit_only=True,
            retry_failed=args.retry_failed,
        )
        if args.submit_only:
            print(
                f"\nSubmission phase finished: {len(submitted)}/{len(unfinished)} "
                "jobs submitted or resumed."
            )
            return 2 if submit_failures else 0

        collected, collect_failures = run_phase(
            "Collect",
            show_directory,
            submitted,
            submit_only=False,
            retry_failed=args.retry_failed,
        )
        failures = submit_failures + collect_failures
        print(
            f"\nBatch finished: {len(complete) + len(collected)}/{len(episodes)} "
            "transcripts complete."
        )
        if failures:
            print("Failed episodes:", file=sys.stderr)
            for video_id, returncode in failures:
                print(f"  {video_id}: child exit {returncode}", file=sys.stderr)
            return 2
        return 0
    except (BatchError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
