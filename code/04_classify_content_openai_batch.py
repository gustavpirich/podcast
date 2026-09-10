#!/usr/bin/env python3
"""Classify overlapping transcript word windows with OpenAI's Batch API.

Run four explicit stages from the repository root:

    python code/04_classify_content_openai_batch.py prepare
    python code/04_classify_content_openai_batch.py submit --yes
    python code/04_classify_content_openai_batch.py status
    python code/04_classify_content_openai_batch.py collect

``prepare`` is local and free. ``submit`` uploads transcript excerpts and starts
a paid external job. ``collect`` only creates analytic outputs after validating
that every expected 256-word window has one result.

Credentials are read only from OPENAI_API_KEY and are never written to disk.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "openai_content_classification.json"
TRANSCRIPTS = PROJECT_ROOT / "data" / "derived" / "transcripts"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "derived" / "classifications" / "openai_batch"
ENDPOINT = "/v1/responses"
TERMINAL_BATCH_STATUSES = {"completed", "failed", "expired", "cancelled"}


class BatchClassificationError(RuntimeError):
    """An expected input, API, or validation failure."""


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


def validate_path_component(value: str, option: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value) or value in {".", ".."}:
        raise BatchClassificationError(
            f"{option} must be one folder name using letters, numbers, '.', '_', or '-'"
        )
    return value


def validate_config(config: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "prompt_version",
        "model",
        "reasoning_effort",
        "window_words",
        "stride_words",
        "minimum_episode_words",
        "include_partial_windows",
        "max_output_tokens",
        "negative_audit_fraction",
        "labels",
        "coding_rules",
        "rationale_rule",
    }
    missing = sorted(required - config.keys())
    if missing:
        raise BatchClassificationError(
            f"Configuration is missing: {', '.join(missing)}"
        )
    window_words = int(config["window_words"])
    stride_words = int(config["stride_words"])
    minimum_episode_words = int(config["minimum_episode_words"])
    if window_words < 1:
        raise BatchClassificationError("window_words must be positive")
    if not 1 <= stride_words <= window_words:
        raise BatchClassificationError(
            "stride_words must be positive and no larger than window_words"
        )
    if minimum_episode_words < window_words:
        raise BatchClassificationError(
            "minimum_episode_words must be at least window_words"
        )
    if config["include_partial_windows"] is not False:
        raise BatchClassificationError(
            "include_partial_windows must be false for standardized full windows"
        )
    if not 0 <= float(config["negative_audit_fraction"]) <= 1:
        raise BatchClassificationError(
            "negative_audit_fraction must be between 0 and 1"
        )
    if set(config["labels"]) != {"health_related", "science_related"}:
        raise BatchClassificationError(
            "Configuration must define exactly the two labels"
        )


def system_instructions(config: dict[str, Any]) -> str:
    rules = "\n".join(f"- {rule}" for rule in config["coding_rules"])
    return (
        "You are coding podcast transcript windows for an observational research "
        "project.\n\n"
        "Definitions:\n"
        f"- health_related: {config['labels']['health_related']}\n"
        f"- science_related: {config['labels']['science_related']}\n\n"
        f"Rules:\n{rules}\n\n"
        f"Rationales: {config['rationale_rule']}\n"
        "Return one classification for the target window. Preserve its integer "
        "window_id exactly."
    )


def response_schema() -> dict[str, Any]:
    """Return the strict output schema for one transcript window."""

    return {
        "type": "object",
        "properties": {
            "window_id": {"type": "integer"},
            "health_related": {"type": "boolean"},
            "science_related": {"type": "boolean"},
            "health_rationale": {"type": "string"},
            "science_rationale": {"type": "string"},
        },
        "required": [
            "window_id",
            "health_related",
            "science_related",
            "health_rationale",
            "science_rationale",
        ],
        "additionalProperties": False,
    }


def flatten_transcript_words(
    utterances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten diarized word objects while preserving provenance and timing."""

    words: list[dict[str, Any]] = []
    for utterance_id, utterance in enumerate(utterances):
        utterance_words = utterance.get("words")
        if not isinstance(utterance_words, list) or not utterance_words:
            raise BatchClassificationError(
                f"Utterance {utterance_id} has no word-level transcript data"
            )
        for word in utterance_words:
            text = str(word.get("text") or "").strip()
            if not text:
                raise BatchClassificationError(
                    f"Utterance {utterance_id} contains an empty word object"
                )
            start_ms = int(word.get("start") or 0)
            end_ms = int(word.get("end") or start_ms)
            words.append(
                {
                    "word_index": len(words),
                    "utterance_id": utterance_id,
                    "speaker": str(
                        word.get("speaker")
                        or utterance.get("speaker")
                        or "Unknown speaker"
                    ),
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "confidence": word.get("confidence"),
                    "text": text,
                }
            )
    return words


def speaker_segments(words: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Group consecutive words by speaker without changing word boundaries."""

    segments: list[dict[str, str]] = []
    for word in words:
        speaker = word["speaker"]
        if segments and segments[-1]["speaker"] == speaker:
            segments[-1]["text"] += " " + word["text"]
        else:
            segments.append({"speaker": speaker, "text": word["text"]})
    return segments


def build_word_windows(
    words: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Create complete fixed-word windows with the configured overlap."""

    window_words = int(config["window_words"])
    stride_words = int(config["stride_words"])
    minimum_episode_words = int(config["minimum_episode_words"])
    if len(words) < minimum_episode_words:
        raise BatchClassificationError(
            f"Episode has {len(words)} words; at least "
            f"{minimum_episode_words} are required"
        )
    windows: list[dict[str, Any]] = []
    for word_start in range(0, len(words) - window_words + 1, stride_words):
        selected = words[word_start : word_start + window_words]
        confidences = [
            float(word["confidence"])
            for word in selected
            if word.get("confidence") is not None
        ]
        windows.append(
            {
                "window_id": len(windows),
                "word_start_index": word_start,
                "word_end_index_exclusive": word_start + window_words,
                "word_count": window_words,
                "utterance_start_id": selected[0]["utterance_id"],
                "utterance_end_id": selected[-1]["utterance_id"],
                "start_ms": selected[0]["start_ms"],
                "end_ms": selected[-1]["end_ms"],
                "mean_word_confidence": (
                    sum(confidences) / len(confidences) if confidences else None
                ),
                "speaker_segments": speaker_segments(selected),
            }
        )
    return windows


def build_batch_requests(
    windows: list[dict[str, Any]],
    episode_id: str,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build request lines and a manifest for exact result validation."""

    instructions = system_instructions(config)
    requests: list[dict[str, Any]] = []
    request_windows: list[dict[str, Any]] = []
    for window in windows:
        window_id = int(window["window_id"])
        custom_id = f"{episode_id}-window-{window_id:06d}"
        payload = {"target_window": window}
        body = {
            "model": config["model"],
            "instructions": instructions,
            "input": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "reasoning": {"effort": config["reasoning_effort"]},
            "max_output_tokens": int(config["max_output_tokens"]),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "podcast_window_classification",
                    "strict": True,
                    "schema": response_schema(),
                }
            },
            "store": False,
        }
        requests.append(
            {"custom_id": custom_id, "method": "POST", "url": ENDPOINT, "body": body}
        )
        request_windows.append(
            {
                "custom_id": custom_id,
                "window_id": window_id,
                "word_start_index": window["word_start_index"],
                "word_end_index_exclusive": window["word_end_index_exclusive"],
            }
        )
    return requests, request_windows


def jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    return text.encode("utf-8")


def episode_paths(show_directory: str, video_id: str) -> tuple[Path, Path]:
    transcript_path = TRANSCRIPTS / show_directory / video_id / "transcript.json"
    episode_output = OUTPUT_ROOT / show_directory / video_id
    return transcript_path, episode_output


def load_inputs(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    show_directory = validate_path_component(args.show_directory, "--show-directory")
    video_id = validate_path_component(args.video_id, "--video-id")
    transcript_path, episode_output = episode_paths(show_directory, video_id)
    if not transcript_path.is_file():
        raise BatchClassificationError(f"Transcript does not exist: {transcript_path}")
    if not CONFIG_PATH.is_file():
        raise BatchClassificationError(f"Configuration does not exist: {CONFIG_PATH}")
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    validate_config(config)
    utterances = transcript.get("utterances") or []
    if not utterances:
        raise BatchClassificationError("Transcript contains no utterances")
    actual_id = transcript.get("episode", {}).get("youtube_video_id") or video_id
    if actual_id != video_id:
        raise BatchClassificationError("Transcript episode ID differs from --video-id")
    return transcript, config, transcript_path, episode_output


def prepare(args: argparse.Namespace) -> int:
    transcript, config, transcript_path, episode_output = load_inputs(args)
    words = flatten_transcript_words(transcript["utterances"])
    windows = build_word_windows(words, config)
    requests, request_windows = build_batch_requests(windows, args.video_id, config)
    input_bytes = jsonl_bytes(requests)
    input_hash = sha256_bytes(input_bytes)
    config_bytes = CONFIG_PATH.read_bytes()
    run_hash = sha256_bytes(input_bytes + b"\0" + config_bytes)
    run_id = run_hash[:12]
    run_dir = episode_output / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    batch_input = run_dir / "batch_input.jsonl"
    atomic_write(batch_input, input_bytes)
    manifest = {
        "schema_version": "0.1",
        "created_at": utc_now(),
        "status": "prepared_not_submitted",
        "run_id": run_id,
        "run_definition_sha256": run_hash,
        "episode_id": args.video_id,
        "show_directory": args.show_directory,
        "model": config["model"],
        "endpoint": ENDPOINT,
        "prompt_version": config["prompt_version"],
        "negative_audit_fraction": config["negative_audit_fraction"],
        "windowing": {
            "unit": "assemblyai_word_object",
            "window_words": config["window_words"],
            "stride_words": config["stride_words"],
            "minimum_episode_words": config["minimum_episode_words"],
            "include_partial_windows": config["include_partial_windows"],
        },
        "input": {
            "transcript_relative_path": str(transcript_path.relative_to(PROJECT_ROOT)),
            "transcript_sha256": sha256_file(transcript_path),
            "configuration_relative_path": str(CONFIG_PATH.relative_to(PROJECT_ROOT)),
            "configuration_sha256": sha256_bytes(config_bytes),
            "batch_input_sha256": input_hash,
            "batch_input_bytes": len(input_bytes),
            "utterances": len(transcript["utterances"]),
            "words": len(words),
            "windows": len(windows),
            "unique_words_covered": windows[-1]["word_end_index_exclusive"],
            "trailing_words_excluded": (
                len(words) - windows[-1]["word_end_index_exclusive"]
            ),
            "requests": len(requests),
        },
        "windows": request_windows,
    }
    write_json(run_dir / "request_manifest.json", manifest)
    write_json(
        episode_output / "latest_prepared_run.json",
        {"run_id": run_id, "updated_at": utc_now()},
    )
    print("Prepared OpenAI Batch classification")
    print(f"  Transcript words: {len(words)}")
    print(f"  Full windows:     {len(windows)}")
    print(
        f"  Window rule:      {config['window_words']} words, "
        f"stride {config['stride_words']}"
    )
    print(
        "  Trailing words:   "
        f"{manifest['input']['trailing_words_excluded']} excluded"
    )
    print(f"  Batch requests:   {len(requests)}")
    print(f"  Model:            {config['model']}")
    print(f"  Run ID:           {run_id}")
    print(f"  Batch input:      {batch_input.relative_to(PROJECT_ROOT)}")
    print("No transcript data were uploaded and no API cost was incurred.")
    print("Next: python code/04_classify_content_openai_batch.py submit --yes")
    return 0


def resolve_run_dir(args: argparse.Namespace, episode_output: Path) -> Path:
    if args.run_id:
        run_id = validate_path_component(args.run_id, "--run-id")
    else:
        pointer = episode_output / "latest_prepared_run.json"
        if not pointer.is_file():
            raise BatchClassificationError(
                "No prepared run found; run the prepare command first"
            )
        run_id = validate_path_component(
            json.loads(pointer.read_text(encoding="utf-8"))["run_id"],
            "stored run_id",
        )
    run_dir = episode_output / run_id
    if not (run_dir / "request_manifest.json").is_file():
        raise BatchClassificationError(f"Run manifest does not exist: {run_dir}")
    return run_dir


def openai_client() -> tuple[Any, str]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise BatchClassificationError(
            "OPENAI_API_KEY is not set in this terminal; do not paste it into "
            "project files"
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise BatchClassificationError(
            "The openai package is missing; run: conda env update --file "
            "environment.yml"
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
    raise BatchClassificationError("Could not serialize the OpenAI API response")


def submit(args: argparse.Namespace) -> int:
    _, _, _, episode_output = load_inputs(args)
    run_dir = resolve_run_dir(args, episode_output)
    manifest = json.loads(
        (run_dir / "request_manifest.json").read_text(encoding="utf-8")
    )
    input_path = run_dir / "batch_input.jsonl"
    if (
        not input_path.is_file()
        or sha256_file(input_path) != manifest["input"]["batch_input_sha256"]
    ):
        raise BatchClassificationError(
            "Prepared batch input is missing or its hash changed"
        )
    job_path = run_dir / "batch_job.json"
    previous: dict[str, Any] | None = None
    if job_path.exists():
        previous = json.loads(job_path.read_text(encoding="utf-8"))
    if previous and previous.get("batch_id"):
        raise BatchClassificationError(
            f"This run was already submitted as {previous.get('batch_id')}; "
            "refusing duplicate cost"
        )
    print("OpenAI Batch submission plan")
    print(f"  Windows sent: {manifest['input']['windows']}")
    print(f"  Requests:    {manifest['input']['requests']}")
    print(f"  Model:       {manifest['model']}")
    print(f"  Input file:  {input_path.relative_to(PROJECT_ROOT)}")
    print(
        "  External action: upload transcript excerpts and create a billable "
        "24-hour batch"
    )
    if not args.yes:
        raise BatchClassificationError(
            "Nothing submitted. Review the plan, then add --yes"
        )
    client, sdk_version = openai_client()
    if previous and previous.get("input_file_id"):
        input_file_id = previous["input_file_id"]
        print(f"Reusing previously uploaded input file: {input_file_id}")
    else:
        with input_path.open("rb") as handle:
            uploaded = client.files.create(file=handle, purpose="batch")
        input_file_id = uploaded.id
        write_json(
            job_path,
            {
                "schema_version": "0.1",
                "uploaded_at": utc_now(),
                "openai_python_version": sdk_version,
                "input_file_id": input_file_id,
                "state": "uploaded_not_submitted",
            },
        )
    batch = client.batches.create(
        input_file_id=input_file_id,
        endpoint=ENDPOINT,
        completion_window="24h",
        metadata={
            "project": "podcast_observational",
            "episode_id": manifest["episode_id"],
            "run_id": manifest["run_id"],
            "prompt_version": manifest["prompt_version"],
        },
    )
    job = {
        "schema_version": "0.1",
        "submitted_at": utc_now(),
        "openai_python_version": sdk_version,
        "input_file_id": input_file_id,
        "batch_id": batch.id,
        "state": "submitted",
        "batch": dump_api_object(batch),
    }
    write_json(job_path, job)
    print(f"Submitted batch: {batch.id}")
    print("Next: python code/04_classify_content_openai_batch.py status")
    return 0


def retrieve_job(
    args: argparse.Namespace,
) -> tuple[Any, dict[str, Any], Path, Any]:
    _, _, _, episode_output = load_inputs(args)
    run_dir = resolve_run_dir(args, episode_output)
    job_path = run_dir / "batch_job.json"
    if not job_path.is_file():
        raise BatchClassificationError("This run has not been submitted")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    client, _ = openai_client()
    batch = client.batches.retrieve(job["batch_id"])
    job["last_checked_at"] = utc_now()
    job["batch"] = dump_api_object(batch)
    write_json(job_path, job)
    return client, job, run_dir, batch


def status(args: argparse.Namespace) -> int:
    _, job, run_dir, batch = retrieve_job(args)
    counts = getattr(batch, "request_counts", None)
    completed = getattr(counts, "completed", 0) if counts else 0
    failed = getattr(counts, "failed", 0) if counts else 0
    total = getattr(counts, "total", 0) if counts else 0
    print(f"Batch:  {job['batch_id']}")
    print(f"Status: {batch.status}")
    print(f"Counts: {completed} completed, {failed} failed, {total} total")
    print(f"State:  {(run_dir / 'batch_job.json').relative_to(PROJECT_ROOT)}")
    if batch.status == "completed":
        print("Next: python code/04_classify_content_openai_batch.py collect")
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
    raise BatchClassificationError(f"Could not read API file {file_id}")


def parse_jsonl(content: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        content.decode("utf-8").splitlines(), 1
    ):
        if not raw_line.strip():
            continue
        try:
            rows.append(json.loads(raw_line))
        except json.JSONDecodeError as exc:
            raise BatchClassificationError(
                f"Invalid JSON on line {line_number} of {label}"
            ) from exc
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
        raise BatchClassificationError("Model refusal: " + "; ".join(refusals))
    if not texts:
        raise BatchClassificationError(
            "A successful response contained no output text"
        )
    return "".join(texts)


def parse_batch_results(
    output_rows: list[dict[str, Any]], manifest: dict[str, Any]
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    """Validate and index possibly out-of-order Batch API responses."""

    expected_windows = {
        window["custom_id"]: window for window in manifest["windows"]
    }
    seen_custom_ids: set[str] = set()
    classifications: dict[int, dict[str, Any]] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for row in output_rows:
        custom_id = row.get("custom_id")
        if custom_id not in expected_windows:
            raise BatchClassificationError(
                f"Unexpected custom_id in output: {custom_id}"
            )
        if custom_id in seen_custom_ids:
            raise BatchClassificationError(f"Duplicate output custom_id: {custom_id}")
        seen_custom_ids.add(custom_id)
        response = row.get("response") or {}
        if response.get("status_code") != 200 or row.get("error"):
            raise BatchClassificationError(
                f"Failed response for {custom_id}: {row.get('error')}"
            )
        body = response.get("body") or {}
        try:
            parsed = json.loads(extract_output_text(body))
        except json.JSONDecodeError as exc:
            raise BatchClassificationError(
                f"Invalid model JSON for {custom_id}"
            ) from exc
        if not isinstance(parsed, dict):
            raise BatchClassificationError(f"Invalid window result for {custom_id}")
        expected_id = int(expected_windows[custom_id]["window_id"])
        if parsed.get("window_id") != expected_id:
            raise BatchClassificationError(
                f"Window ID does not match the manifest for {custom_id}"
            )
        for label in ("health_related", "science_related"):
            if type(parsed.get(label)) is not bool:
                raise BatchClassificationError(
                    f"{label} is not boolean for window {expected_id}"
                )
        for rationale in ("health_rationale", "science_rationale"):
            if not isinstance(parsed.get(rationale), str):
                raise BatchClassificationError(
                    f"{rationale} is not text for window {expected_id}"
                )
        if expected_id in classifications:
            raise BatchClassificationError(
                f"Duplicate classification for window {expected_id}"
            )
        classifications[expected_id] = {
            **parsed,
            "batch_custom_id": custom_id,
            "response_id": body.get("id"),
            "response_model": body.get("model"),
        }
        body_usage = body.get("usage") or {}
        for name in usage:
            usage[name] += int(body_usage.get(name) or 0)
    missing_windows = sorted(set(expected_windows) - seen_custom_ids)
    if missing_windows:
        raise BatchClassificationError(
            f"Output is missing {len(missing_windows)} expected request(s)"
        )
    expected_count = int(manifest["input"]["windows"])
    if set(classifications) != set(range(expected_count)):
        raise BatchClassificationError(
            "Final classifications do not cover every transcript window"
        )
    return classifications, usage


def deterministic_audit_sample(identifier: str, fraction: float) -> bool:
    value = int(hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:8], 16)
    return value / 0xFFFFFFFF < fraction


def label_metrics(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    selected = [row for row in rows if row[label]]
    return {
        "windows": len(selected),
        "share_of_windows": (
            round(len(selected) / len(rows), 6) if rows else None
        ),
    }


def build_analytic_rows(
    windows: list[dict[str, Any]],
    episode_id: str,
    classifications: dict[int, dict[str, Any]],
    audit_fraction: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in windows:
        window_id = int(window["window_id"])
        classification = classifications[window_id]
        segments = window["speaker_segments"]
        speakers = list(dict.fromkeys(segment["speaker"] for segment in segments))
        positive = (
            classification["health_related"]
            or classification["science_related"]
        )
        negative_audit = (not positive) and deterministic_audit_sample(
            f"{episode_id}:{window_id}", audit_fraction
        )
        rows.append(
            {
                "episode_id": episode_id,
                "window_id": window_id,
                "word_start_index": window["word_start_index"],
                "word_end_index_exclusive": window["word_end_index_exclusive"],
                "word_count": window["word_count"],
                "utterance_start_id": window["utterance_start_id"],
                "utterance_end_id": window["utterance_end_id"],
                "start_ms": window["start_ms"],
                "end_ms": window["end_ms"],
                "duration_seconds": (
                    window["end_ms"] - window["start_ms"]
                ) / 1000,
                "speakers": " | ".join(speakers),
                "text": " ".join(segment["text"] for segment in segments),
                "speaker_segments_json": json.dumps(
                    segments, ensure_ascii=False, separators=(",", ":")
                ),
                "mean_word_confidence": window["mean_word_confidence"],
                "health_related": int(classification["health_related"]),
                "science_related": int(classification["science_related"]),
                "health_rationale": classification["health_rationale"],
                "science_rationale": classification["science_rationale"],
                "negative_audit_sample": int(negative_audit),
                "needs_review": int(positive or negative_audit),
                "batch_custom_id": classification["batch_custom_id"],
                "response_id": classification["response_id"],
                "response_model": classification["response_model"],
            }
        )
    return rows


def build_summary(
    rows: list[dict[str, Any]],
    transcript: dict[str, Any],
    manifest: dict[str, Any],
    job: dict[str, Any],
    usage: dict[str, int],
) -> dict[str, Any]:
    totals: dict[str, Any] = {
        "windows": len(rows),
        "health_related": label_metrics(rows, "health_related"),
        "science_related": label_metrics(rows, "science_related"),
        "health_and_science": label_metrics(
            [
                {
                    **row,
                    "health_and_science": int(
                        row["health_related"] and row["science_related"]
                    ),
                }
                for row in rows
            ],
            "health_and_science",
        ),
    }
    return {
        "schema_version": "0.1",
        "generated_at": utc_now(),
        "status": "provisional_model_assisted_not_human_validated",
        "unit": "overlapping_256_word_window",
        "episode": transcript.get("episode"),
        "method": {
            "provider": "OpenAI",
            "api": "Batch API with Responses API and Structured Outputs",
            "model_requested": manifest["model"],
            "models_returned": sorted(
                {
                    row["response_model"]
                    for row in rows
                    if row["response_model"]
                }
            ),
            "prompt_version": manifest["prompt_version"],
            "run_id": manifest["run_id"],
            "batch_id": job["batch_id"],
            "openai_python_version": job["openai_python_version"],
            "usage": usage,
        },
        "input": manifest["input"],
        "windowing": manifest["windowing"],
        "totals": totals,
        "interpretation_note": (
            "Because windows overlap, shares describe classified windows. They "
            "must not be interpreted as non-overlapping shares of words, time, "
            "or speaker-specific speech."
        ),
        "review": {
            "rows_marked_for_review": sum(row["needs_review"] for row in rows),
            "positive_rows": sum(
                int(row["health_related"] or row["science_related"])
                for row in rows
            ),
            "negative_audit_rows": sum(
                row["negative_audit_sample"] for row in rows
            ),
        },
    }


def write_analytic_outputs(
    rows: list[dict[str, Any]], summary: dict[str, Any], run_dir: Path
) -> None:
    fields = list(rows[0])
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(run_dir / "window_classification.csv", buffer.getvalue())
    write_json(run_dir / "classification_summary.json", summary)


def collect(args: argparse.Namespace) -> int:
    transcript, _, transcript_path, _ = load_inputs(args)
    client, job, run_dir, batch = retrieve_job(args)
    manifest = json.loads(
        (run_dir / "request_manifest.json").read_text(encoding="utf-8")
    )
    if sha256_file(transcript_path) != manifest["input"]["transcript_sha256"]:
        raise BatchClassificationError(
            "The transcript changed after prepare; refusing to join results"
        )
    if batch.status != "completed":
        if batch.status in TERMINAL_BATCH_STATUSES:
            raise BatchClassificationError(
                f"Batch ended with status: {batch.status}"
            )
        raise BatchClassificationError(
            f"Batch is still {batch.status}; run status later and collect when "
            "completed"
        )
    if not batch.output_file_id:
        raise BatchClassificationError("Completed batch has no output_file_id")
    output_bytes = api_file_bytes(client, batch.output_file_id)
    atomic_write(run_dir / "batch_output.jsonl", output_bytes)
    if batch.error_file_id:
        error_bytes = api_file_bytes(client, batch.error_file_id)
        atomic_write(run_dir / "batch_errors.jsonl", error_bytes)
        errors = parse_jsonl(error_bytes, "batch error file")
        if errors:
            raise BatchClassificationError(
                f"Batch has {len(errors)} failed request(s); retained "
                "batch_errors.jsonl"
            )
    output_rows = parse_jsonl(output_bytes, "batch output file")
    classifications, usage = parse_batch_results(output_rows, manifest)
    words = flatten_transcript_words(transcript["utterances"])
    windows = build_word_windows(words, manifest["windowing"])
    if len(windows) != manifest["input"]["windows"]:
        raise BatchClassificationError(
            "Reconstructed window count differs from the prepared manifest"
        )
    analytic_rows = build_analytic_rows(
        windows,
        str(transcript.get("episode", {}).get("youtube_video_id") or ""),
        classifications,
        float(manifest["negative_audit_fraction"]),
    )
    summary = build_summary(analytic_rows, transcript, manifest, job, usage)
    write_analytic_outputs(analytic_rows, summary, run_dir)
    print("Collected and validated every transcript window")
    print(
        f"  Health-related:  {summary['totals']['health_related']['windows']} windows"
    )
    print(
        f"  Science-related: {summary['totals']['science_related']['windows']} windows"
    )
    print(f"  Review rows:     {summary['review']['rows_marked_for_review']}")
    print(f"  Output:          {run_dir.relative_to(PROJECT_ROOT)}")
    print("Status: provisional until human validation.")
    return 0


def add_common_arguments(
    parser: argparse.ArgumentParser, include_run: bool = False
) -> None:
    parser.add_argument(
        "--show-directory", default="the_joe_rogan_experience"
    )
    parser.add_argument("--video-id", default="BAhcDwMGKYU")
    if include_run:
        parser.add_argument(
            "--run-id", help="Prepared run ID; defaults to latest prepared run"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser(
        "prepare", help="Create the local Batch JSONL file"
    )
    add_common_arguments(prepare_parser)
    submit_parser = commands.add_parser(
        "submit", help="Upload transcript excerpts and submit a paid batch"
    )
    add_common_arguments(submit_parser, include_run=True)
    submit_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm transcript upload and API charges",
    )
    status_parser = commands.add_parser(
        "status", help="Refresh remote batch status"
    )
    add_common_arguments(status_parser, include_run=True)
    collect_parser = commands.add_parser(
        "collect", help="Download and validate completed results"
    )
    add_common_arguments(collect_parser, include_run=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    actions = {
        "prepare": prepare,
        "submit": submit,
        "status": status,
        "collect": collect,
    }
    try:
        return actions[args.command](args)
    except (
        BatchClassificationError,
        OSError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if exc.__class__.__module__.startswith("openai"):
            print(f"ERROR: OpenAI API request failed: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
