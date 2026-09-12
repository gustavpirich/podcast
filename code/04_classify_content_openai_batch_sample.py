#!/usr/bin/env python3
"""Run the OpenAI window classifier over a frozen podcast sample.

The single-episode script remains authoritative. This runner validates the
sample, reports episode/window counts, and invokes that script once per episode
for the requested stage. Existing submitted or collected episodes are skipped,
so interrupted work can be resumed safely.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PODCAST_CONFIG = PROJECT_ROOT / "config" / "podcasts.json"
CLASSIFIER_CONFIG = PROJECT_ROOT / "config" / "openai_content_classification.json"
SINGLE_EPISODE_SCRIPT = PROJECT_ROOT / "code" / "04_classify_content_openai_batch.py"
TRANSCRIPTS = PROJECT_ROOT / "data" / "derived" / "transcripts"
EPISODE_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "derived" / "classifications" / "openai_batch"
)
SAMPLE_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "derived" / "classifications" / "openai_batch_samples"
)
DEFAULT_SAMPLE = "config/doac_starter_sample.json"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


class SampleClassificationError(RuntimeError):
    """An expected sample, input, state, or child-process failure."""


@dataclass(frozen=True)
class Episode:
    video_id: str
    title: str
    words: int
    windows: int
    run_id: str | None
    state: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    if not path.is_relative_to(PROJECT_ROOT):
        raise SampleClassificationError("The sample configuration must be inside this project")
    return path


def episode_state(show_directory: str, video_id: str) -> tuple[str | None, str]:
    output = EPISODE_OUTPUT_ROOT / show_directory / video_id
    pointer = output / "latest_prepared_run.json"
    if not pointer.is_file():
        return None, "not-prepared"
    try:
        run_id = str(json.loads(pointer.read_text(encoding="utf-8"))["run_id"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SampleClassificationError(f"Invalid prepared-run pointer for {video_id}") from exc
    run_dir = output / run_id
    manifest_path = run_dir / "request_manifest.json"
    if not manifest_path.is_file():
        raise SampleClassificationError(f"Missing request manifest for {video_id}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded_config_hash = manifest["input"]["configuration_sha256"]
        recorded_transcript_hash = manifest["input"]["transcript_sha256"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SampleClassificationError(f"Invalid request manifest for {video_id}") from exc
    transcript_path = TRANSCRIPTS / show_directory / video_id / "transcript.json"
    if recorded_config_hash != sha256_file(CLASSIFIER_CONFIG) or (
        recorded_transcript_hash != sha256_file(transcript_path)
    ):
        return run_id, "stale"
    if (run_dir / "window_classification.csv").is_file() and (
        run_dir / "classification_summary.json"
    ).is_file():
        return run_id, "collected"
    job_path = run_dir / "batch_job.json"
    if not job_path.is_file():
        return run_id, "prepared"
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SampleClassificationError(f"Invalid Batch job record for {video_id}") from exc
    if job.get("batch_id"):
        return run_id, "submitted"
    if job.get("input_file_id"):
        return run_id, "uploaded-not-submitted"
    raise SampleClassificationError(f"Unrecognized Batch job state for {video_id}")


def load_sample(sample_path: Path) -> tuple[str, str, list[Episode], dict[str, Any]]:
    try:
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        podcasts = json.loads(PODCAST_CONFIG.read_text(encoding="utf-8"))["podcasts"]
        classifier = json.loads(CLASSIFIER_CONFIG.read_text(encoding="utf-8"))
        sample_id = str(sample["sample_id"])
        show_id = str(sample["show_id"])
        show_directory = str(podcasts[show_id]["raw_directory"])
        rows = sample["episodes"]
        window_words = int(classifier["window_words"])
        stride_words = int(classifier["stride_words"])
        minimum_words = int(classifier["minimum_episode_words"])
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SampleClassificationError(f"Invalid sample or project configuration: {sample_path}") from exc
    if not re.fullmatch(r"[A-Za-z0-9._-]+", sample_id):
        raise SampleClassificationError("sample_id is not a safe folder name")
    if not isinstance(rows, list) or not rows:
        raise SampleClassificationError("The frozen sample contains no episodes")

    episodes: list[Episode] = []
    seen: set[str] = set()
    for number, row in enumerate(rows, start=1):
        try:
            video_id = str(row["youtube_id"])
        except (KeyError, TypeError) as exc:
            raise SampleClassificationError(f"Sample episode {number} has no YouTube ID") from exc
        if not VIDEO_ID_PATTERN.fullmatch(video_id) or video_id in seen:
            raise SampleClassificationError(f"Invalid or duplicate YouTube ID: {video_id}")
        seen.add(video_id)
        transcript_path = TRANSCRIPTS / show_directory / video_id / "transcript.json"
        if not transcript_path.is_file():
            raise SampleClassificationError(f"Missing transcript: {transcript_path}")
        try:
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            episode_record = transcript["episode"]
            recorded_id = episode_record["youtube_video_id"]
            title = str(episode_record["title"])
            utterances = transcript["utterances"]
            words = sum(len(utterance["words"]) for utterance in utterances)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SampleClassificationError(f"Invalid transcript for {video_id}") from exc
        if recorded_id != video_id:
            raise SampleClassificationError(f"Transcript ID mismatch for {video_id}")
        if words < minimum_words:
            raise SampleClassificationError(
                f"Episode {video_id} has {words} words; {minimum_words} required"
            )
        windows = 1 + (words - window_words) // stride_words
        run_id, state = episode_state(show_directory, video_id)
        episodes.append(Episode(video_id, title, words, windows, run_id, state))
    return sample_id, show_directory, episodes, classifier


def child_command(stage: str, show_directory: str, episode: Episode, yes: bool) -> list[str]:
    command = [
        sys.executable,
        str(SINGLE_EPISODE_SCRIPT),
        stage,
        "--show-directory",
        show_directory,
        "--video-id",
        episode.video_id,
    ]
    if episode.run_id and stage != "prepare":
        command.extend(["--run-id", episode.run_id])
    if stage == "submit" and yes:
        command.append("--yes")
    return command


def run_children(
    stage: str,
    show_directory: str,
    episodes: list[Episode],
    *,
    yes: bool = False,
) -> list[tuple[str, int]]:
    failures: list[tuple[str, int]] = []
    for number, episode in enumerate(episodes, start=1):
        print(f"\n{stage.capitalize()} [{number}/{len(episodes)}]: {episode.video_id} — {episode.title}")
        result = subprocess.run(
            child_command(stage, show_directory, episode, yes), check=False
        )
        if result.returncode:
            failures.append((episode.video_id, result.returncode))
    return failures


def sample_run_id(sample_path: Path) -> str:
    digest = hashlib.sha256(sample_path.read_bytes() + b"\0" + CLASSIFIER_CONFIG.read_bytes())
    return digest.hexdigest()[:12]


def aggregate(
    sample_path: Path,
    sample_id: str,
    show_directory: str,
    episodes: list[Episode],
    classifier: dict[str, Any],
) -> Path:
    refreshed = [episode_state(show_directory, item.video_id) for item in episodes]
    incomplete = [
        episodes[index].video_id
        for index, (_, state) in enumerate(refreshed)
        if state != "collected"
    ]
    if incomplete:
        raise SampleClassificationError(
            "Cannot aggregate until every episode is collected: " + ", ".join(incomplete)
        )

    combined: list[dict[str, str]] = []
    episode_summaries: list[dict[str, Any]] = []
    fields: list[str] | None = None
    for episode, (run_id, _) in zip(episodes, refreshed):
        assert run_id is not None
        run_dir = EPISODE_OUTPUT_ROOT / show_directory / episode.video_id / run_id
        with (run_dir / "window_classification.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            current_fields = reader.fieldnames
            if not current_fields:
                raise SampleClassificationError(f"Empty classification CSV for {episode.video_id}")
            if fields is None:
                fields = current_fields
            elif current_fields != fields:
                raise SampleClassificationError("Episode classification columns differ")
            rows = list(reader)
        if len(rows) != episode.windows:
            raise SampleClassificationError(f"Window count mismatch for {episode.video_id}")
        combined.extend(rows)
        summary = json.loads((run_dir / "classification_summary.json").read_text(encoding="utf-8"))
        episode_summaries.append(
            {
                "episode_id": episode.video_id,
                "title": episode.title,
                "run_id": run_id,
                "words": episode.words,
                "windows": len(rows),
                "health_related_windows": sum(int(row["health_related"]) for row in rows),
                "science_related_windows": sum(int(row["science_related"]) for row in rows),
                "health_and_science_windows": sum(
                    int(row["health_related"]) and int(row["science_related"])
                    for row in rows
                ),
                "batch_id": summary["method"]["batch_id"],
            }
        )

    assert fields is not None
    run_id = sample_run_id(sample_path)
    output = SAMPLE_OUTPUT_ROOT / sample_id / run_id
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(combined)
    atomic_write(output / "window_classification.csv", buffer.getvalue())
    health = sum(int(row["health_related"]) for row in combined)
    science = sum(int(row["science_related"]) for row in combined)
    both = sum(
        int(row["health_related"]) and int(row["science_related"])
        for row in combined
    )
    total = len(combined)
    write_json(
        output / "classification_summary.json",
        {
            "schema_version": "0.1",
            "generated_at": utc_now(),
            "status": "provisional_model_assisted_not_human_validated",
            "sample_id": sample_id,
            "sample_run_id": run_id,
            "show_directory": show_directory,
            "sample_configuration": str(sample_path.relative_to(PROJECT_ROOT)),
            "classifier_configuration": str(CLASSIFIER_CONFIG.relative_to(PROJECT_ROOT)),
            "model_requested": classifier["model"],
            "unit": "overlapping_256_word_window",
            "episodes": episode_summaries,
            "totals": {
                "episodes": len(episodes),
                "words": sum(item.words for item in episodes),
                "windows": total,
                "health_related_windows": health,
                "science_related_windows": science,
                "health_and_science_windows": both,
                "health_related_share_of_windows": round(health / total, 6),
                "science_related_share_of_windows": round(science / total, 6),
                "health_and_science_share_of_windows": round(both / total, 6),
            },
            "interpretation_note": (
                "Windows overlap by 128 words. Shares describe classified windows, not "
                "non-overlapping shares of words, time, claims, or speaker speech."
            ),
        },
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "submit", "status", "collect", "aggregate")
    )
    parser.add_argument(
        "--sample",
        default=DEFAULT_SAMPLE,
        help=f"Frozen sample JSON inside this project (default: {DEFAULT_SAMPLE})",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Confirm transcript upload and API charges"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        sample_path = project_path(args.sample)
        sample_id, show_directory, episodes, classifier = load_sample(sample_path)
        print("OpenAI Batch sample classification plan")
        print(f"  Sample:       {sample_id}")
        print(f"  Episodes:     {len(episodes)}")
        print(f"  Words:        {sum(item.words for item in episodes):,}")
        print(f"  Windows:      {sum(item.windows for item in episodes):,}")
        print(
            f"  Window rule:  {classifier['window_words']} words, "
            f"stride {classifier['stride_words']}"
        )
        print(f"  Labels:       health_related; science_related")
        print(f"  Model:        {classifier['model']}")
        for item in episodes:
            print(
                f"    {item.video_id} | {item.words:>6,} words | "
                f"{item.windows:>3} windows | {item.state}"
            )

        if args.command == "prepare":
            targets = [
                item for item in episodes if item.state in {"not-prepared", "stale"}
            ]
            if not targets:
                print("\nEvery episode is already prepared.")
                return 0
            failures = run_children("prepare", show_directory, targets)
        elif args.command == "submit":
            invalid = [
                item.video_id
                for item in episodes
                if item.state in {"not-prepared", "stale"}
            ]
            if invalid:
                raise SampleClassificationError(
                    "Run prepare first for: " + ", ".join(invalid)
                )
            targets = [
                item
                for item in episodes
                if item.state in {"prepared", "uploaded-not-submitted"}
            ]
            if not targets:
                print("\nEvery episode has already been submitted or collected.")
                return 0
            print(
                "\nExternal action: upload transcript excerpts and create "
                f"{len(targets)} billable 24-hour batches."
            )
            if not args.yes:
                raise SampleClassificationError("Nothing submitted. Review the plan, then add --yes")
            if not os.environ.get("OPENAI_API_KEY", "").strip():
                raise SampleClassificationError(
                    "OPENAI_API_KEY is not set in this terminal; never put it in project files"
                )
            failures = run_children("submit", show_directory, targets, yes=True)
        elif args.command == "status":
            targets = [item for item in episodes if item.state == "submitted"]
            if not targets:
                print("\nNo submitted, uncollected episodes need a status check.")
                return 0
            failures = run_children("status", show_directory, targets)
        elif args.command == "collect":
            targets = [item for item in episodes if item.state == "submitted"]
            if not targets:
                output = aggregate(
                    sample_path, sample_id, show_directory, episodes, classifier
                )
                print(f"\nAll episodes were already collected. Aggregated output: {output.relative_to(PROJECT_ROOT)}")
                return 0
            failures = run_children("collect", show_directory, targets)
            if not failures:
                _, _, refreshed, _ = load_sample(sample_path)
                output = aggregate(
                    sample_path, sample_id, show_directory, refreshed, classifier
                )
                print(f"\nAggregated output: {output.relative_to(PROJECT_ROOT)}")
        else:
            output = aggregate(sample_path, sample_id, show_directory, episodes, classifier)
            print(f"\nAggregated output: {output.relative_to(PROJECT_ROOT)}")
            return 0

        if failures:
            print("\nFailed episodes:", file=sys.stderr)
            for video_id, returncode in failures:
                print(f"  {video_id}: child exit {returncode}", file=sys.stderr)
            return 2
        return 0
    except (SampleClassificationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
