#!/usr/bin/env python3
"""Classify existing broad-run claims by health object and claim focus.

The pipeline deduplicates exact claims repeated by overlapping windows, selects
the most centered 256-word context, classifies each statement unit once through
OpenAI Batch, and propagates the result to every original claim instance.
Existing broad-fringe fields are carried through without modification.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import runpy
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = runpy.run_path(str(ROOT / "code/05_classify_passage_content_openai_batch.py"))
DEFAULT_INPUT = ROOT / "data/derived/classifications/broad_fringe/5a165612d6459da0/broad_window_classification.csv"
CONFIG = ROOT / "config/health_object_classification.json"
RUN_ROOT = ROOT / "data/derived/classifications/health_objects"
WORD = re.compile(r"\S+")
NORMALIZED_TOKEN = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    BASE["write_json"](path, value)


def freeze(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ValueError(f"Refusing to overwrite frozen input: {path}")
    if not path.exists():
        BASE["atomic_write"](path, content)


def normalized(text: str) -> str:
    return " ".join(
        match.group(0).casefold().replace("’", "'")
        for match in NORMALIZED_TOKEN.finditer(text)
    )


def locate_claim(row: dict[str, str], claim: dict[str, Any]) -> dict[str, int] | None:
    """Locate an aligned source quotation in the 256 whitespace-token window."""
    quote = str(claim.get("exact_claim_text") or "")
    if claim.get("quote_match_method") == "unmatched" or not quote:
        return None
    starts = [match.start() for match in re.finditer(re.escape(quote), row["snippet_text"])]
    if len(starts) != 1:
        return None
    char_start, char_end = starts[0], starts[0] + len(quote)
    words = list(WORD.finditer(row["snippet_text"]))
    touched = [
        index for index, match in enumerate(words)
        if match.end() > char_start and match.start() < char_end
    ]
    if not touched:
        return None
    local_start, local_end = touched[0], touched[-1] + 1
    global_start = int(row["word_start_index"]) + local_start
    global_end = int(row["word_start_index"]) + local_end
    return {
        "local_start": local_start,
        "local_end": local_end,
        "global_start": global_start,
        "global_end": global_end,
    }


def build_statement_units(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    instances: list[dict[str, Any]] = []
    seen_claim_ids: set[str] = set()
    for row in rows:
        if len(row["snippet_text"].split()) != 256:
            raise ValueError(f"Window does not contain 256 words: {row['snippet_id']}")
        claims = json.loads(row["claims_json"])
        if len(claims) != int(row["claim_count"]):
            raise ValueError(f"Claim count mismatch: {row['snippet_id']}")
        for claim in claims:
            claim_id = claim["claim_id"]
            if claim_id in seen_claim_ids:
                raise ValueError(f"Duplicate claim ID: {claim_id}")
            seen_claim_ids.add(claim_id)
            location = locate_claim(row, claim)
            if location:
                group_key = (
                    "aligned", row["episode_id"], location["global_start"],
                    location["global_end"], normalized(claim["exact_claim_text"]),
                )
                span_status = "aligned"
            else:
                group_key = ("singleton", claim_id)
                span_status = (
                    "unmatched" if claim.get("quote_match_method") == "unmatched"
                    else "ambiguous_location"
                )
            instance = {
                "claim_instance_id": claim_id,
                "snippet_id": row["snippet_id"],
                "show": row["show"],
                "episode_id": row["episode_id"],
                "episode_title": row["episode_title"],
                "guest": row["guest"],
                "published_date": row["published_date"],
                "window_id": int(row["window_id"]),
                "window_word_start": int(row["word_start_index"]),
                "window_word_end": int(row["word_end_index_exclusive"]),
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
                "snippet_text": row["snippet_text"],
                "span_status": span_status,
                "location": location,
                "claim": claim,
                "existing_health_related": int(row["health_related"]),
                "existing_science_related": int(row["science_related"]),
            }
            groups[group_key].append(instance)
            instances.append(instance)

    units: list[dict[str, Any]] = []
    seen_unit_ids: set[str] = set()
    for group_key, members in groups.items():
        unit_id = "statement-" + digest(canonical(group_key).encode())[:20]
        if unit_id in seen_unit_ids:
            raise ValueError(f"Statement-unit hash collision: {unit_id}")
        seen_unit_ids.add(unit_id)
        representative = max(
            members,
            key=lambda item: (
                min(item["location"]["local_start"], 256 - item["location"]["local_end"])
                if item["location"] else -1,
                -item["window_id"],
            ),
        )
        for item in members:
            item["statement_unit_id"] = unit_id
            item["is_representative"] = int(item is representative)
        location = representative["location"]
        units.append({
            "statement_unit_id": unit_id,
            "show": representative["show"],
            "episode_id": representative["episode_id"],
            "episode_title": representative["episode_title"],
            "guest": representative["guest"],
            "published_date": representative["published_date"],
            "source_span_status": representative["span_status"],
            "source_word_start": location["global_start"] if location else None,
            "source_word_end_exclusive": location["global_end"] if location else None,
            "exact_claim_text": representative["claim"]["exact_claim_text"] or representative["claim"]["model_claim_text"],
            "normalized_claim_text": normalized(representative["claim"]["exact_claim_text"] or representative["claim"]["model_claim_text"]),
            "representative_claim_instance_id": representative["claim_instance_id"],
            "representative_snippet_id": representative["snippet_id"],
            "representative_window_id": representative["window_id"],
            "representative_snippet_text": representative["snippet_text"],
            "existing_claim_domain": representative["claim"]["claim_domain"],
            "claim_instance_count": len(members),
            "claim_instance_ids": [item["claim_instance_id"] for item in members],
        })
    units.sort(key=lambda item: (
        item["show"], item["episode_id"],
        item["source_word_start"] if item["source_word_start"] is not None else 10**12,
        item["statement_unit_id"],
    ))
    instances.sort(key=lambda item: (item["show"], item["episode_id"], item["window_id"], item["claim_instance_id"]))
    if sum(unit["claim_instance_count"] for unit in units) != len(instances):
        raise ValueError("Statement-unit mapping does not cover every claim instance")
    return units, instances


def schema(config: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "statement_unit_id": {"type": "string"},
        "extraction_quality": {"type": "string", "enum": list(config["extraction_quality"])},
        "primary_object": {"type": "string", "enum": list(config["object_categories"])},
        "secondary_objects": {
            "type": "array", "items": {"type": "string", "enum": list(config["object_categories"])},
        },
        "claim_focus": {"type": "string", "enum": list(config["claim_focuses"])},
        "product_maturity": {"type": "string", "enum": list(config["product_maturity"])},
        "classification_reason": {"type": "string"},
    }
    item = {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    return {
        "type": "object",
        "properties": {
            "snippet_id": {"type": "string"},
            "classifications": {"type": "array", "items": item},
        },
        "required": ["snippet_id", "classifications"],
        "additionalProperties": False,
    }


def instructions(config: dict[str, Any]) -> str:
    sections = [
        "You are a helpful research assistant classifying what health product, intervention, "
        "behavior, condition, or science subject each existing podcast statement concerns. "
        "This is a descriptive content classification, not an assessment of truth.",
        "Object categories:\n" + "\n".join(f"- {key}: {value}" for key, value in config["object_categories"].items()),
        "Claim focuses:\n" + "\n".join(f"- {key}: {value}" for key, value in config["claim_focuses"].items()),
        "Product maturity:\n" + "\n".join(f"- {key}: {value}" for key, value in config["product_maturity"].items()),
        "Extraction quality:\n" + "\n".join(f"- {key}: {value}" for key, value in config["extraction_quality"].items()),
        "Rules:\n" + "\n".join(f"- {rule}" for rule in config["rules"]),
        "Reason format: " + config["reason_rule"],
        "Return exactly one classification for each supplied statement_unit_id and preserve snippet_id and statement_unit_id exactly.",
    ]
    return "\n\n".join(sections)


def validate_classification(
    value: dict[str, Any], snippet_id: str, expected_units: set[str], config: dict[str, Any]
) -> None:
    if not isinstance(value, dict) or set(value) != {"snippet_id", "classifications"}:
        raise ValueError(f"Invalid response structure: {snippet_id}")
    if value["snippet_id"] != snippet_id or not isinstance(value["classifications"], list):
        raise ValueError(f"Snippet ID or classifications mismatch: {snippet_id}")
    returned: set[str] = set()
    expected_fields = set(schema(config)["properties"]["classifications"]["items"]["properties"])
    for result in value["classifications"]:
        if not isinstance(result, dict) or set(result) != expected_fields:
            raise ValueError(f"Invalid classification fields: {snippet_id}")
        unit_id = result["statement_unit_id"]
        if unit_id not in expected_units or unit_id in returned:
            raise ValueError(f"Unexpected or duplicate statement unit: {unit_id}")
        returned.add(unit_id)
        if result["extraction_quality"] not in config["extraction_quality"]:
            raise ValueError(f"Invalid extraction quality: {unit_id}")
        if result["primary_object"] not in config["object_categories"]:
            raise ValueError(f"Invalid primary object: {unit_id}")
        secondaries = result["secondary_objects"]
        if (
            not isinstance(secondaries, list) or len(secondaries) > 2
            or len(set(secondaries)) != len(secondaries)
            or any(item not in config["object_categories"] for item in secondaries)
            or result["primary_object"] in secondaries
        ):
            raise ValueError(f"Invalid secondary objects: {unit_id}")
        if result["claim_focus"] not in config["claim_focuses"]:
            raise ValueError(f"Invalid claim focus: {unit_id}")
        if result["product_maturity"] not in config["product_maturity"]:
            raise ValueError(f"Invalid product maturity: {unit_id}")
        reason = result["classification_reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Missing classification reason: {unit_id}")
        if result["extraction_quality"] == "not_checkable" and (
            result["primary_object"] != "unclear" or secondaries
            or result["product_maturity"] != "not_applicable"
        ):
            raise ValueError(f"Invalid nonclaim coding combination: {unit_id}")
    if returned != expected_units:
        raise ValueError(f"Missing statement classifications for {snippet_id}")


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, 1):
        current = [row]
        for column, right_char in enumerate(right, 1):
            current.append(min(
                current[-1] + 1, previous[column] + 1,
                previous[column - 1] + int(left_char != right_char),
            ))
        previous = current
    return previous[-1]


def recover_statement_ids(
    value: dict[str, Any], expected_units: set[str]
) -> tuple[dict[str, Any], int]:
    """Recover rare one/two-character corruption of opaque structured IDs."""
    returned = value.get("classifications")
    if not isinstance(returned, list):
        return value, 0
    used: set[str] = set()
    recovered = 0
    for classification in returned:
        candidate = classification.get("statement_unit_id")
        if candidate in expected_units and candidate not in used:
            used.add(candidate)
            continue
        cleaned = str(candidate).replace(" ", "")
        matches = [
            unit_id for unit_id in expected_units - used
            if edit_distance(cleaned, unit_id) <= 4
        ]
        if len(matches) != 1:
            continue
        classification["model_statement_unit_id"] = candidate
        classification["statement_unit_id"] = matches[0]
        used.add(matches[0])
        recovered += 1
    return value, recovered


def read_source(path: Path) -> list[dict[str, str]]:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT / "data/derived"):
        raise ValueError("Input must be inside this project's data/derived directory")
    with resolved.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 4124 or len({row["snippet_id"] for row in rows}) != len(rows):
        raise ValueError("Expected the complete frozen 4,124-window pilot")
    required = {
        "show", "episode_id", "snippet_id", "snippet_text", "claims_json",
        "word_start_index", "word_end_index_exclusive", "claim_count",
    }
    if not required.issubset(rows[0]):
        raise ValueError("Input is not a broad-window classification CSV")
    return rows


def prepare(args: argparse.Namespace) -> None:
    config = load(CONFIG)
    rows = read_source(args.input)
    units, instances = build_statement_units(rows)
    units_by_snippet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in units:
        units_by_snippet[unit["representative_snippet_id"]].append(unit)
    prompt, output_schema = instructions(config), schema(config)
    requests = []
    for snippet_id, selected in sorted(units_by_snippet.items()):
        representative = selected[0]
        payload = {
            "snippet_id": snippet_id,
            "published_date": representative["published_date"],
            "episode_title": representative["episode_title"],
            "transcript_window": representative["representative_snippet_text"],
            "statements": [
                {
                    "statement_unit_id": unit["statement_unit_id"],
                    "exact_claim_text": unit["exact_claim_text"],
                    "existing_claim_domain": unit["existing_claim_domain"],
                }
                for unit in selected
            ],
        }
        requests.append({
            "custom_id": snippet_id,
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": config["model"],
                "reasoning": {"effort": config["reasoning_effort"]},
                "max_output_tokens": config["max_output_tokens"],
                "store": False,
                "instructions": prompt,
                "input": canonical(payload),
                "text": {"format": {
                    "type": "json_schema", "name": "health_object_window",
                    "schema": output_schema, "strict": True,
                }},
            },
        })
    unit_payload = [{**unit, "claim_instance_ids": unit["claim_instance_ids"]} for unit in units]
    instance_payload = [
        {
            "claim_instance_id": item["claim_instance_id"],
            "statement_unit_id": item["statement_unit_id"],
            "snippet_id": item["snippet_id"],
            "is_representative": item["is_representative"],
            "span_status": item["span_status"],
        }
        for item in instances
    ]
    frozen = {
        "config.json": canonical(config) + "\n",
        "statement_units.json": canonical(unit_payload) + "\n",
        "instance_mapping.json": canonical(instance_payload) + "\n",
        "instructions.txt": prompt + "\n",
        "response_schema.json": canonical(output_schema) + "\n",
        "batch_input.jsonl": "".join(canonical(request) + "\n" for request in requests),
    }
    run_id = digest(canonical(frozen).encode())[:16]
    run = RUN_ROOT / run_id
    for name, content in frozen.items():
        freeze(run / name, content)
    if not (run / "manifest.json").exists():
        write(run / "manifest.json", {
            "run_id": run_id,
            "created_at": BASE["utc_now"](),
            "prompt_version": config["prompt_version"],
            "model": config["model"],
            "source": str(args.input.resolve().relative_to(ROOT)),
            "source_sha256": digest(args.input.read_bytes()),
            "windows": len(rows),
            "claim_instances": len(instances),
            "statement_units": len(units),
            "aligned_statement_units": sum(unit["source_span_status"] == "aligned" for unit in units),
            "unresolved_statement_units": sum(unit["source_span_status"] != "aligned" for unit in units),
            "requests": len(requests),
            "script_sha256": digest(Path(__file__).read_bytes()),
            "config_source_sha256": digest(CONFIG.read_bytes()),
            "files": {name: digest(content.encode()) for name, content in frozen.items()},
        })
    write(RUN_ROOT / "latest_prepared_run.json", {"run_id": run_id})
    print(f"Prepared {len(units):,} unique statement units from {len(instances):,} claim instances.")
    print(f"Prepared {len(requests):,} Batch requests. Run: {run_id}")
    print(f"Prompt: {run / 'instructions.txt'}")
    print("Prepared locally; not submitted.")


def resolve(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    run_id = args.run_id or load(RUN_ROOT / "latest_prepared_run.json")["run_id"]
    if len(run_id) != 16 or any(char not in "0123456789abcdef" for char in run_id):
        raise ValueError("Invalid run ID")
    run = RUN_ROOT / run_id
    manifest = load(run / "manifest.json")
    for name, expected in manifest["files"].items():
        if digest((run / name).read_bytes()) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    return run, manifest


def submit(args: argparse.Namespace) -> None:
    run, manifest = resolve(args)
    if not args.yes:
        raise ValueError("submit --yes confirms the authorized transcript upload and API charge")
    if (run / "batch_job.json").exists():
        print("Existing job:", load(run / "batch_job.json")["id"])
        return
    client, sdk = BASE["openai_client"]()
    upload_path = run / "upload.json"
    if not upload_path.exists():
        with (run / "batch_input.jsonl").open("rb") as handle:
            uploaded = client.files.create(file=handle, purpose="batch")
        write(upload_path, {"file_id": uploaded.id})
    batch = client.batches.create(
        input_file_id=load(upload_path)["file_id"], endpoint="/v1/responses",
        completion_window="24h", metadata={"run_id": manifest["run_id"]},
    )
    write(run / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Submitted:", batch.id, "Status:", batch.status, "Requests:", manifest["requests"])


def retrieve(run: Path) -> tuple[Any, Any]:
    client, sdk = BASE["openai_client"]()
    batch = client.batches.retrieve(load(run / "batch_job.json")["id"])
    write(run / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Batch:", batch.id, "Status:", batch.status, "Counts:", batch.request_counts)
    return client, batch


def status(args: argparse.Namespace) -> None:
    run, _ = resolve(args)
    retrieve(run)


def incomplete_request_ids(run: Path) -> list[str]:
    incomplete: list[str] = []
    for raw in BASE["parse_jsonl"]((run / "batch_output.jsonl").read_bytes(), "health-object batch output"):
        body = ((raw.get("response") or {}).get("body") or {})
        try:
            json.loads(BASE["extract_output_text"](body))
        except (ValueError, json.JSONDecodeError, BASE["PassageClassificationError"]):
            incomplete.append(raw.get("custom_id"))
            continue
        if body.get("status") not in (None, "completed"):
            incomplete.append(raw.get("custom_id"))
    return sorted(set(incomplete))


def repair(args: argparse.Namespace) -> None:
    run, manifest = resolve(args)
    if not args.yes:
        raise ValueError("repair --yes confirms the authorized retry and API charge")
    if not (run / "batch_output.jsonl").exists():
        raise ValueError("Collect the primary provider output before preparing repairs")
    repair_dir = run / "repair"
    repair_ids = set(incomplete_request_ids(run))
    if not repair_ids:
        print("No incomplete requests need repair.")
        return
    requests = []
    for line in (run / "batch_input.jsonl").read_text(encoding="utf-8").splitlines():
        request = json.loads(line)
        if request["custom_id"] in repair_ids:
            request["body"]["max_output_tokens"] = 20000
            requests.append(request)
    if {request["custom_id"] for request in requests} != repair_ids:
        raise ValueError("Could not reconstruct every incomplete request")
    freeze(repair_dir / "batch_input.jsonl", "".join(canonical(request) + "\n" for request in requests))
    write(repair_dir / "manifest.json", {
        "parent_run_id": manifest["run_id"], "created_at": BASE["utc_now"](),
        "requests": len(requests), "custom_ids": sorted(repair_ids),
        "max_output_tokens": 20000,
        "input_sha256": digest((repair_dir / "batch_input.jsonl").read_bytes()),
    })
    if (repair_dir / "batch_job.json").exists():
        print("Existing repair job:", load(repair_dir / "batch_job.json")["id"])
        return
    client, sdk = BASE["openai_client"]()
    upload_path = repair_dir / "upload.json"
    if not upload_path.exists():
        with (repair_dir / "batch_input.jsonl").open("rb") as handle:
            uploaded = client.files.create(file=handle, purpose="batch")
        write(upload_path, {"file_id": uploaded.id})
    batch = client.batches.create(
        input_file_id=load(upload_path)["file_id"], endpoint="/v1/responses",
        completion_window="24h", metadata={"run_id": manifest["run_id"], "repair": "1"},
    )
    write(repair_dir / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Submitted repair:", batch.id, "Status:", batch.status, "Requests:", len(requests))


def repair_status(args: argparse.Namespace) -> None:
    run, _ = resolve(args)
    repair_dir = run / "repair"
    client, sdk = BASE["openai_client"]()
    batch = client.batches.retrieve(load(repair_dir / "batch_job.json")["id"])
    write(repair_dir / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Repair batch:", batch.id, "Status:", batch.status, "Counts:", batch.request_counts)


def repair_split(args: argparse.Namespace) -> None:
    run, manifest = resolve(args)
    if not args.yes:
        raise ValueError("repair-split --yes confirms the authorized retry and API charge")
    source_output = run / "repair" / "batch_output.jsonl"
    if not source_output.exists():
        raise ValueError("The first repair output has not been collected")
    bad_ids: set[str] = set()
    for raw in BASE["parse_jsonl"](source_output.read_bytes(), "first repair output"):
        body = ((raw.get("response") or {}).get("body") or {})
        try:
            json.loads(BASE["extract_output_text"](body))
        except (ValueError, json.JSONDecodeError, BASE["PassageClassificationError"]):
            bad_ids.add(raw["custom_id"])
            continue
        if body.get("status") not in (None, "completed"):
            bad_ids.add(raw["custom_id"])
    if not bad_ids:
        print("No requests need a split repair.")
        return
    split_dir = run / "repair_split"
    requests = []
    request_map = {}
    counter = 0
    for line in (run / "batch_input.jsonl").read_text(encoding="utf-8").splitlines():
        original = json.loads(line)
        if original["custom_id"] not in bad_ids:
            continue
        payload = json.loads(original["body"]["input"])
        for statement in payload["statements"]:
            counter += 1
            custom_id = f"split-{counter:05d}"
            split_payload = {**payload, "statements": [statement]}
            request = json.loads(canonical(original))
            request["custom_id"] = custom_id
            request["body"]["input"] = canonical(split_payload)
            request["body"]["max_output_tokens"] = 5000
            requests.append(request)
            request_map[custom_id] = {
                "snippet_id": original["custom_id"],
                "statement_unit_id": statement["statement_unit_id"],
            }
    freeze(split_dir / "batch_input.jsonl", "".join(canonical(request) + "\n" for request in requests))
    write(split_dir / "manifest.json", {
        "parent_run_id": manifest["run_id"], "created_at": BASE["utc_now"](),
        "requests": len(requests), "request_map": request_map,
        "input_sha256": digest((split_dir / "batch_input.jsonl").read_bytes()),
    })
    if (split_dir / "batch_job.json").exists():
        print("Existing split-repair job:", load(split_dir / "batch_job.json")["id"])
        return
    client, sdk = BASE["openai_client"]()
    upload_path = split_dir / "upload.json"
    if not upload_path.exists():
        with (split_dir / "batch_input.jsonl").open("rb") as handle:
            uploaded = client.files.create(file=handle, purpose="batch")
        write(upload_path, {"file_id": uploaded.id})
    batch = client.batches.create(
        input_file_id=load(upload_path)["file_id"], endpoint="/v1/responses",
        completion_window="24h", metadata={"run_id": manifest["run_id"], "repair": "split"},
    )
    write(split_dir / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Submitted split repair:", batch.id, "Status:", batch.status, "Requests:", len(requests))


def repair_split_status(args: argparse.Namespace) -> None:
    run, _ = resolve(args)
    split_dir = run / "repair_split"
    client, sdk = BASE["openai_client"]()
    batch = client.batches.retrieve(load(split_dir / "batch_job.json")["id"])
    write(split_dir / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Split repair:", batch.id, "Status:", batch.status, "Counts:", batch.request_counts)


def ensure_repair_output(run: Path) -> None:
    repair_dir = run / "repair"
    if not (repair_dir / "batch_job.json").exists() or (repair_dir / "batch_output.jsonl").exists():
        return
    client, sdk = BASE["openai_client"]()
    batch = client.batches.retrieve(load(repair_dir / "batch_job.json")["id"])
    write(repair_dir / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    if batch.status not in BASE["TERMINAL_BATCH_STATUSES"]:
        raise ValueError(f"Repair batch still {batch.status}; collect once complete")
    BASE["download_batch_results"](client, batch, repair_dir)


def ensure_split_repair_output(run: Path) -> None:
    split_dir = run / "repair_split"
    if not (split_dir / "batch_job.json").exists() or (split_dir / "batch_output.jsonl").exists():
        return
    client, sdk = BASE["openai_client"]()
    batch = client.batches.retrieve(load(split_dir / "batch_job.json")["id"])
    write(split_dir / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    if batch.status not in BASE["TERMINAL_BATCH_STATUSES"]:
        raise ValueError(f"Split repair still {batch.status}; collect once complete")
    BASE["download_batch_results"](client, batch, split_dir)


def csv_text(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def summary_rows(
    units: list[dict[str, Any]], instances: list[dict[str, Any]], field: str, values: list[str]
) -> list[dict[str, Any]]:
    unit_counts = Counter(unit[field] for unit in units)
    instance_counts = Counter(item[field] for item in instances)
    return [
        {
            "category": value,
            "unique_statement_units": unit_counts[value],
            "unique_statement_percent": round(100 * unit_counts[value] / len(units), 6),
            "claim_instances": instance_counts[value],
            "claim_instance_percent": round(100 * instance_counts[value] / len(instances), 6),
        }
        for value in values
    ]


def collect(args: argparse.Namespace) -> None:
    run, manifest = resolve(args)
    output_path = run / "batch_output.jsonl"
    if not output_path.exists():
        client, batch = retrieve(run)
        if batch.status not in BASE["TERMINAL_BATCH_STATUSES"]:
            raise ValueError(f"Batch still {batch.status}; collect once complete")
        BASE["download_batch_results"](client, batch, run)
    config = load(run / "config.json")
    ensure_repair_output(run)
    ensure_split_repair_output(run)
    units = load(run / "statement_units.json")
    mapping = load(run / "instance_mapping.json")
    by_snippet: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        by_snippet[unit["representative_snippet_id"]].add(unit["statement_unit_id"])
    expected = set(by_snippet)
    results: dict[str, dict[str, Any]] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    raw_rows = BASE["parse_jsonl"](output_path.read_bytes(), "health-object batch output")
    repair_output = run / "repair" / "batch_output.jsonl"
    repair_ids = set()
    if repair_output.exists():
        repair_rows = BASE["parse_jsonl"](repair_output.read_bytes(), "health-object repair output")
        repair_ids = {row.get("custom_id") for row in repair_rows}
        raw_rows = [row for row in raw_rows if row.get("custom_id") not in repair_ids] + repair_rows
    split_output = run / "repair_split" / "batch_output.jsonl"
    split_request_count = 0
    if split_output.exists():
        split_manifest = load(run / "repair_split" / "manifest.json")
        grouped: dict[str, dict[str, Any]] = {}
        for raw in BASE["parse_jsonl"](split_output.read_bytes(), "split repair output"):
            split_request_count += 1
            custom_id = raw.get("custom_id")
            link = split_manifest["request_map"].get(custom_id)
            body = ((raw.get("response") or {}).get("body") or {})
            if not link or raw.get("error") or (raw.get("response") or {}).get("status_code") != 200 or body.get("status") not in (None, "completed"):
                raise ValueError(f"Invalid split-repair response: {custom_id}")
            value = json.loads(BASE["extract_output_text"](body))
            classification = value.get("classifications")
            if not isinstance(classification, list) or len(classification) != 1:
                raise ValueError(f"Split repair did not return one classification: {custom_id}")
            item = grouped.setdefault(link["snippet_id"], {
                "classifications": [], "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "ids": [], "models": [],
            })
            item["classifications"].extend(classification)
            item["ids"].append(body.get("id", "")); item["models"].append(body.get("model", ""))
            for field in item["usage"]:
                item["usage"][field] += int((body.get("usage") or {}).get(field) or 0)
        split_ids = set(grouped)
        synthetic = []
        for snippet_id, item in grouped.items():
            synthetic.append({
                "custom_id": snippet_id,
                "response": {"status_code": 200, "body": {
                    "status": "completed", "id": " | ".join(item["ids"]),
                    "model": item["models"][0] if item["models"] else "",
                    "usage": item["usage"],
                    "output": [{"type": "message", "content": [{
                        "type": "output_text", "text": canonical({
                            "snippet_id": snippet_id, "classifications": item["classifications"],
                        }),
                    }]}],
                }},
            })
        raw_rows = [row for row in raw_rows if row.get("custom_id") not in split_ids] + synthetic
    recovered_id_count = 0
    recovered_snippet_id_count = 0
    recovered_secondary_units: set[str] = set()
    for raw in raw_rows:
        snippet_id = raw.get("custom_id")
        response = raw.get("response") or {}
        if snippet_id not in expected or snippet_id in results or raw.get("error") or response.get("status_code") != 200:
            raise ValueError(f"Unexpected, duplicate, or failed result: {snippet_id}")
        body = response.get("body") or {}
        if body.get("status") not in (None, "completed"):
            raise ValueError(f"Incomplete response: {snippet_id}")
        value = json.loads(BASE["extract_output_text"](body))
        if value.get("snippet_id") != snippet_id:
            value["snippet_id"] = snippet_id
            recovered_snippet_id_count += 1
        value, recovered = recover_statement_ids(value, by_snippet[snippet_id])
        recovered_id_count += recovered
        for classification in value.get("classifications", []):
            classification.pop("model_statement_unit_id", None)
            original_secondary = classification.get("secondary_objects")
            if isinstance(original_secondary, list):
                cleaned_secondary = []
                for item in original_secondary:
                    if item != classification.get("primary_object") and item not in cleaned_secondary:
                        cleaned_secondary.append(item)
                if cleaned_secondary != original_secondary:
                    recovered_secondary_units.add(classification.get("statement_unit_id"))
                    classification["secondary_objects"] = cleaned_secondary[:2]
        validate_classification(value, snippet_id, by_snippet[snippet_id], config)
        results[snippet_id] = {
            **value, "response_id": body.get("id", ""), "response_model": body.get("model", ""),
        }
        for field in usage:
            usage[field] += int((body.get("usage") or {}).get(field) or 0)
    if set(results) != expected:
        raise ValueError(f"Missing {len(expected - set(results))} request results")
    classification_by_unit: dict[str, dict[str, Any]] = {}
    provenance_by_unit: dict[str, dict[str, str]] = {}
    for result in results.values():
        for classification in result["classifications"]:
            unit_id = classification["statement_unit_id"]
            classification_by_unit[unit_id] = classification
            provenance_by_unit[unit_id] = {
                "response_id": result["response_id"], "response_model": result["response_model"],
            }
    if set(classification_by_unit) != {unit["statement_unit_id"] for unit in units}:
        raise ValueError("Collected classifications do not cover every statement unit")

    unit_rows: list[dict[str, Any]] = []
    unit_by_id: dict[str, dict[str, Any]] = {}
    for unit in units:
        unit_id = unit["statement_unit_id"]
        classification = classification_by_unit[unit_id]
        row = {
            **{key: value for key, value in unit.items() if key not in {"claim_instance_ids"}},
            "claim_instance_ids": " | ".join(unit["claim_instance_ids"]),
            **classification,
            "secondary_objects": " | ".join(classification["secondary_objects"]),
            "reason_word_count": len(classification["classification_reason"].split()),
            "reason_over_word_limit": int(len(classification["classification_reason"].split()) > 45),
            "secondary_objects_recovered": int(unit_id in recovered_secondary_units),
            "coding_rule_deviation": int(
                classification["extraction_quality"] in {"unclear_fragment", "not_checkable"} and (
                    classification["primary_object"] != "unclear"
                    or classification["secondary_objects"]
                    or classification["claim_focus"] != "unclear"
                    or classification["product_maturity"] != "not_applicable"
                )
            ),
            **provenance_by_unit[unit_id],
            "source_csv_sha256": manifest["source_sha256"],
            "needs_human_review": 1,
            "human_primary_object": "",
            "human_secondary_objects": "",
            "human_claim_focus": "",
            "human_product_maturity": "",
            "human_extraction_quality": "",
            "human_note": "",
        }
        unit_rows.append(row)
        unit_by_id[unit_id] = row

    broad_rows = read_source(ROOT / manifest["source"])
    claim_source: dict[str, tuple[dict[str, str], dict[str, Any]]] = {}
    for source_row in broad_rows:
        for claim in json.loads(source_row["claims_json"]):
            claim_source[claim["claim_id"]] = (source_row, claim)
    instance_rows: list[dict[str, Any]] = []
    for link in mapping:
        source_row, claim = claim_source[link["claim_instance_id"]]
        unit = unit_by_id[link["statement_unit_id"]]
        instance_rows.append({
            "claim_instance_id": link["claim_instance_id"],
            "statement_unit_id": link["statement_unit_id"],
            "is_representative": link["is_representative"],
            "statement_unit_instance_count": unit["claim_instance_count"],
            "representative_claim_instance_id": unit["representative_claim_instance_id"],
            "source_span_status": link["span_status"],
            "show": source_row["show"], "episode_id": source_row["episode_id"],
            "episode_title": source_row["episode_title"], "guest": source_row["guest"],
            "published_date": source_row["published_date"], "snippet_id": source_row["snippet_id"],
            "window_id": source_row["window_id"], "word_start_index": source_row["word_start_index"],
            "word_end_index_exclusive": source_row["word_end_index_exclusive"],
            "start_ms": source_row["start_ms"], "end_ms": source_row["end_ms"],
            "health_related": source_row["health_related"], "science_related": source_row["science_related"],
            "exact_claim_text": claim["exact_claim_text"], "model_claim_text": claim["model_claim_text"],
            "existing_claim_domain": claim["claim_domain"], "existing_scientific_position": claim["scientific_position"],
            "existing_exaggeration": claim["exaggeration"], "existing_stance": claim["stance"],
            "existing_broad_status": claim["broad_status"], "existing_advanced_status": claim["advanced_status"],
            "existing_reason": claim["reason"], "quote_match_method": claim["quote_match_method"],
            "primary_object": unit["primary_object"], "secondary_objects": unit["secondary_objects"],
            "claim_focus": unit["claim_focus"], "product_maturity": unit["product_maturity"],
            "extraction_quality": unit["extraction_quality"],
            "classification_reason": unit["classification_reason"],
            "response_id": unit["response_id"], "response_model": unit["response_model"],
            "source_csv_sha256": manifest["source_sha256"], "snippet_text": source_row["snippet_text"],
            "needs_human_review": 1,
            "human_primary_object": "", "human_secondary_objects": "",
            "human_claim_focus": "", "human_product_maturity": "",
            "human_extraction_quality": "", "human_note": "",
        })
    if len(instance_rows) != manifest["claim_instances"] or len(unit_rows) != manifest["statement_units"]:
        raise ValueError("Output row counts do not match the frozen manifest")

    mapping_rows = [
        {
            **link,
            "source_csv_sha256": manifest["source_sha256"],
        }
        for link in mapping
    ]
    BASE["atomic_write"](run / "statement_units.csv", csv_text(unit_rows, list(unit_rows[0])))
    BASE["atomic_write"](run / "statement_instances.csv", csv_text(instance_rows, list(instance_rows[0])))
    BASE["atomic_write"](run / "statement_unit_mapping.csv", csv_text(mapping_rows, list(mapping_rows[0])))
    summaries = {
        "primary_object_summary.csv": summary_rows(unit_rows, instance_rows, "primary_object", list(config["object_categories"])),
        "claim_focus_summary.csv": summary_rows(unit_rows, instance_rows, "claim_focus", list(config["claim_focuses"])),
        "product_maturity_summary.csv": summary_rows(unit_rows, instance_rows, "product_maturity", list(config["product_maturity"])),
        "extraction_quality_summary.csv": summary_rows(unit_rows, instance_rows, "extraction_quality", list(config["extraction_quality"])),
    }
    for filename, rows in summaries.items():
        BASE["atomic_write"](run / filename, csv_text(rows, list(rows[0])))
    show_rows = []
    for (show, category), group in sorted(defaultdict(list, {
        key: [unit for unit in unit_rows if (unit["show"], unit["primary_object"]) == key]
        for key in {(unit["show"], unit["primary_object"]) for unit in unit_rows}
    }).items()):
        denominator = sum(unit["show"] == show for unit in unit_rows)
        show_rows.append({
            "show": show, "primary_object": category, "unique_statement_units": len(group),
            "show_statement_units": denominator, "percent_within_show": round(100 * len(group) / denominator, 6),
        })
    BASE["atomic_write"](run / "show_object_summary.csv", csv_text(show_rows, list(show_rows[0])))
    write(run / "collection_summary.json", {
        "run_id": manifest["run_id"], "prompt_version": config["prompt_version"],
        "claim_instances": len(instance_rows), "statement_units": len(unit_rows),
        "duplicate_instances_linked": len(instance_rows) - len(unit_rows),
        "unresolved_statement_units": sum(row["source_span_status"] != "aligned" for row in unit_rows),
        "requests_completed": len(results), "usage": usage,
        "repair_requests": len(repair_ids),
        "split_repair_requests": split_request_count,
        "recovered_statement_ids": recovered_id_count,
        "recovered_snippet_ids": recovered_snippet_id_count,
        "recovered_secondary_object_lists": len(recovered_secondary_units),
        "primary_objects": dict(Counter(row["primary_object"] for row in unit_rows)),
        "claim_focuses": dict(Counter(row["claim_focus"] for row in unit_rows)),
        "product_maturity": dict(Counter(row["product_maturity"] for row in unit_rows)),
        "extraction_quality": dict(Counter(row["extraction_quality"] for row in unit_rows)),
        "long_explanations": sum(row["reason_over_word_limit"] for row in unit_rows),
        "coding_rule_deviations": sum(row["coding_rule_deviation"] for row in unit_rows),
        "source_csv_sha256": manifest["source_sha256"],
        "collector_sha256": digest(Path(__file__).read_bytes()),
        "batch_output_sha256": digest(output_path.read_bytes()),
        "status": "provisional_model_assisted_not_human_validated",
        "collected_at": BASE["utc_now"](),
    })
    print(f"Collected {len(unit_rows):,} statement units and {len(instance_rows):,} claim instances: {run}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "submit", "status", "repair", "repair-status", "repair-split", "repair-split-status", "collect"))
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--run-id")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        command = args.command.replace("-", "_")
        globals()[command](args)
    except (ValueError, KeyError, OSError, json.JSONDecodeError, BASE["PassageClassificationError"]) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
