#!/usr/bin/env python3
"""Extract and provisionally classify claims in health/science passages.

Stage 04 is a broad screen of overlapping 256-word windows. This stage preserves
those exact windows as the units of analysis, sends windows where health_related
OR science_related is true for claim extraction, and provisionally classifies
each claim's relationship to scientific consensus and fringe status. One Batch
job covers one frozen sample.

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
import gzip
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
VIDEO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RELATION_TO_FRINGE_STATUS = {
    "consistent_with_consensus": "not_fringe",
    "within_legitimate_debate": "not_fringe",
    "conflicts_with_consensus": "fringe",
    "extraordinary_unsupported": "fringe",
    "insufficient_information": "uncertain",
}
CLAIM_TOKEN = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)


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
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                value = json.load(handle)
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PassageClassificationError(f"Invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PassageClassificationError(f"Invalid {label}: expected a JSON object")
    return value


def validate_config(config: dict[str, Any]) -> None:
    required = {
        "schema_version", "prompt_version", "model", "reasoning_effort",
        "max_output_tokens", "claim_domains", "claim_types",
        "consensus_relations", "fringe_statuses", "coding_rules",
        "fringe_reason_rule",
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
                "health_rationale": str(row.get("health_rationale") or ""),
                "science_rationale": str(row.get("science_rationale") or ""),
                "negative_audit_sample": int(row.get("negative_audit_sample") or 0),
                "stage04_needs_review": int(row.get("needs_review") or 0),
                "stage04_batch_custom_id": str(row.get("batch_custom_id") or ""),
                "stage04_response_id": str(row.get("response_id") or ""),
                "stage04_response_model": str(row.get("response_model") or ""),
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


def build_screen_snippets(
    rows: list[dict[str, Any]], words: list[dict[str, Any]], episode_id: str
) -> list[dict[str, Any]]:
    """Reconstruct every Stage-04 window as the identical Stage-05 snippet."""

    snippets: list[dict[str, Any]] = []
    for row in rows:
        word_start = row["word_start_index"]
        word_end = row["word_end_index_exclusive"]
        if word_end > len(words):
            raise PassageClassificationError(
                f"Stage-04 word interval exceeds transcript length for {episode_id}"
            )
        selected = words[word_start:word_end]
        segments = speaker_segments(selected)
        confidences = [
            float(word["confidence"])
            for word in selected
            if word.get("confidence") is not None
        ]
        snippets.append({
            "passage_id": f"{episode_id}-window-{row['window_id']:06d}",
            "episode_id": episode_id,
            "window_id": row["window_id"],
            "screen_health_related": row["health_related"],
            "screen_science_related": row["science_related"],
            "stage04_health_rationale": row["health_rationale"],
            "stage04_science_rationale": row["science_rationale"],
            "negative_audit_sample": row["negative_audit_sample"],
            "stage04_needs_review": row["stage04_needs_review"],
            "stage04_batch_custom_id": row["stage04_batch_custom_id"],
            "stage04_response_id": row["stage04_response_id"],
            "stage04_response_model": row["stage04_response_model"],
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
    return snippets


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
            "claims": {"type": "array", "items": claim_schema},
        },
        "required": ["passage_id", "claims"],
        "additionalProperties": False,
    }


def system_instructions(config: dict[str, Any]) -> str:
    def definitions(name: str) -> str:
        return "\n".join(f"- {key}: {value}" for key, value in config[name].items())

    rules = "\n".join(f"- {rule}" for rule in config["coding_rules"])
    return (
        "You are a helpful research assistant with knowledge of health communication, "
        "scientific reasoning, and established scientific consensus. You are extracting "
        "and provisionally classifying claims from 256-word transcript windows "
        "selected by a broad health/science screen for an observational podcast "
        "research project. Code only claims stated in the supplied window.\n\n"
        "Claim domains:\n" + definitions("claim_domains") + "\n\n"
        "Claim types:\n" + definitions("claim_types") + "\n\n"
        "Consensus relationships:\n" + definitions("consensus_relations") + "\n\n"
        "Fringe statuses:\n" + definitions("fringe_statuses") + "\n\n"
        "Rules:\n" + rules + "\n\n"
        "Fringe reason: " + str(config["fringe_reason_rule"]) + "\n"
        "Return exactly one window result and preserve passage_id exactly."
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
    all_snippets: list[dict[str, Any]] = []
    source_files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in episode_rows:
        episode_id = str(row.get("episode_id") or row.get("youtube_id") or "")
        if not VIDEO_ID.fullmatch(episode_id) or episode_id in seen:
            raise PassageClassificationError(f"Invalid or duplicate episode ID: {episode_id}")
        seen.add(episode_id)
        transcript_dir = TRANSCRIPTS / show_directory / episode_id
        transcript_path = transcript_dir / "transcript.json"
        if not transcript_path.is_file() and (transcript_dir / "transcript.json.gz").is_file():
            transcript_path = transcript_dir / "transcript.json.gz"
        transcript = load_json(transcript_path, "transcript")
        recorded_episode_id = (
            transcript.get("episode", {}).get("episode_id")
            or transcript.get("episode", {}).get("youtube_video_id")
        )
        if recorded_episode_id != episode_id:
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
        snippets = build_screen_snippets(screen_rows, words, episode_id)
        for snippet in snippets:
            snippet["episode_title"] = transcript.get("episode", {}).get("title")
        passages = [
            snippet for snippet in snippets
            if snippet["screen_health_related"] or snippet["screen_science_related"]
        ]
        all_snippets.extend(snippets)
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
            "stage05_requested_windows": len(passages),
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
        "passages": all_passages, "snippets": all_snippets, "source_files": source_files,
    }


def prepare(args: argparse.Namespace) -> int:
    sample_path = project_path(args.sample)
    inputs = load_sample_inputs(sample_path)
    requests, requested = build_batch_requests(inputs["passages"], inputs["config"])
    input_bytes = jsonl_bytes(requests)
    snippets_bytes = json.dumps(inputs["snippets"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    run_definition = (
        input_bytes + b"\0" + snippets_bytes + b"\0" + sample_path.read_bytes()
        + b"\0" + CONFIG_PATH.read_bytes()
    )
    run_hash = sha256_bytes(run_definition)
    run_id = run_hash[:12]
    sample_root = OUTPUT_ROOT / inputs["sample_id"]
    run_dir = sample_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(run_dir / "batch_input.jsonl", input_bytes)
    atomic_write(run_dir / "snippets.json", snippets_bytes + b"\n")
    manifest = {
        "schema_version": "0.1", "created_at": utc_now(),
        "status": "prepared_not_submitted", "run_id": run_id,
        "run_definition_sha256": run_hash, "sample_id": inputs["sample_id"],
        "show_id": inputs["show_id"], "show_directory": inputs["show_directory"],
        "model": inputs["config"]["model"], "endpoint": ENDPOINT,
        "prompt_version": inputs["config"]["prompt_version"],
        "selection": {
            "unit": "the unchanged Stage-04 256-word window with a 128-word stride",
            "episode_minimum_words": 768,
            "requests": "only Stage-04 windows where health_related OR science_related",
            "final_csv": "all Stage-04 windows; negative windows receive a derived not_assessable value",
            "classification_unit": "window, with exact claims retained inside the window record",
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
            "snippets_sha256": sha256_bytes(snippets_bytes + b"\n"),
            "episodes": len(inputs["episodes"]),
            "snippets": len(inputs["snippets"]),
            "stage05_requested_windows": len(inputs["passages"]),
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
            f"{episode['screen_windows']} windows sent for Stage 05"
        )
    print(f"  Episodes:       {len(inputs['episodes'])}")
    print(f"  CSV windows:    {len(inputs['snippets'])}")
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
        run_dir / "snippets.json": manifest["input"]["snippets_sha256"],
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
    print(f"  Windows sent:    {manifest['input']['stage05_requested_windows']}")
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
    claims = result.get("claims")
    if not isinstance(claims, list):
        raise PassageClassificationError(f"Claims are not a list for {expected_id}")
    seen_claims: set[str] = set()
    valid_domains = set(config["claim_domains"])
    valid_types = set(config["claim_types"])
    valid_relations = set(config["consensus_relations"])
    valid_statuses = set(config["fringe_statuses"])
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
        if claim.get("claim_type") not in valid_types:
            raise PassageClassificationError(f"Invalid claim type for {expected_id}")
        relation = claim.get("consensus_relation")
        status = claim.get("fringe_status")
        if relation not in valid_relations or status not in valid_statuses:
            raise PassageClassificationError(f"Invalid fringe coding for {expected_id}")
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


def align_claim_text(model_text: str, snippet_text: str) -> tuple[str, str]:
    """Recover an unambiguous verbatim snippet span for a model claim.

    Structured output guarantees the field shape, but it cannot guarantee that
    the model copied punctuation and capitalization exactly. Token alignment is
    deterministic and only succeeds when the same token sequence occurs once.
    """
    if model_text in snippet_text:
        return model_text, "exact"

    case_matches = list(re.finditer(re.escape(model_text), snippet_text, re.IGNORECASE))
    if len(case_matches) == 1:
        match = case_matches[0]
        return snippet_text[match.start():match.end()], "case_insensitive"

    model_tokens = [
        match.group(0).casefold().replace("’", "'")
        for match in CLAIM_TOKEN.finditer(model_text)
    ]
    snippet_matches = list(CLAIM_TOKEN.finditer(snippet_text))
    snippet_tokens = [
        match.group(0).casefold().replace("’", "'") for match in snippet_matches
    ]
    if not model_tokens or len(model_tokens) > len(snippet_tokens):
        return "", "unmatched"
    starts = [
        start for start in range(len(snippet_tokens) - len(model_tokens) + 1)
        if snippet_tokens[start:start + len(model_tokens)] == model_tokens
    ]
    if len(starts) != 1:
        return "", "unmatched"
    start = starts[0]
    return (
        snippet_text[
            snippet_matches[start].start():
            snippet_matches[start + len(model_tokens) - 1].end()
        ],
        "token_sequence",
    )


def analytic_rows(
    passages: list[dict[str, Any]], results: dict[str, dict[str, Any]],
    sample_id: str, show_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for passage in passages:
        result = results.get(passage["passage_id"])
        claims = result["claims"] if result else []
        claim_records: list[dict[str, Any]] = []
        for claim_number, claim in enumerate(claims, 1):
            model_claim_text = claim["exact_claim_text"]
            exact_text, match_method = align_claim_text(
                model_claim_text, passage["text"]
            )
            claim_text_matched = match_method != "unmatched"
            expected_status = RELATION_TO_FRINGE_STATUS[claim["consensus_relation"]]
            status_is_consistent = claim["fringe_status"] == expected_status
            claim_records.append({
                "claim_id": f"{passage['passage_id']}-claim-{claim_number:04d}",
                **claim,
                "model_claim_text": model_claim_text,
                "exact_claim_text": exact_text,
                "claim_text_match_method": match_method,
                "claim_text_matched": int(claim_text_matched),
                "model_fringe_status": claim["fringe_status"],
                "fringe_status": (
                    claim["fringe_status"]
                    if status_is_consistent and claim_text_matched else "uncertain"
                ),
                "consensus_fringe_consistent": int(status_is_consistent),
            })
        status_counts = Counter(claim["fringe_status"] for claim in claim_records)
        if status_counts["fringe"]:
            window_fringe_status = "fringe"
        elif status_counts["uncertain"]:
            window_fringe_status = "uncertain"
        elif status_counts["not_fringe"]:
            window_fringe_status = "not_fringe"
        else:
            window_fringe_status = "not_assessable"
        rows.append({
            "sample_id": sample_id, "show": show_id,
            "episode_id": passage["episode_id"],
            "episode_title": passage.get("episode_title"),
            "snippet_id": passage["passage_id"],
            "window_id": passage["window_id"],
            "screen_health_related": int(passage["screen_health_related"]),
            "screen_science_related": int(passage["screen_science_related"]),
            "stage04_health_rationale": passage["stage04_health_rationale"],
            "stage04_science_rationale": passage["stage04_science_rationale"],
            "negative_audit_sample": passage["negative_audit_sample"],
            "stage04_needs_review": passage["stage04_needs_review"],
            "health_related": int(passage["screen_health_related"]),
            "science_related": int(passage["screen_science_related"]),
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
            "stage05_requested": int(result is not None),
            "claim_present": int(bool(claim_records)),
            "claim_count": len(claim_records),
            "fringe_claim_count": status_counts["fringe"],
            "not_fringe_claim_count": status_counts["not_fringe"],
            "uncertain_claim_count": status_counts["uncertain"],
            "inconsistent_claim_coding_count": sum(
                not claim["consensus_fringe_consistent"] for claim in claim_records
            ),
            "non_exact_claim_text_count": sum(
                claim["claim_text_match_method"] != "exact" for claim in claim_records
            ),
            "unmatched_claim_text_count": sum(
                not claim["claim_text_matched"] for claim in claim_records
            ),
            "fringe_status": window_fringe_status,
            "claim_texts": " || ".join(
                claim["exact_claim_text"] or claim["model_claim_text"]
                for claim in claim_records
            ),
            "fringe_claim_texts": " || ".join(
                claim["exact_claim_text"] or claim["model_claim_text"]
                for claim in claim_records
                if claim["fringe_status"] == "fringe"
            ),
            "uncertain_claim_texts": " || ".join(
                claim["exact_claim_text"] or claim["model_claim_text"]
                for claim in claim_records
                if claim["fringe_status"] == "uncertain"
            ),
            "not_fringe_claim_texts": " || ".join(
                claim["exact_claim_text"] or claim["model_claim_text"]
                for claim in claim_records
                if claim["fringe_status"] == "not_fringe"
            ),
            "claim_domains": " | ".join(dict.fromkeys(
                claim["claim_domain"] for claim in claim_records
            )),
            "claim_types": " | ".join(dict.fromkeys(
                claim["claim_type"] for claim in claim_records
            )),
            "consensus_relations": " | ".join(dict.fromkeys(
                claim["consensus_relation"] for claim in claim_records
            )),
            "claims_json": json.dumps(claim_records, ensure_ascii=False, separators=(",", ":")),
            "evidence_sources": "", "needs_human_review": 1,
            "human_decision": "",
            "stage04_batch_custom_id": passage["stage04_batch_custom_id"],
            "stage04_response_id": passage["stage04_response_id"],
            "stage04_response_model": passage["stage04_response_model"],
            "stage05_batch_custom_id": result["batch_custom_id"] if result else "",
            "stage05_response_id": result["response_id"] if result else "",
            "stage05_response_model": result["response_model"] if result else "",
        })
    return rows


def window_subset_metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    selected = [row for row in rows if row[field]]
    return {
        "windows": len(selected),
        "duration_seconds": round(sum(row["duration_seconds"] for row in selected), 3),
    }


def build_summary(
    rows: list[dict[str, Any]], manifest: dict[str, Any], job: dict[str, Any],
    usage: dict[str, int],
) -> dict[str, Any]:
    episode_inputs = {row["episode_id"]: row for row in manifest["episodes"]}
    by_episode: list[dict[str, Any]] = []
    for episode_id, episode in episode_inputs.items():
        episode_rows = [row for row in rows if row["episode_id"] == episode_id]
        health = window_subset_metrics(episode_rows, "health_related")
        science = window_subset_metrics(episode_rows, "science_related")
        health["share_of_windows"] = round(health["windows"] / len(episode_rows), 6)
        science["share_of_windows"] = round(science["windows"] / len(episode_rows), 6)
        by_episode.append({
            **episode, "stage04_health": health, "stage04_science": science,
            "claims_extracted_in_windows": sum(row["claim_count"] for row in episode_rows),
            "windows_without_assessable_claims": sum(
                row["fringe_status"] == "not_assessable" for row in episode_rows
            ),
            "fringe_statuses": dict(sorted(Counter(
                row["fringe_status"] for row in episode_rows
            ).items())),
        })
    health = window_subset_metrics(rows, "health_related")
    science = window_subset_metrics(rows, "science_related")
    health["share_of_windows"] = round(health["windows"] / len(rows), 6)
    science["share_of_windows"] = round(science["windows"] / len(rows), 6)
    return {
        "schema_version": "0.3", "generated_at": utc_now(),
        "status": "provisional_model_assisted_not_human_validated",
        "unit": "one_overlapping_256_word_window_per_row_with_128_word_stride",
        "sample_id": manifest["sample_id"], "show_id": manifest["show_id"],
        "method": {
            "provider": "OpenAI", "api": "Batch API with Responses API and Structured Outputs",
            "model_requested": manifest["model"],
            "models_returned": sorted({
                row["stage05_response_model"] for row in rows
                if row["stage05_response_model"]
            }),
            "prompt_version": manifest["prompt_version"], "run_id": manifest["run_id"],
            "batch_id": job["batch_id"], "openai_python_version": job["openai_python_version"],
            "usage": usage,
        },
        "selection": manifest["selection"],
        "totals": {
            "episodes": len(manifest["episodes"]), "windows": len(rows),
            "stage05_requested_windows": sum(row["stage05_requested"] for row in rows),
            "stage04_health": health, "stage04_science": science,
            "claims_extracted_in_windows": sum(row["claim_count"] for row in rows),
            "inconsistent_claim_codings": sum(
                row["inconsistent_claim_coding_count"] for row in rows
            ),
            "non_exact_claim_texts": sum(
                row["non_exact_claim_text_count"] for row in rows
            ),
            "unmatched_claim_texts": sum(
                row["unmatched_claim_text_count"] for row in rows
            ),
            "windows_without_assessable_claims": sum(
                row["fringe_status"] == "not_assessable" for row in rows
            ),
            "window_fringe_statuses": dict(sorted(Counter(
                row["fringe_status"] for row in rows
            ).items())),
            "claim_fringe_statuses_with_overlap": {
                "fringe": sum(row["fringe_claim_count"] for row in rows),
                "not_fringe": sum(row["not_fringe_claim_count"] for row in rows),
                "uncertain": sum(row["uncertain_claim_count"] for row in rows),
            },
        },
        "episodes": by_episode,
        "interpretation_note": (
            "Rows preserve the overlapping Stage-04 windows. Adjacent windows share 128 words, "
            "so extracted claim counts can include the same claim more than once and must not be "
            "interpreted as unique-claim counts. A window is fringe when it contains at least one "
            "fringe claim; otherwise uncertain takes precedence over not_fringe. Fringe status is "
            "a provisional model assessment, not a literature search or final accuracy judgment."
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
    snippets = json.loads((run_dir / "snippets.json").read_text(encoding="utf-8"))
    if not isinstance(snippets, list) or len(snippets) != manifest["input"]["snippets"]:
        raise PassageClassificationError("Prepared snippet count does not match the manifest")
    results, usage = parse_batch_results(
        parse_jsonl(output_bytes, "batch output file"), manifest, config
    )
    rows = analytic_rows(
        snippets, results, manifest["sample_id"], manifest["show_id"]
    )
    summary = build_summary(rows, manifest, job, usage)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(run_dir / "window_claim_classification.csv", buffer.getvalue())
    write_json(run_dir / "classification_summary.json", summary)
    print("Collected and validated every Stage-05 window and claim")
    print(f"  CSV windows:        {len(snippets)}")
    print(f"  Claims in windows:  {summary['totals']['claims_extracted_in_windows']}")
    print(f"  Stage-04 health:    {summary['totals']['stage04_health']['windows']}")
    print(f"  Stage-04 science:   {summary['totals']['stage04_science']['windows']}")
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
