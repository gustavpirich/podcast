#!/usr/bin/env python3
"""Create provisional health/science labels for diarized transcript turns.

INPUTS
    data/derived/transcripts/<show-directory>/<video-id>/transcript.json
    data/raw/transcripts/<show-directory>/<video-id>/rss_metadata.json
    config/content_classification.json

OUTPUTS
    data/derived/classifications/<show-directory>/<video-id>/turn_classification.csv
    data/derived/classifications/<show-directory>/<video-id>/classification_summary.json

This is a transparent dictionary screen, not a validated content classifier.
Every positive and a deterministic sample of negatives are marked for review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "content_classification.json"
TRANSCRIPTS = PROJECT_ROOT / "data" / "derived" / "transcripts"
RAW_TRANSCRIPTS = PROJECT_ROOT / "data" / "raw" / "transcripts"
CLASSIFICATIONS = PROJECT_ROOT / "data" / "derived" / "classifications"


class ClassificationError(RuntimeError):
    """An expected input or validation failure with a readable message."""


def validate_path_component(value: str, option: str) -> str:
    """Require a single safe folder-name component from a CLI option."""

    if not re.fullmatch(r"[A-Za-z0-9._-]+", value) or value in {".", ".."}:
        raise ClassificationError(
            f"{option} must be one folder name using letters, numbers, '.', '_', or '-'"
        )
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value: str) -> str:
    """Lowercase text and replace punctuation with single spaces."""

    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def matched_rules(
    text: str,
    terms: Iterable[str],
    prefixes: Iterable[str],
) -> list[str]:
    """Return the visible dictionary rules that matched a turn."""

    normalized = normalize_text(text)
    padded = f" {normalized} "
    tokens = normalized.split()
    matches = {
        f"term:{term}"
        for term in terms
        if f" {normalize_text(term)} " in padded
    }
    matches.update(
        f"prefix:{prefix}"
        for prefix in prefixes
        if any(token.startswith(prefix.casefold()) for token in tokens)
    )
    return sorted(matches)


def deterministic_audit_sample(identifier: str, fraction: float) -> bool:
    """Select the same negative audit sample on every run."""

    if not 0 <= fraction <= 1:
        raise ClassificationError("negative_audit_fraction must be between 0 and 1")
    value = int(hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:8], 16)
    return value / 0xFFFFFFFF < fraction


def classify_direct(
    utterances: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Apply the two dictionaries without using conversational context."""

    rows: list[dict[str, Any]] = []
    for index, utterance in enumerate(utterances):
        text = str(utterance.get("text") or "").strip()
        health_matches = matched_rules(
            text,
            config["health_terms"],
            config["health_prefixes"],
        )
        science_matches = matched_rules(
            text,
            config["science_terms"],
            config["science_prefixes"],
        )
        words = utterance.get("words") or []
        word_count = len(words) if words else len(normalize_text(text).split())
        start_ms = int(utterance.get("start") or 0)
        end_ms = int(utterance.get("end") or start_ms)
        if end_ms < start_ms:
            raise ClassificationError(f"Turn {index} ends before it starts")
        rows.append(
            {
                "utterance_id": index,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_seconds": (end_ms - start_ms) / 1000,
                "speaker": utterance.get("speaker") or "Unknown speaker",
                "text": text,
                "word_count": word_count,
                "confidence": utterance.get("confidence"),
                "health_direct": int(bool(health_matches)),
                "science_direct": int(bool(science_matches)),
                "health_related": int(bool(health_matches)),
                "science_related": int(bool(science_matches)),
                "health_matches": health_matches,
                "science_matches": science_matches,
                "health_context_source": "",
                "science_context_source": "",
            }
        )
    return rows


def apply_context(rows: list[dict[str, Any]], config: dict[str, Any]) -> None:
    """Let short replies inherit direct labels from adjacent turns once."""

    rule = config["context_rule"]
    max_words = int(rule["max_words"])
    max_gap_ms = int(rule["max_gap_ms"])
    for index, row in enumerate(rows):
        if row["word_count"] > max_words:
            continue
        neighbors: list[tuple[str, dict[str, Any]]] = []
        if index > 0 and row["start_ms"] - rows[index - 1]["end_ms"] <= max_gap_ms:
            neighbors.append(("previous", rows[index - 1]))
        if (
            index + 1 < len(rows)
            and rows[index + 1]["start_ms"] - row["end_ms"] <= max_gap_ms
        ):
            neighbors.append(("next", rows[index + 1]))

        for label in ("health", "science"):
            if row[f"{label}_direct"]:
                continue
            sources = [side for side, item in neighbors if item[f"{label}_direct"]]
            if sources:
                row[f"{label}_related"] = 1
                row[f"{label}_context_source"] = "|".join(sources)


def interval_union_seconds(intervals: Iterable[tuple[int, int]]) -> float:
    """Measure unique timeline coverage, avoiding double-counted cross-talk."""

    ordered = sorted((start, end) for start, end in intervals if end > start)
    if not ordered:
        return 0.0
    total_ms = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total_ms += current_end - current_start
            current_start, current_end = start, end
    total_ms += current_end - current_start
    return total_ms / 1000


def label_metrics(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    selected = [row for row in rows if row[label]]
    return {
        "turns": len(selected),
        "words": sum(row["word_count"] for row in selected),
        "speaking_seconds": round(sum(row["duration_seconds"] for row in selected), 3),
        "timeline_coverage_seconds": round(
            interval_union_seconds((row["start_ms"], row["end_ms"]) for row in selected),
            3,
        ),
    }


def build_summary(
    rows: list[dict[str, Any]],
    transcript: dict[str, Any],
    raw_metadata: dict[str, Any],
    config: dict[str, Any],
    input_path: Path,
) -> dict[str, Any]:
    media_duration = (
        raw_metadata.get("media", {}).get("measured", {}).get("duration_seconds")
    )
    total_speaking_seconds = sum(row["duration_seconds"] for row in rows)
    totals = {
        "turns": len(rows),
        "words": sum(row["word_count"] for row in rows),
        "speaking_seconds": round(total_speaking_seconds, 3),
        "episode_audio_seconds": media_duration,
        "health_related": label_metrics(rows, "health_related"),
        "science_related": label_metrics(rows, "science_related"),
        "health_and_science": label_metrics(
            [
                {**row, "health_and_science": int(row["health_related"] and row["science_related"])}
                for row in rows
            ],
            "health_and_science",
        ),
    }
    for name in ("health_related", "science_related", "health_and_science"):
        metric = totals[name]
        metric["share_of_speaking_time"] = round(
            metric["speaking_seconds"] / total_speaking_seconds, 6
        ) if total_speaking_seconds else None
        metric["share_of_episode_audio"] = round(
            metric["timeline_coverage_seconds"] / media_duration, 6
        ) if media_duration else None

    by_speaker: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["speaker"])].append(row)
    for speaker, speaker_rows in sorted(grouped.items()):
        speaking_seconds = sum(row["duration_seconds"] for row in speaker_rows)
        by_speaker[speaker] = {
            "turns": len(speaker_rows),
            "words": sum(row["word_count"] for row in speaker_rows),
            "speaking_seconds": round(speaking_seconds, 3),
            "health_related": label_metrics(speaker_rows, "health_related"),
            "science_related": label_metrics(speaker_rows, "science_related"),
        }

    return {
        "schema_version": "0.1",
        "generated_at": utc_now(),
        "status": "provisional_not_human_validated",
        "method": config["method"],
        "unit": config["unit"],
        "definitions": config["labels"],
        "input": {
            "relative_path": str(input_path.relative_to(PROJECT_ROOT)),
            "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "episode": transcript.get("episode"),
        },
        "configuration": {
            "relative_path": str(CONFIG_PATH.relative_to(PROJECT_ROOT)),
            "sha256": hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest(),
            "context_rule": config["context_rule"],
            "negative_audit_fraction": config["negative_audit_fraction"],
        },
        "totals": totals,
        "by_speaker": by_speaker,
        "review": {
            "rows_marked_for_review": sum(row["needs_review"] for row in rows),
            "positive_rows": sum(
                int(row["health_related"] or row["science_related"]) for row in rows
            ),
            "negative_audit_rows": sum(row["negative_audit_sample"] for row in rows),
        },
    }


def atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_outputs(
    rows: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "episode_id",
        "utterance_id",
        "start_ms",
        "end_ms",
        "duration_seconds",
        "speaker",
        "text",
        "word_count",
        "confidence",
        "health_related",
        "science_related",
        "health_direct",
        "science_direct",
        "health_matches",
        "science_matches",
        "health_context_source",
        "science_context_source",
        "negative_audit_sample",
        "needs_review",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        output_row = dict(row)
        output_row["health_matches"] = "|".join(row["health_matches"])
        output_row["science_matches"] = "|".join(row["science_matches"])
        writer.writerow(output_row)
    atomic_write_text(output_dir / "turn_classification.csv", buffer.getvalue())
    atomic_write_text(
        output_dir / "classification_summary.json",
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-directory",
        default="the_joe_rogan_experience",
        help="Folder below data/derived/transcripts",
    )
    parser.add_argument(
        "--video-id",
        default="BAhcDwMGKYU",
        help="Episode identifier used by the acquisition pipeline",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        show_directory = validate_path_component(args.show_directory, "--show-directory")
        video_id = validate_path_component(args.video_id, "--video-id")
        input_path = TRANSCRIPTS / show_directory / video_id / "transcript.json"
        metadata_path = RAW_TRANSCRIPTS / show_directory / video_id / "rss_metadata.json"
        output_dir = CLASSIFICATIONS / show_directory / video_id
        if not input_path.is_file():
            raise ClassificationError(f"Transcript input does not exist: {input_path}")
        if not metadata_path.is_file():
            raise ClassificationError(f"Raw metadata input does not exist: {metadata_path}")
        transcript = json.loads(input_path.read_text(encoding="utf-8"))
        raw_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        utterances = transcript.get("utterances") or []
        if not utterances:
            raise ClassificationError("Transcript contains no utterances")

        rows = classify_direct(utterances, config)
        apply_context(rows, config)
        episode_id = transcript.get("episode", {}).get("youtube_video_id") or video_id
        if episode_id != video_id:
            raise ClassificationError("Transcript episode ID differs from --video-id")
        audit_fraction = float(config["negative_audit_fraction"])
        for row in rows:
            row["episode_id"] = episode_id
            negative = not row["health_related"] and not row["science_related"]
            row["negative_audit_sample"] = int(
                negative
                and deterministic_audit_sample(
                    f"{episode_id}:{row['utterance_id']}", audit_fraction
                )
            )
            row["needs_review"] = int(
                row["health_related"]
                or row["science_related"]
                or row["negative_audit_sample"]
            )

        if len({row["utterance_id"] for row in rows}) != len(rows):
            raise ClassificationError("Utterance identifiers are not unique")
        summary = build_summary(
            rows, transcript, raw_metadata, config, input_path
        )
        write_outputs(rows, summary, output_dir)

        totals = summary["totals"]
        print(f"Input turns: {totals['turns']}")
        print(
            "Health-related: "
            f"{totals['health_related']['turns']} turns, "
            f"{totals['health_related']['timeline_coverage_seconds'] / 60:.1f} minutes"
        )
        print(
            "Science-related: "
            f"{totals['science_related']['turns']} turns, "
            f"{totals['science_related']['timeline_coverage_seconds'] / 60:.1f} minutes"
        )
        print(f"Rows requiring review: {summary['review']['rows_marked_for_review']}")
        print(f"Wrote {output_dir.relative_to(PROJECT_ROOT)}/turn_classification.csv")
        print(f"Wrote {output_dir.relative_to(PROJECT_ROOT)}/classification_summary.json")
        print("Status: provisional; validate labels before substantive analysis.")
        return 0
    except (ClassificationError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
