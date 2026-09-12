#!/usr/bin/env python3
"""Extract and provisionally classify claims in health/science passages.

Stage 04 is a broad screen of overlapping 256-word windows. This stage reads
only collected stage-04 outputs, keeps windows where health_related OR
science_related is true, and merges consecutive overlapping positive windows
into non-overlapping passages. It then extracts exact claim text and provisionally
classifies each claim's relationship to scientific consensus and fringe status.
One Batch job covers one frozen sample.

Run from the repository root:

    python code/05_classify_passage_content_openai_batch.py prepare \
        --sample config/doac_starter_sample.json
    python code/05_classify_passage_content_openai_batch.py submit \
        --sample config/doac_starter_sample.json --yes
    python code/05_classify_passage_content_openai_batch.py status \
        --sample config/doac_starter_sample.json
    python code/05_classify_passage_content_openai_batch.py collect \
        --sample config/doac_starter_sample.json

Only ``submit --yes`` uploads passage text or incurs an API charge. Credentials
come only from OPENAI_API_KEY and are never written to the project.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PODCAST_CONFIG = PROJECT_ROOT / "config" / "podcasts.json"
SCREEN_CONFIG = PROJECT_ROOT / "config" / "openai_content_classification.json"
CONFIG_PATH = PROJECT_ROOT / "config" / "openai_passage_content_classification.json"
TRANSCRIPTS = PROJECT_ROOT / "data" / "derived" / "transcripts"
SCREEN_ROOT = PROJECT_ROOT / "data" / "derived" / "classifications" / "openai_batch"
OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "derived" / "classifications" / "openai_passage_content"
)
ENDPOINT = "/v1/responses"
TERMINAL_BATCH_STATUSES = {"completed", "failed", "expired", "cancelled"}
DEFAULT_SAMPLE = "config/doac_starter_sample.json"
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class PassageClassificationError(RuntimeError):
    """An expected input, provenance, API, or result-validation failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if isinstance(content, bytes):
        temporary.write_bytes(content)
    else:
        temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    if not path.is_relative_to(PROJECT_ROOT):
        raise PassageClassificationError("The sample path must stay inside this project")
    return path


def validate_component(value: str, label: str) -> str:
    if not SAFE_COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise PassageClassificationError(f"Invalid {label}: {value}")
    return value


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PassageClassificationError(f"Missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PassageClassificationError(f"Invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PassageClassificationError(f"Invalid {label}: expected a JSON object")
    return value


def validate_config(config: dict[str, Any]) -> None:
    required = {
        "schema_version", "prompt_version", "model", "reasoning_effort",
        "max_output_tokens", "max_snippet_words", "claim_domains", "claim_types",
        "consensus_relations", "fringe_statuses", "coding_rules",
        "passage_rationale_rule", "fringe_reason_rule",
    }
    missing = sorted(required - config.keys())
    if missing:
        raise PassageClassificationError("Stage-05 config is missing: " + ", ".join(missing))
    for name in (
        "claim_domains", "claim_types", "consensus_relations", "fringe_statuses"
    ):
        values = config[name]
        if not isinstance(values, dict) or not values:
            raise PassageClassificationError(f"{name} must be a non-empty mapping")
        if any(not SAFE_COMPONENT.fullmatch(str(key)) for key in values):
            raise PassageClassificationError(f"{name} contains an invalid code")
    if int(config["max_output_tokens"]) < 1:
        raise PassageClassificationError("max_output_tokens must be positive")
    if int(config["max_snippet_words"]) < 256:
        raise PassageClassificationError("max_snippet_words must be at least 256")


def flatten_transcript_words(utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for utterance_id, utterance in enumerate(utterances):
        utterance_words = utterance.get("words")
        if not isinstance(utterance_words, list) or not utterance_words:
            raise PassageClassificationError(
                f"Utterance {utterance_id} has no word-level transcript data"
            )
        for word in utterance_words:
            text = str(word.get("text") or "").strip()
            if not text:
                raise PassageClassificationError(
                    f"Utterance {utterance_id} contains an empty word"
                )
            start_ms = int(word.get("start") or 0)
            end_ms = int(word.get("end") or start_ms)
            words.append({
                "word_index": len(words),
                "utterance_id": utterance_id,
                "speaker": str(word.get("speaker") or utterance.get("speaker") or "Unknown speaker"),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "confidence": word.get("confidence"),
                "text": text,
            })
    return words


def speaker_segments(words: list[dict[str, Any]]) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    for word in words:
        if segments and segments[-1]["speaker"] == word["speaker"]:
            segments[-1]["text"] += " " + word["text"]
        else:
            segments.append({"speaker": word["speaker"], "text": word["text"]})
    return segments


def read_screen_rows(path: Path, episode_id: str) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            raw_rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise PassageClassificationError(f"Could not read stage-04 CSV: {path}") from exc
    if not raw_rows:
        raise PassageClassificationError(f"Stage-04 CSV has no rows: {path}")
    rows: list[dict[str, Any]] = []
    for expected_id, row in enumerate(raw_rows):
        try:
            health_value = int(row["health_related"])
            science_value = int(row["science_related"])
            if health_value not in {0, 1} or science_value not in {0, 1}:
                raise ValueError("screen labels must be 0 or 1")
            parsed = {
                "episode_id": str(row["episode_id"]),
                "window_id": int(row["window_id"]),
                "word_start_index": int(row["word_start_index"]),
                "word_end_index_exclusive": int(row["word_end_index_exclusive"]),
                "health_related": bool(health_value),
                "science_related": bool(science_value),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise PassageClassificationError(f"Invalid stage-04 row {expected_id + 2}: {path}") from exc
        if parsed["episode_id"] != episode_id or parsed["window_id"] != expected_id:
            raise PassageClassificationError(
                f"Stage-04 IDs are not complete and ordered for {episode_id}"
            )
        if parsed["word_start_index"] >= parsed["word_end_index_exclusive"]:
            raise PassageClassificationError(f"Invalid word interval in {path}")
        rows.append(parsed)
    return rows


def merge_positive_windows(
    rows: list[dict[str, Any]], words: list[dict[str, Any]], episode_id: str,
    max_passage_words: int | None = None,
) -> list[dict[str, Any]]:
    """Merge positive windows, then split long regions into bounded snippets."""

    positive = [row for row in rows if row["health_related"] or row["science_related"]]
    groups: list[list[dict[str, Any]]] = []
    for row in positive:
        if (
            groups
            and row["window_id"] == groups[-1][-1]["window_id"] + 1
            and row["word_start_index"] < groups[-1][-1]["word_end_index_exclusive"]
        ):
            groups[-1].append(row)
        else:
            groups.append([row])

    passages: list[dict[str, Any]] = []
    previous_end = -1
    for merged_region_number, group in enumerate(groups):
        region_start = group[0]["word_start_index"]
        region_end = max(row["word_end_index_exclusive"] for row in group)
        if region_start < previous_end:
            raise PassageClassificationError(
                f"Merged passages unexpectedly overlap for {episode_id}"
            )
        if region_end > len(words):
            raise PassageClassificationError(
                f"Stage-04 word interval exceeds transcript length for {episode_id}"
            )
        boundaries = [region_start]
        while boundaries[-1] < region_end:
            word_start = boundaries[-1]
            remaining = region_end - word_start
            if max_passage_words is None or remaining <= max_passage_words:
                boundaries.append(region_end)
                continue
            chunks_left = (remaining + max_passage_words - 1) // max_passage_words
            target = word_start + (remaining + chunks_left - 1) // chunks_left
            upper = min(word_start + max_passage_words, region_end - 1)
            lower = word_start + max_passage_words // 2
            candidates = [
                boundary for boundary in range(lower, upper + 1)
                if words[boundary - 1]["utterance_id"] != words[boundary]["utterance_id"]
            ]
            boundaries.append(
                min(candidates, key=lambda boundary: (abs(boundary - target), boundary))
                if candidates else min(target, upper)
            )
        for word_start, word_end in zip(boundaries, boundaries[1:]):
            passage_number = len(passages)
            selected = words[word_start:word_end]
            selected_windows = [
                row for row in group
                if row["word_start_index"] < word_end
                and row["word_end_index_exclusive"] > word_start
            ]
            segments = speaker_segments(selected)
            confidences = [
                float(word["confidence"])
                for word in selected
                if word.get("confidence") is not None
            ]
            passages.append({
                "passage_id": f"{episode_id}-passage-{passage_number:04d}",
                "episode_id": episode_id,
                "passage_number": passage_number,
                "source_merged_region_number": merged_region_number,
                "source_window_ids": [row["window_id"] for row in selected_windows],
                "screen_health_related": any(row["health_related"] for row in selected_windows),
                "screen_science_related": any(row["science_related"] for row in selected_windows),
                "word_start_index": word_start,
                "word_end_index_exclusive": word_end,
                "word_count": word_end - word_start,
                "utterance_start_id": selected[0]["utterance_id"],
                "utterance_end_id": selected[-1]["utterance_id"],
                "start_ms": selected[0]["start_ms"],
                "end_ms": selected[-1]["end_ms"],
                "duration_seconds": (selected[-1]["end_ms"] - selected[0]["start_ms"]) / 1000,
                "speakers": list(dict.fromkeys(segment["speaker"] for segment in segments)),
                "speaker_segments": segments,
                "text": " ".join(segment["text"] for segment in segments),
                "mean_word_confidence": (
                    sum(confidences) / len(confidences) if confidences else None
                ),
            })
        previous_end = region_end
    return passages


def response_schema(config: dict[str, Any]) -> dict[str, Any]:
    claim_domains = list(config["claim_domains"])
    claim_types = list(config["claim_types"])
    consensus_relations = list(config["consensus_relations"])
    fringe_statuses = list(config["fringe_statuses"])
    claim_schema = {
        "type": "object",
        "properties": {
            "exact_claim_text": {"type": "string"},
            "claim_domain": {"type": "string", "enum": claim_domains},
            "claim_type": {"type": "string", "enum": claim_types},
            "consensus_relation": {
                "type": "string", "enum": consensus_relations,
            },
            "fringe_status": {"type": "string", "enum": fringe_statuses},
            "fringe_reason": {"type": "string"},
        },
        "required": [
            "exact_claim_text", "claim_domain", "claim_type",
            "consensus_relation", "fringe_status", "fringe_reason",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "passage_id": {"type": "string"},
            "confirmed_health_related": {"type": "boolean"},
            "confirmed_science_related": {"type": "boolean"},
            "passage_rationale": {"type": "string"},
            "claims": {"type": "array", "items": claim_schema},
        },
        "required": [
            "passage_id", "confirmed_health_related", "confirmed_science_related",
            "passage_rationale", "claims",
        ],
        "additionalProperties": False,
    }


def system_instructions(config: dict[str, Any]) -> str:
    def definitions(name: str) -> str:
        return "\n".join(f"- {key}: {value}" for key, value in config[name].items())

    rules = "\n".join(f"- {rule}" for rule in config["coding_rules"])
    return (
        "You are extracting and provisionally classifying claims from passages "
        "selected by a broad health/science screen for an observational podcast "
        "research project. Code only claims stated in the supplied passage.\n\n"
        "Claim domains:\n" + definitions("claim_domains") + "\n\n"
        "Claim types:\n" + definitions("claim_types") + "\n\n"
        "Consensus relationships:\n" + definitions("consensus_relations") + "\n\n"
        "Fringe statuses:\n" + definitions("fringe_statuses") + "\n\n"
        "Rules:\n" + rules + "\n\n"
        "Passage rationale: " + str(config["passage_rationale_rule"]) + "\n"
        "Fringe reason: " + str(config["fringe_reason_rule"]) + "\n"
        "Return exactly one passage result and preserve passage_id exactly."
    )


def build_batch_requests(
    passages: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    requested: list[dict[str, Any]] = []
    instructions = system_instructions(config)
    schema = response_schema(config)
    for passage in passages:
        custom_id = passage["passage_id"]
        model_passage = {
            "passage_id": passage["passage_id"],
            "episode_id": passage["episode_id"],
            "screen_labels": {
                "health_related": passage["screen_health_related"],
                "science_related": passage["screen_science_related"],
            },
            "speaker_segments": passage["speaker_segments"],
        }
        body = {
            "model": config["model"],
            "instructions": instructions,
            "input": json.dumps({"passage": model_passage}, ensure_ascii=False, separators=(",", ":")),
            "reasoning": {"effort": config["reasoning_effort"]},
            "max_output_tokens": int(config["max_output_tokens"]),
            "text": {"format": {
                "type": "json_schema", "name": "podcast_passage_content",
                "strict": True, "schema": schema,
            }},
            "store": False,
        }
        requests.append({"custom_id": custom_id, "method": "POST", "url": ENDPOINT, "body": body})
        requested.append({
            "custom_id": custom_id,
            "passage_id": passage["passage_id"],
            "episode_id": passage["episode_id"],
            "word_start_index": passage["word_start_index"],
            "word_end_index_exclusive": passage["word_end_index_exclusive"],
        })
    return requests, requested


def jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    ).encode("utf-8")


def resolve_collected_screen_run(show_directory: str, episode_id: str) -> Path:
    episode_root = SCREEN_ROOT / show_directory / episode_id
    candidates: list[Path] = []
    expected_config_hash = sha256_file(SCREEN_CONFIG)
    if episode_root.is_dir():
        for run_dir in sorted(episode_root.iterdir()):
            if not run_dir.is_dir():
                continue
            manifest_path = run_dir / "request_manifest.json"
            if not all((run_dir / name).is_file() for name in (
                "request_manifest.json", "window_classification.csv", "classification_summary.json"
            )):
                continue
            manifest = load_json(manifest_path, "stage-04 request manifest")
            if manifest.get("input", {}).get("configuration_sha256") == expected_config_hash:
                candidates.append(run_dir)
    if not candidates:
        raise PassageClassificationError(
            f"No current collected stage-04 screen for {episode_id}. "
            "Run prepare, submit, status, and collect in stage 04 first."
        )
    if len(candidates) > 1:
        raise PassageClassificationError(
            f"More than one current collected stage-04 run exists for {episode_id}: "
            + ", ".join(path.name for path in candidates)
        )
    return candidates[0]


def load_sample_inputs(sample_path: Path) -> dict[str, Any]:
    sample = load_json(sample_path, "sample configuration")
    podcasts = load_json(PODCAST_CONFIG, "podcast configuration").get("podcasts", {})
    config = load_json(CONFIG_PATH, "stage-05 configuration")
    validate_config(config)
    try:
        sample_id = validate_component(str(sample["sample_id"]), "sample_id")
        show_id = str(sample["show_id"])
        show_directory = validate_component(str(podcasts[show_id]["raw_directory"]), "show directory")
        episode_rows = sample["episodes"]
    except (KeyError, TypeError) as exc:
        raise PassageClassificationError("Invalid sample or podcast configuration") from exc
    if not isinstance(episode_rows, list) or not episode_rows:
        raise PassageClassificationError("The frozen sample contains no episodes")

    episodes: list[dict[str, Any]] = []
    all_passages: list[dict[str, Any]] = []
    source_files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in episode_rows:
        episode_id = str(row.get("youtube_id") or "")
        if not VIDEO_ID.fullmatch(episode_id) or episode_id in seen:
            raise PassageClassificationError(f"Invalid or duplicate YouTube ID: {episode_id}")
        seen.add(episode_id)
        transcript_path = TRANSCRIPTS / show_directory / episode_id / "transcript.json"
        transcript = load_json(transcript_path, "transcript")
        if transcript.get("episode", {}).get("youtube_video_id") != episode_id:
            raise PassageClassificationError(f"Transcript episode ID mismatch for {episode_id}")
        utterances = transcript.get("utterances")
        if not isinstance(utterances, list) or not utterances:
            raise PassageClassificationError(f"Transcript has no utterances: {episode_id}")
        screen_run = resolve_collected_screen_run(show_directory, episode_id)
        screen_csv = screen_run / "window_classification.csv"
        screen_manifest_path = screen_run / "request_manifest.json"
        screen_manifest = load_json(screen_manifest_path, "stage-04 request manifest")
        if screen_manifest.get("input", {}).get("transcript_sha256") != sha256_file(transcript_path):
            raise PassageClassificationError(f"Stage-04 screen uses a different transcript for {episode_id}")
        words = flatten_transcript_words(utterances)
        screen_rows = read_screen_rows(screen_csv, episode_id)
        requested_windows = screen_manifest.get("windows")
        if not isinstance(requested_windows, list) or len(requested_windows) != len(screen_rows):
            raise PassageClassificationError(
                f"Stage-04 CSV and request manifest disagree for {episode_id}"
            )
        for screen_row, requested_window in zip(screen_rows, requested_windows):
            expected_interval = (
                int(requested_window.get("window_id", -1)),
                int(requested_window.get("word_start_index", -1)),
                int(requested_window.get("word_end_index_exclusive", -1)),
            )
            actual_interval = (
                screen_row["window_id"], screen_row["word_start_index"],
                screen_row["word_end_index_exclusive"],
            )
            if actual_interval != expected_interval:
                raise PassageClassificationError(
                    f"Stage-04 CSV interval differs from its manifest for {episode_id}"
                )
        passages = merge_positive_windows(
            screen_rows, words, episode_id,
            max_passage_words=int(config["max_snippet_words"]),
        )
        for passage in passages:
            passage["episode_title"] = transcript.get("episode", {}).get("title")
        all_passages.extend(passages)
        episodes.append({
            "episode_id": episode_id,
            "title": transcript.get("episode", {}).get("title"),
            "transcript_words": len(words),
            "transcript_duration_seconds": (
                transcript.get("transcription", {}).get("audio_duration_seconds")
                or (words[-1]["end_ms"] / 1000 if words else None)
            ),
            "screen_windows": len(screen_rows),
            "positive_screen_windows": sum(
                row["health_related"] or row["science_related"] for row in screen_rows
            ),
            "candidate_passages": len(passages),
            "candidate_unique_words": sum(passage["word_count"] for passage in passages),
            "stage04_run_id": screen_run.name,
        })
        source_files.extend([
            {"relative_path": str(transcript_path.relative_to(PROJECT_ROOT)), "sha256": sha256_file(transcript_path)},
            {"relative_path": str(screen_csv.relative_to(PROJECT_ROOT)), "sha256": sha256_file(screen_csv)},
            {"relative_path": str(screen_manifest_path.relative_to(PROJECT_ROOT)), "sha256": sha256_file(screen_manifest_path)},
        ])
    if not all_passages:
        raise PassageClassificationError("The sample has no positive stage-04 windows to classify")
    return {
        "sample": sample, "sample_id": sample_id, "show_id": show_id,
        "show_directory": show_directory, "config": config, "episodes": episodes,
        "passages": all_passages, "source_files": source_files,
    }


def prepare(args: argparse.Namespace) -> int:
    sample_path = project_path(args.sample)
    inputs = load_sample_inputs(sample_path)
    requests, requested = build_batch_requests(inputs["passages"], inputs["config"])
    input_bytes = jsonl_bytes(requests)
    passages_bytes = json.dumps(inputs["passages"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    run_definition = (
        input_bytes + b"\0" + passages_bytes + b"\0" + sample_path.read_bytes()
        + b"\0" + CONFIG_PATH.read_bytes()
    )
    run_hash = sha256_bytes(run_definition)
    run_id = run_hash[:12]
    sample_root = OUTPUT_ROOT / inputs["sample_id"]
    run_dir = sample_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(run_dir / "batch_input.jsonl", input_bytes)
    atomic_write(run_dir / "passages.json", passages_bytes + b"\n")
    manifest = {
        "schema_version": "0.1", "created_at": utc_now(),
        "status": "prepared_not_submitted", "run_id": run_id,
        "run_definition_sha256": run_hash, "sample_id": inputs["sample_id"],
        "show_id": inputs["show_id"], "show_directory": inputs["show_directory"],
        "model": inputs["config"]["model"], "endpoint": ENDPOINT,
        "prompt_version": inputs["config"]["prompt_version"],
        "selection": {
            "source": "stage-04 windows where health_related OR science_related",
            "merge_rule": "consecutive overlapping positive windows are merged; no negative window is bridged; long merged regions are split at an utterance boundary when possible",
            "max_snippet_words": int(inputs["config"]["max_snippet_words"]),
            "amount_unit": "unique transcript words and passage time intervals",
            "classification_unit": "exact checkable health/science claim within a merged passage",
            "fringe_definition": (
                "fringe means the claim clearly conflicts with established scientific "
                "consensus or presents an extraordinary unsupported position as established knowledge"
            ),
            "uncertain_rule": (
                "retain uncertain when evidence is mixed, evolving, missing, specialized, "
                "or insufficient for a reliable determination"
            ),
        },
        "input": {
            "sample_relative_path": str(sample_path.relative_to(PROJECT_ROOT)),
            "sample_sha256": sha256_file(sample_path),
            "configuration_relative_path": str(CONFIG_PATH.relative_to(PROJECT_ROOT)),
            "configuration_sha256": sha256_file(CONFIG_PATH),
            "screen_configuration_relative_path": str(SCREEN_CONFIG.relative_to(PROJECT_ROOT)),
            "screen_configuration_sha256": sha256_file(SCREEN_CONFIG),
            "batch_input_sha256": sha256_bytes(input_bytes),
            "batch_input_bytes": len(input_bytes),
            "passages_sha256": sha256_bytes(passages_bytes + b"\n"),
            "episodes": len(inputs["episodes"]), "passages": len(inputs["passages"]),
            "requests": len(requests), "source_files": inputs["source_files"],
        },
        "episodes": inputs["episodes"], "requests": requested,
    }
    write_json(run_dir / "request_manifest.json", manifest)
    write_json(sample_root / "latest_prepared_run.json", {"run_id": run_id, "updated_at": utc_now()})
    print("Prepared stage-05 OpenAI Batch classification")
    for episode in inputs["episodes"]:
        print(
            f"  {episode['episode_id']}: {episode['positive_screen_windows']}/"
            f"{episode['screen_windows']} positive windows -> "
            f"{episode['candidate_passages']} passages, "
            f"{episode['candidate_unique_words']} unique words"
        )
    print(f"  Episodes:       {len(inputs['episodes'])}")
    print(f"  Batch requests: {len(inputs['passages'])}")
    print(f"  Model:          {inputs['config']['model']}")
    print(f"  Run ID:         {run_id}")
    print(f"  Batch input:    {(run_dir / 'batch_input.jsonl').relative_to(PROJECT_ROOT)}")
    print("No transcript text was uploaded and no API cost was incurred.")
    return 0


def resolve_run_dir(args: argparse.Namespace) -> Path:
    sample_path = project_path(args.sample)
    sample = load_json(sample_path, "sample configuration")
    sample_id = validate_component(str(sample.get("sample_id") or ""), "sample_id")
    sample_root = OUTPUT_ROOT / sample_id
    if args.run_id:
        run_id = validate_component(args.run_id, "run_id")
    else:
        pointer = load_json(sample_root / "latest_prepared_run.json", "latest run pointer")
        run_id = validate_component(str(pointer.get("run_id") or ""), "stored run_id")
    run_dir = sample_root / run_id
    if not (run_dir / "request_manifest.json").is_file():
        raise PassageClassificationError(f"Run manifest does not exist: {run_dir}")
    return run_dir


def validate_prepared_files(run_dir: Path) -> dict[str, Any]:
    manifest = load_json(run_dir / "request_manifest.json", "request manifest")
    checks = {
        run_dir / "batch_input.jsonl": manifest["input"]["batch_input_sha256"],
        run_dir / "passages.json": manifest["input"]["passages_sha256"],
        project_path(manifest["input"]["sample_relative_path"]): manifest["input"]["sample_sha256"],
        CONFIG_PATH: manifest["input"]["configuration_sha256"],
        SCREEN_CONFIG: manifest["input"]["screen_configuration_sha256"],
    }
    for path, expected_hash in checks.items():
        if not path.is_file() or sha256_file(path) != expected_hash:
            raise PassageClassificationError(f"Prepared input is missing or changed: {path}")
    for source in manifest["input"]["source_files"]:
        path = project_path(source["relative_path"])
        if not path.is_file() or sha256_file(path) != source["sha256"]:
            raise PassageClassificationError(f"A stage-04 source changed after prepare: {path}")
    return manifest


def openai_client() -> tuple[Any, str]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise PassageClassificationError(
            "OPENAI_API_KEY is not set in this terminal; do not put it in project files"
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise PassageClassificationError(
            "The openai package is missing; run: conda env update --file environment.yml"
        ) from exc
    try:
        version = importlib.metadata.version("openai")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return OpenAI(), version


def dump_api_object(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    raise PassageClassificationError("Could not serialize the OpenAI API response")


def submit(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args)
    manifest = validate_prepared_files(run_dir)
    job_path = run_dir / "batch_job.json"
    previous = load_json(job_path, "Batch job") if job_path.is_file() else None
    if previous and previous.get("batch_id"):
        raise PassageClassificationError(
            f"This run was already submitted as {previous['batch_id']}; refusing duplicate cost"
        )
    print("Stage-05 OpenAI Batch submission plan")
    print(f"  Sample:          {manifest['sample_id']}")
    print(f"  Passages sent:   {manifest['input']['passages']}")
    print(f"  Requests:        {manifest['input']['requests']}")
    print(f"  Model:           {manifest['model']}")
    print("  External action: upload selected transcript passages and create a billable 24-hour batch")
    if not args.yes:
        raise PassageClassificationError("Nothing submitted. Review the plan, then add --yes")
    client, sdk_version = openai_client()
    if previous and previous.get("input_file_id"):
        input_file_id = previous["input_file_id"]
    else:
        with (run_dir / "batch_input.jsonl").open("rb") as handle:
            uploaded = client.files.create(file=handle, purpose="batch")
        input_file_id = uploaded.id
        write_json(job_path, {
            "schema_version": "0.1", "uploaded_at": utc_now(),
            "openai_python_version": sdk_version, "input_file_id": input_file_id,
            "state": "uploaded_not_submitted",
        })
    batch = client.batches.create(
        input_file_id=input_file_id, endpoint=ENDPOINT, completion_window="24h",
        metadata={
            "project": "podcast_observational", "sample_id": manifest["sample_id"],
            "run_id": manifest["run_id"], "prompt_version": manifest["prompt_version"],
        },
    )
    write_json(job_path, {
        "schema_version": "0.1", "submitted_at": utc_now(),
        "openai_python_version": sdk_version, "input_file_id": input_file_id,
        "batch_id": batch.id, "state": "submitted", "batch": dump_api_object(batch),
    })
    print(f"Submitted batch: {batch.id}")
    return 0


def retrieve_job(args: argparse.Namespace) -> tuple[Any, dict[str, Any], Path, Any]:
    run_dir = resolve_run_dir(args)
    job_path = run_dir / "batch_job.json"
    job = load_json(job_path, "Batch job")
    if not job.get("batch_id"):
        raise PassageClassificationError("This run has not been submitted")
    client, _ = openai_client()
    batch = client.batches.retrieve(job["batch_id"])
    job["last_checked_at"] = utc_now()
    job["batch"] = dump_api_object(batch)
    write_json(job_path, job)
    return client, job, run_dir, batch


def status(args: argparse.Namespace) -> int:
    _, job, run_dir, batch = retrieve_job(args)
    counts = getattr(batch, "request_counts", None)
    print(f"Batch:  {job['batch_id']}")
    print(f"Status: {batch.status}")
    print(
        f"Counts: {getattr(counts, 'completed', 0) if counts else 0} completed, "
        f"{getattr(counts, 'failed', 0) if counts else 0} failed, "
        f"{getattr(counts, 'total', 0) if counts else 0} total"
    )
    print(f"State:  {(run_dir / 'batch_job.json').relative_to(PROJECT_ROOT)}")
    return 0


def api_file_bytes(client: Any, file_id: str) -> bytes:
    response = client.files.content(file_id)
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    text_value = getattr(response, "text", None)
    if isinstance(text_value, str):
        return text_value.encode("utf-8")
    if callable(text_value):
        value = text_value()
        return value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if hasattr(response, "read"):
        value = response.read()
        return value.encode("utf-8") if isinstance(value, str) else bytes(value)
    raise PassageClassificationError(f"Could not read API file {file_id}")


def parse_jsonl(content: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(content.decode("utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            rows.append(json.loads(raw_line))
        except json.JSONDecodeError as exc:
            raise PassageClassificationError(f"Invalid JSON on line {line_number} of {label}") from exc
    return rows


def extract_output_text(body: dict[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    texts: list[str] = []
    refusals: list[str] = []
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                texts.append(str(content.get("text") or ""))
            elif content.get("type") == "refusal":
                refusals.append(str(content.get("refusal") or "refused"))
    if refusals:
        raise PassageClassificationError("Model refusal: " + "; ".join(refusals))
    if not texts:
        raise PassageClassificationError("A successful response contained no output text")
    return "".join(texts)


def validate_classification(
    result: dict[str, Any], expected_id: str, config: dict[str, Any]
) -> None:
    if result.get("passage_id") != expected_id:
        raise PassageClassificationError(f"Passage ID mismatch for {expected_id}")
    for name in ("confirmed_health_related", "confirmed_science_related"):
        if type(result.get(name)) is not bool:
            raise PassageClassificationError(f"{name} is not boolean for {expected_id}")
    rationale = result.get("passage_rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale.split()) > 60:
        raise PassageClassificationError(f"Invalid passage_rationale for {expected_id}")
    claims = result.get("claims")
    if not isinstance(claims, list):
        raise PassageClassificationError(f"Claims are not a list for {expected_id}")
    if claims and not (
        result["confirmed_health_related"] or result["confirmed_science_related"]
    ):
        raise PassageClassificationError(
            f"Claims cannot be present in a non-health/non-science passage: {expected_id}"
        )
    seen_claims: set[str] = set()
    valid_domains = set(config["claim_domains"])
    valid_types = set(config["claim_types"])
    valid_relations = set(config["consensus_relations"])
    valid_statuses = set(config["fringe_statuses"])
    relation_statuses = {
        "consistent_with_consensus": "not_fringe",
        "within_legitimate_debate": "not_fringe",
        "conflicts_with_consensus": "fringe",
        "extraordinary_unsupported": "fringe",
        "insufficient_information": "uncertain",
    }
    for claim_number, claim in enumerate(claims, 1):
        if not isinstance(claim, dict):
            raise PassageClassificationError(
                f"Claim {claim_number} is not an object for {expected_id}"
            )
        exact_text = claim.get("exact_claim_text")
        if not isinstance(exact_text, str) or not exact_text.strip():
            raise PassageClassificationError(
                f"Claim {claim_number} has no exact text for {expected_id}"
            )
        if exact_text in seen_claims:
            raise PassageClassificationError(f"Duplicate claim text for {expected_id}")
        seen_claims.add(exact_text)
        domain = claim.get("claim_domain")
        if domain not in valid_domains:
            raise PassageClassificationError(f"Invalid claim domain for {expected_id}")
        if domain in {"health", "both"} and not result["confirmed_health_related"]:
            raise PassageClassificationError(f"Health claim inconsistency for {expected_id}")
        if domain in {"science", "both"} and not result["confirmed_science_related"]:
            raise PassageClassificationError(f"Science claim inconsistency for {expected_id}")
        if claim.get("claim_type") not in valid_types:
            raise PassageClassificationError(f"Invalid claim type for {expected_id}")
        relation = claim.get("consensus_relation")
        status = claim.get("fringe_status")
        if relation not in valid_relations or status not in valid_statuses:
            raise PassageClassificationError(f"Invalid fringe coding for {expected_id}")
        if relation_statuses.get(str(relation)) != status:
            raise PassageClassificationError(
                f"Consensus/fringe inconsistency for {expected_id}"
            )
        reason = claim.get("fringe_reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason.split()) > 80:
            raise PassageClassificationError(f"Invalid fringe reason for {expected_id}")


def parse_batch_results(
    output_rows: list[dict[str, Any]], manifest: dict[str, Any], config: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    expected = {row["custom_id"]: row for row in manifest["requests"]}
    results: dict[str, dict[str, Any]] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for row in output_rows:
        custom_id = row.get("custom_id")
        if custom_id not in expected:
            raise PassageClassificationError(f"Unexpected custom_id in output: {custom_id}")
        if custom_id in results:
            raise PassageClassificationError(f"Duplicate output custom_id: {custom_id}")
        response = row.get("response") or {}
        if response.get("status_code") != 200 or row.get("error"):
            raise PassageClassificationError(f"Failed response for {custom_id}: {row.get('error')}")
        body = response.get("body") or {}
        try:
            result = json.loads(extract_output_text(body))
        except json.JSONDecodeError as exc:
            raise PassageClassificationError(f"Invalid model JSON for {custom_id}") from exc
        if not isinstance(result, dict):
            raise PassageClassificationError(f"Invalid result for {custom_id}")
        validate_classification(result, expected[custom_id]["passage_id"], config)
        results[custom_id] = {
            **result, "batch_custom_id": custom_id,
            "response_id": body.get("id"), "response_model": body.get("model"),
        }
        body_usage = body.get("usage") or {}
        for name in usage:
            usage[name] += int(body_usage.get(name) or 0)
    missing = sorted(set(expected) - set(results))
    if missing:
        raise PassageClassificationError(f"Output is missing {len(missing)} expected request(s)")
    return results, usage


def analytic_rows(
    passages: list[dict[str, Any]], results: dict[str, dict[str, Any]],
    sample_id: str, show_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for passage in passages:
        result = results[passage["passage_id"]]
        common = {
            "sample_id": sample_id, "show": show_id,
            "episode_id": passage["episode_id"],
            "episode_title": passage.get("episode_title"),
            "snippet_id": passage["passage_id"],
            "passage_number": passage["passage_number"],
            "source_merged_region_number": passage["source_merged_region_number"],
            "source_window_ids": " | ".join(map(str, passage["source_window_ids"])),
            "source_window_count": len(passage["source_window_ids"]),
            "screen_health_related": int(passage["screen_health_related"]),
            "screen_science_related": int(passage["screen_science_related"]),
            "word_start_index": passage["word_start_index"],
            "word_end_index_exclusive": passage["word_end_index_exclusive"],
            "word_count": passage["word_count"],
            "utterance_start_id": passage["utterance_start_id"],
            "utterance_end_id": passage["utterance_end_id"],
            "start_ms": passage["start_ms"], "end_ms": passage["end_ms"],
            "duration_seconds": passage["duration_seconds"],
            "speakers": " | ".join(passage["speakers"]),
            "snippet_text": passage["text"],
            "speaker_segments_json": json.dumps(passage["speaker_segments"], ensure_ascii=False, separators=(",", ":")),
            "mean_word_confidence": passage["mean_word_confidence"],
            "confirmed_health_related": int(result["confirmed_health_related"]),
            "confirmed_science_related": int(result["confirmed_science_related"]),
            "passage_rationale": result["passage_rationale"],
            "batch_custom_id": result["batch_custom_id"],
            "response_id": result["response_id"], "response_model": result["response_model"],
        }
        claims = result["claims"]
        if not claims:
            rows.append({
                **common, "claim_present": 0, "claim_count_in_snippet": 0,
                "claim_id": "", "claim_number": "", "exact_claim_text": "",
                "claim_domain": "", "claim_type": "",
                "consensus_relation": "", "fringe_status": "not_assessable",
                "fringe_reason": "No sufficiently precise, checkable health/science claim was extracted.",
                "evidence_sources": "", "needs_human_review": 1,
                "human_decision": "",
            })
            continue
        for claim_number, claim in enumerate(claims, 1):
            exact_text = claim["exact_claim_text"]
            if exact_text not in passage["text"]:
                raise PassageClassificationError(
                    f"Claim text is not an exact snippet quotation for {passage['passage_id']}"
                )
            rows.append({
                **common, "claim_present": 1,
                "claim_count_in_snippet": len(claims),
                "claim_id": f"{passage['passage_id']}-claim-{claim_number:04d}",
                "claim_number": claim_number, "exact_claim_text": exact_text,
                "claim_domain": claim["claim_domain"],
                "claim_type": claim["claim_type"],
                "consensus_relation": claim["consensus_relation"],
                "fringe_status": claim["fringe_status"],
                "fringe_reason": claim["fringe_reason"],
                "evidence_sources": "", "needs_human_review": 1,
                "human_decision": "",
            })
    return rows


def passage_subset_metrics(
    passages: list[dict[str, Any]], results: dict[str, dict[str, Any]], field: str,
) -> dict[str, Any]:
    selected = [passage for passage in passages if results[passage["passage_id"]][field]]
    return {
        "passages": len(selected), "unique_words": sum(row["word_count"] for row in selected),
        "duration_seconds": round(sum(row["duration_seconds"] for row in selected), 3),
    }


def build_summary(
    rows: list[dict[str, Any]], passages: list[dict[str, Any]],
    results: dict[str, dict[str, Any]], manifest: dict[str, Any],
    job: dict[str, Any], usage: dict[str, int],
) -> dict[str, Any]:
    episode_inputs = {row["episode_id"]: row for row in manifest["episodes"]}
    by_episode: list[dict[str, Any]] = []
    for episode_id, episode in episode_inputs.items():
        episode_passages = [
            passage for passage in passages if passage["episode_id"] == episode_id
        ]
        episode_rows = [row for row in rows if row["episode_id"] == episode_id]
        episode_claims = [row for row in episode_rows if row["claim_present"]]
        health = passage_subset_metrics(
            episode_passages, results, "confirmed_health_related"
        )
        science = passage_subset_metrics(
            episode_passages, results, "confirmed_science_related"
        )
        total_words = int(episode["transcript_words"])
        health["share_of_transcript_words"] = round(health["unique_words"] / total_words, 6)
        science["share_of_transcript_words"] = round(science["unique_words"] / total_words, 6)
        by_episode.append({
            **episode, "confirmed_health": health, "confirmed_science": science,
            "claims_extracted": len(episode_claims),
            "snippets_without_assessable_claims": sum(
                row["fringe_status"] == "not_assessable" for row in episode_rows
            ),
            "fringe_statuses": dict(sorted(Counter(
                row["fringe_status"] for row in episode_rows
            ).items())),
        })
    total_transcript_words = sum(int(row["transcript_words"]) for row in manifest["episodes"])
    health = passage_subset_metrics(passages, results, "confirmed_health_related")
    science = passage_subset_metrics(passages, results, "confirmed_science_related")
    health["share_of_transcript_words"] = round(health["unique_words"] / total_transcript_words, 6)
    science["share_of_transcript_words"] = round(science["unique_words"] / total_transcript_words, 6)
    claim_rows = [row for row in rows if row["claim_present"]]
    return {
        "schema_version": "0.2", "generated_at": utc_now(),
        "status": "provisional_model_assisted_not_human_validated",
        "unit": "one_row_per_extracted_claim_plus_one_not_assessable_row_for_snippets_without_claims",
        "sample_id": manifest["sample_id"], "show_id": manifest["show_id"],
        "method": {
            "provider": "OpenAI", "api": "Batch API with Responses API and Structured Outputs",
            "model_requested": manifest["model"],
            "models_returned": sorted({row["response_model"] for row in rows if row["response_model"]}),
            "prompt_version": manifest["prompt_version"], "run_id": manifest["run_id"],
            "batch_id": job["batch_id"], "openai_python_version": job["openai_python_version"],
            "usage": usage,
        },
        "selection": manifest["selection"],
        "totals": {
            "episodes": len(manifest["episodes"]), "transcript_words": total_transcript_words,
            "candidate_passages": len(passages),
            "candidate_unique_words": sum(row["word_count"] for row in passages),
            "confirmed_health": health, "confirmed_science": science,
            "claims_extracted": len(claim_rows),
            "snippets_without_assessable_claims": sum(
                row["fringe_status"] == "not_assessable" for row in rows
            ),
            "claim_domains": dict(sorted(Counter(
                row["claim_domain"] for row in claim_rows
            ).items())),
            "claim_types": dict(sorted(Counter(
                row["claim_type"] for row in claim_rows
            ).items())),
            "consensus_relations": dict(sorted(Counter(
                row["consensus_relation"] for row in claim_rows
            ).items())),
            "fringe_statuses": dict(sorted(Counter(
                row["fringe_status"] for row in rows
            ).items())),
        },
        "episodes": by_episode,
        "interpretation_note": (
            "Passages are non-overlapping, so passage-level word totals do not double-count "
            "the stage-04 overlap. Fringe status is a provisional model assessment based on "
            "general scientific knowledge, not a literature search or final accuracy judgment. "
            "Evidence sources and human decisions must be added during review."
        ),
        "review": {
            "rows_marked_for_review": len(rows), "human_validated": False,
            "evidence_sources_populated": False,
        },
    }


def download_batch_results(client: Any, batch: Any, run_dir: Path) -> bytes:
    """Retain provider diagnostics even when every request failed.

    A completed Batch can have zero successful requests and only an error file.
    Partial successes are preserved too, but never published as a complete CSV.
    """
    errors: list[dict[str, Any]] = []
    error_file_id = getattr(batch, "error_file_id", None)
    if error_file_id:
        error_bytes = api_file_bytes(client, error_file_id)
        atomic_write(run_dir / "batch_errors.jsonl", error_bytes)
        errors = parse_jsonl(error_bytes, "batch error file")

    output_bytes: bytes | None = None
    if getattr(batch, "output_file_id", None):
        output_bytes = api_file_bytes(client, batch.output_file_id)
        atomic_write(run_dir / "batch_output.jsonl", output_bytes)

    if errors:
        reasons: Counter[str] = Counter()
        for row in errors:
            response = row.get("response") or {}
            body = response.get("body") or {}
            detail = row.get("error") or body.get("error") or {}
            if isinstance(detail, dict):
                code = detail.get("code") or detail.get("type") or "request_error"
                message = detail.get("message") or "No error message supplied"
                reason = f"{code}: {message}"
            else:
                reason = str(detail)
            reasons[reason] += 1
        summary = "; ".join(
            f"{count} request(s): {' '.join(reason.split())[:1000]}"
            for reason, count in reasons.most_common(3)
        )
        raise PassageClassificationError(
            f"Batch {batch.status}: {len(errors)} failed request(s). "
            f"Provider errors: {summary}. "
            f"Full diagnostics saved to {run_dir / 'batch_errors.jsonl'}. "
            "No final classification CSV was generated. Resolve the errors before resubmitting."
        )

    if batch.status != "completed":
        raise PassageClassificationError(f"Batch ended with status: {batch.status}")
    counts = getattr(batch, "request_counts", None)
    failed = getattr(counts, "failed", 0) or 0
    if failed:
        raise PassageClassificationError(
            f"Batch completed with {failed} failed request(s), but no error details "
            "were returned. Refusing to publish incomplete classifications."
        )
    if output_bytes is None:
        raise PassageClassificationError(
            "Batch completed without an output file or usable error details; "
            "inspect batch_job.json. No classifications were generated."
        )
    return output_bytes


def collect(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args)
    client, job, retrieved_dir, batch = retrieve_job(args)
    if retrieved_dir != run_dir:
        raise PassageClassificationError("Resolved run changed unexpectedly")
    if batch.status not in TERMINAL_BATCH_STATUSES:
        raise PassageClassificationError(f"Batch is still {batch.status}; collect after completion")
    output_bytes = download_batch_results(client, batch, run_dir)
    manifest = validate_prepared_files(run_dir)
    config = load_json(CONFIG_PATH, "stage-05 configuration")
    passages = json.loads((run_dir / "passages.json").read_text(encoding="utf-8"))
    if not isinstance(passages, list) or len(passages) != manifest["input"]["passages"]:
        raise PassageClassificationError("Prepared passage count does not match the manifest")
    results, usage = parse_batch_results(
        parse_jsonl(output_bytes, "batch output file"), manifest, config
    )
    rows = analytic_rows(
        passages, results, manifest["sample_id"], manifest["show_id"]
    )
    summary = build_summary(rows, passages, results, manifest, job, usage)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(run_dir / "claim_classification.csv", buffer.getvalue())
    write_json(run_dir / "classification_summary.json", summary)
    print("Collected and validated every stage-05 passage and claim")
    print(f"  Candidate passages: {len(passages)}")
    print(f"  Claims extracted:   {summary['totals']['claims_extracted']}")
    print(f"  Confirmed health:   {summary['totals']['confirmed_health']['passages']}")
    print(f"  Confirmed science:  {summary['totals']['confirmed_science']['passages']}")
    print(f"  Output:             {run_dir.relative_to(PROJECT_ROOT)}")
    print("Status: provisional until human validation.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("prepare", "Create the local Batch JSONL file"),
        ("submit", "Upload selected passages and create a paid Batch job"),
        ("status", "Refresh remote Batch status"),
        ("collect", "Download, validate, and summarize completed results"),
    ):
        child = commands.add_parser(command, help=help_text)
        child.add_argument("--sample", default=DEFAULT_SAMPLE)
        if command != "prepare":
            child.add_argument("--run-id", help="Prepared run ID; defaults to latest")
        if command == "submit":
            child.add_argument("--yes", action="store_true", help="Confirm upload and API charges")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    actions = {"prepare": prepare, "submit": submit, "status": status, "collect": collect}
    try:
        return actions[args.command](args)
    except (PassageClassificationError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if exc.__class__.__module__.startswith("openai"):
            print(f"ERROR: OpenAI API request failed: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
