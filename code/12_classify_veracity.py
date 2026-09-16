#!/usr/bin/env python3
"""Augment Stage-10 statements with provisional health veracity and danger labels.

Reuses the existing OpenAI client, Batch response parser, immutable file writer,
CSV serializer and statement identifiers. All prior CSV columns are preserved.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import runpy
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HEALTH = runpy.run_path(str(ROOT / "code/10_classify_health_objects.py"))
BASE = HEALTH["BASE"]
canonical, digest, load = (HEALTH[name] for name in ("canonical", "digest", "load"))
write, csv_text = (HEALTH[name] for name in ("write", "csv_text"))
CONFIG = ROOT / "config/veracity_classification.json"
RUN_ROOT = ROOT / "data/derived/classifications/veracity"
DEFAULT_INPUT = ROOT / "data/derived/classifications/health_objects/e5112711aca03600"
ENUM_FIELDS = {"health_scope": "health_scope", "veracity_label": "veracity", "danger_label": "danger"}
TEXT_FIELDS = ("veracity_reason", "danger_reason", "evidence_review_needed")


def freeze(path: Path, content: str) -> None:
    """Compare bytes so CSV CRLF record separators survive repeat collection."""
    encoded = content.encode("utf-8")
    if path.exists() and path.read_bytes() != encoded:
        raise ValueError(f"Refusing to overwrite frozen file: {path}")
    if not path.exists():
        BASE["atomic_write"](path, encoded)


def read_csv(content: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(content))
    fields = reader.fieldnames or []
    if not fields or len(fields) != len(set(fields)):
        raise ValueError("Missing or duplicate CSV headers")
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("Empty or malformed input CSV")
    return rows


def validate_inputs(units: list[dict[str, str]], instances: list[dict[str, str]]) -> None:
    required = {
        "statement_unit_id", "exact_claim_text", "representative_snippet_id",
        "representative_snippet_text", "representative_claim_instance_id",
        "claim_instance_count", "claim_instance_ids", "source_span_status",
        "show", "episode_id", "published_date",
    }
    if not units or not instances or not required.issubset(units[0]):
        raise ValueError("Expected Stage-10 statement units and instances")
    if not {"statement_unit_id", "claim_instance_id", "is_representative", "episode_id"}.issubset(instances[0]):
        raise ValueError("Missing instance mapping fields")
    by_unit = {row["statement_unit_id"]: row for row in units}
    if len(by_unit) != len(units) or len({row["claim_instance_id"] for row in instances}) != len(instances):
        raise ValueError("Duplicate statement or claim instance identifiers")
    members: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in instances:
        if row["statement_unit_id"] not in by_unit:
            raise ValueError("An instance refers to an unknown statement unit")
        members[row["statement_unit_id"]].append(row)
    for unit_id, unit in by_unit.items():
        group = members[unit_id]
        if (len(group) != int(unit["claim_instance_count"])
                or {row["claim_instance_id"] for row in group} != set(unit["claim_instance_ids"].split(" | "))
                or [row["claim_instance_id"] for row in group if row["is_representative"] == "1"]
                != [unit["representative_claim_instance_id"]]
                or any(row["episode_id"] != unit["episode_id"] for row in group)):
            raise ValueError(f"Invalid statement-instance mapping: {unit_id}")
        if len(unit["representative_snippet_text"].split()) != 256:
            raise ValueError(f"Expected a complete 256-word window: {unit_id}")


def schema(config: dict[str, Any]) -> dict[str, Any]:
    fields = {"statement_unit_id": {"type": "string"}}
    fields.update({field: {"type": "string", "enum": list(config[key])} for field, key in ENUM_FIELDS.items()})
    fields.update({field: {"type": "string"} for field in TEXT_FIELDS})
    item = {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    return {"type": "object", "properties": {"classifications": {"type": "array", "items": item}},
            "required": ["classifications"], "additionalProperties": False}


def instructions(config: dict[str, Any]) -> str:
    sections = ["You assist an observational research project with provisional health-claim veracity coding.",
                "Assessment frame: " + config["assessment_frame"]]
    for name in ("health_scope", "veracity", "danger"):
        sections.append(name + ":\n" + "\n".join(f"- {key}: {value}" for key, value in config[name].items()))
    sections.append("Rules:\n" + "\n".join(f"- {rule}" for rule in config["rules"]))
    return "\n\n".join(sections)


def validate_result(value: Any, expected: dict[str, dict[str, str]], config: dict[str, Any]) -> None:
    if not isinstance(value, dict) or set(value) != {"classifications"} or not isinstance(value["classifications"], list):
        raise ValueError("Invalid response structure")
    fields = set(schema(config)["properties"]["classifications"]["items"]["properties"])
    seen = set()
    for item in value["classifications"]:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("Invalid classification fields")
        unit_id = item["statement_unit_id"]
        if not isinstance(unit_id, str) or unit_id not in expected or unit_id in seen:
            raise ValueError("Unexpected or duplicate statement identifier")
        seen.add(unit_id)
        for field, key in ENUM_FIELDS.items():
            if not isinstance(item[field], str) or item[field] not in config[key]:
                raise ValueError(f"Invalid {field}: {unit_id}")
        for field in TEXT_FIELDS:
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(f"Missing {field}: {unit_id}")
        scope, veracity, danger = (item[name] for name in ENUM_FIELDS)
        if scope == "non_health":
            valid = veracity == danger == "not_applicable"
        elif scope == "uncertain":
            valid = veracity in {"uncertain", "not_assessable"} and danger in {"uncertain", "not_assessable"}
        else:
            valid = veracity != "not_applicable" and danger != "not_applicable"
        valid = valid and ((veracity == "not_assessable") == (danger == "not_assessable"))
        if expected[unit_id]["source_span_status"] == "unmatched":
            valid = valid and veracity in {"not_assessable", "not_applicable"}
        if not valid:
            raise ValueError(f"Inconsistent scope/veracity/danger or unverified quotation: {unit_id}")
    if seen != set(expected):
        raise ValueError("Missing statement classifications")


def make_requests(units: list[dict[str, str]], config: dict[str, Any], assessment_date: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for unit in units:
        grouped[unit["representative_snippet_id"]].append(unit)
    requests = []
    size = config["statements_per_request"]
    if not isinstance(size, int) or size < 1:
        raise ValueError("statements_per_request must be a positive integer")
    for snippet_id, group in sorted(grouped.items()):
        group.sort(key=lambda item: item["statement_unit_id"])
        for offset in range(0, len(group), size):
            selected = group[offset:offset + size]
            if len({row["representative_snippet_text"] for row in selected}) != 1:
                raise ValueError("Inconsistent text for one snippet identifier")
            payload = {
                "assessment_date": assessment_date, "published_date": selected[0]["published_date"],
                "snippet_id": snippet_id, "transcript_window": selected[0]["representative_snippet_text"],
                "statements": [{key: row[key] for key in ("statement_unit_id", "exact_claim_text", "source_span_status")}
                               for row in selected],
            }
            requests.append({
                "custom_id": "veracity-" + digest(canonical(payload).encode())[:24],
                "method": "POST", "url": "/v1/responses",
                "body": {
                    "model": config["model"], "reasoning": {"effort": config["reasoning_effort"]},
                    "max_output_tokens": config["max_output_tokens"], "store": False,
                    "instructions": instructions(config), "input": canonical(payload),
                    "text": {"format": {"type": "json_schema", "name": "health_claim_veracity",
                                         "schema": schema(config), "strict": True}},
                },
            })
    if len({row["custom_id"] for row in requests}) != len(requests):
        raise ValueError("Duplicate request identifiers")
    return requests


def select_pilot(units: list[dict[str, str]], instances: list[dict[str, str]], size: int
                 ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Deterministic technical smoke test, balanced across shows; not an analytic sample."""
    if size < 1:
        raise ValueError("Pilot size must be positive")
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in units:
        if row.get("existing_claim_domain") in {"health", "both"}:
            groups[row["show"]].append(row)
    for group in groups.values():
        group.sort(key=lambda row: digest(("veracity-pilot-v1:" + row["statement_unit_id"]).encode()))
    selected = []
    while len(selected) < size and any(groups.values()):
        for show in sorted(groups):
            if groups[show] and len(selected) < size:
                selected.append(groups[show].pop(0))
    if len(selected) != size:
        raise ValueError("Pilot size exceeds the available health/both statement units")
    ids = {row["statement_unit_id"] for row in selected}
    return selected, [row for row in instances if row["statement_unit_id"] in ids]


def prepare(args: argparse.Namespace) -> None:
    source = args.input.resolve()
    if not source.is_relative_to(ROOT / "data/derived"):
        raise ValueError("Input must be inside this project's data/derived directory")
    contents = {}
    for name in ("statement_units.csv", "statement_instances.csv"):
        path = (source / name).resolve()
        if not path.is_relative_to(ROOT / "data/derived"):
            raise ValueError("Input symlink leaves this project's derived data directory")
        contents["source_" + name] = path.read_bytes().decode("utf-8")
    units, instances = [read_csv(contents["source_" + name]) for name in ("statement_units.csv", "statement_instances.csv")]
    validate_inputs(units, instances)
    pilot_size = getattr(args, "pilot_size", None)
    if pilot_size is not None:
        parent_hashes = {name: digest(content.encode()) for name, content in contents.items()}
        units, instances = select_pilot(units, instances, pilot_size)
        validate_inputs(units, instances)
        contents["source_statement_units.csv"] = csv_text(units, list(units[0]))
        contents["source_statement_instances.csv"] = csv_text(instances, list(instances[0]))
        contents["pilot_selection.json"] = canonical({
            "purpose": "technical_smoke_test_not_representative_validation",
            "rule": "health/both domain; round-robin shows; SHA256 veracity-pilot-v1:statement_unit_id order",
            "requested_size": pilot_size, "parent_source_sha256": parent_hashes,
            "selected_unit_ids": [row["statement_unit_id"] for row in units],
        }) + "\n"
    config = load(CONFIG)
    requests = make_requests(units, config, args.assessment_date)
    contents.update({"config.json": canonical(config) + "\n", "instructions.txt": instructions(config) + "\n",
                     "response_schema.json": canonical(schema(config)) + "\n",
                     "batch_input.jsonl": "".join(canonical(row) + "\n" for row in requests)})
    if len(requests) > 50000 or len(contents["batch_input.jsonl"].encode()) > 200_000_000:
        raise ValueError("Exceeds one Batch's limits; partition the upstream corpus explicitly")
    run_id = digest(canonical(contents).encode())[:16]
    run = RUN_ROOT / run_id
    for name, content in contents.items():
        freeze(run / name, content)
    if not (run / "manifest.json").exists():
        write(run / "manifest.json", {
            "run_id": run_id, "created_at": BASE["utc_now"](), "assessment_date": args.assessment_date,
            "source": str(source.relative_to(ROOT)), "statement_units": len(units),
            "claim_instances": len(instances), "requests": len(requests),
            "model": config["model"], "prompt_version": config["prompt_version"],
            "evidence_mode": config["evidence_mode"], "protocol_status": config["protocol_status"],
            "files": {name: digest(content.encode()) for name, content in contents.items()},
            "code_sha256": {name: digest((ROOT / "code" / name).read_bytes()) for name in
                            ("12_classify_veracity.py", "10_classify_health_objects.py", "05_classify_passage_content_openai_batch.py")},
        })
    write(RUN_ROOT / "latest_prepared_run.json", {"run_id": run_id})
    print(f"Prepared {len(units):,} units / {len(instances):,} instances / {len(requests):,} requests: {run_id}")
    print("Prepared locally; not submitted. Labels will be provisional model-knowledge assessments.")


def resolve(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    run_id = args.run_id or load(RUN_ROOT / "latest_prepared_run.json")["run_id"]
    if len(run_id) != 16 or any(char not in "0123456789abcdef" for char in run_id):
        raise ValueError("Invalid run identifier")
    run = RUN_ROOT / run_id
    manifest = load(run / "manifest.json")
    for name, expected in manifest["files"].items():
        if digest((run / name).read_bytes()) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    return run, manifest


def submit_job(directory: Path, run_id: str, yes: bool) -> None:
    if not yes:
        raise ValueError("--yes confirms the requested OpenAI upload and API charge")
    if (directory / "batch_job.json").exists():
        print("Existing job:", load(directory / "batch_job.json")["id"])
        return
    client, sdk = BASE["openai_client"]()
    if not (directory / "upload.json").exists():
        with (directory / "batch_input.jsonl").open("rb") as handle:
            uploaded = client.files.create(file=handle, purpose="batch")
        write(directory / "upload.json", {"file_id": uploaded.id})
    batch = client.batches.create(input_file_id=load(directory / "upload.json")["file_id"],
                                  endpoint="/v1/responses", completion_window="24h", metadata={"run_id": run_id})
    write(directory / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Submitted:", batch.id, "Status:", batch.status)


def submit(args: argparse.Namespace) -> None:
    run, manifest = resolve(args)
    submit_job(run, manifest["run_id"], args.yes)


def estimate(args: argparse.Namespace) -> None:
    run, manifest = resolve(args)
    pricing = load(ROOT / "config/openai_veracity_pricing_2026-09-16.json")
    requests = read_requests(run / "batch_input.jsonl")
    if any(row["body"]["model"] != pricing["model"] for row in requests):
        raise ValueError("Pricing model does not match prepared requests")
    input_bytes = sum(len(json.dumps({key: row["body"][key] for key in ("instructions", "input", "text")},
                                    ensure_ascii=False).encode()) for row in requests)
    output_cap = sum(row["body"]["max_output_tokens"] for row in requests)
    input_rate, output_rate = pricing["input_per_million"] / 1e6, pricing["output_per_million"] / 1e6
    report = {"run_id": manifest["run_id"], "pricing": pricing, "requests": len(requests),
              "input_serialized_bytes": input_bytes, "approximate_input_tokens_bytes_divided_by_four": input_bytes / 4,
              "output_token_cap": output_cap,
              "scenario_usd_1000_output_tokens_per_request": input_bytes / 4 * input_rate + len(requests) * 1000 * output_rate,
              "scenario_usd_3000_output_tokens_per_request": input_bytes / 4 * input_rate + len(requests) * 3000 * output_rate,
              "conservative_planning_usd_one_input_token_per_byte_and_output_cap": input_bytes * input_rate + output_cap * output_rate,
              "limitations": "Planning scenarios, not measured token counts or a billing guarantee; excludes retries, taxes and regional uplift."}
    summary_path = run / "collection_summary.json"
    if summary_path.exists():
        usage = load(summary_path)["usage"]
        report["measured_usage"] = usage
        report["measured_usage_usd_at_uncached_rates"] = usage["input_tokens"] * input_rate + usage["output_tokens"] * output_rate
    write(run / "cost_estimate.json", report)
    print(json.dumps(report, indent=2))


def attempts(run: Path) -> list[Path]:
    return [run] + sorted(path for path in run.glob("retry_[0-9][0-9][0-9]") if path.is_dir())


def download(directory: Path) -> None:
    client, sdk = BASE["openai_client"]()
    batch = client.batches.retrieve(load(directory / "batch_job.json")["id"])
    write(directory / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Batch:", batch.id, "Status:", batch.status, "Counts:", batch.request_counts)
    if batch.status not in BASE["TERMINAL_BATCH_STATUSES"]:
        raise ValueError("Batch still running; collect after it completes")
    for field, name in (("error_file_id", "batch_errors.jsonl"), ("output_file_id", "batch_output.jsonl")):
        file_id = getattr(batch, field, None)
        if file_id:
            freeze(directory / name, BASE["api_file_bytes"](client, file_id).decode("utf-8"))
    write(directory / "download_complete.json", {"status": batch.status, "downloaded_at": BASE["utc_now"]()})


def status(args: argparse.Namespace) -> None:
    run, _ = resolve(args)
    client, sdk = BASE["openai_client"]()
    for directory in attempts(run):
        if not (directory / "batch_job.json").exists():
            print(directory.name, "prepared, not submitted")
            continue
        batch = client.batches.retrieve(load(directory / "batch_job.json")["id"])
        write(directory / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
        print(directory.name, batch.id, batch.status, batch.request_counts)


def read_requests(path: Path) -> list[dict[str, Any]]:
    return BASE["parse_jsonl"](path.read_bytes(), str(path))


def results(run: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, int]]:
    config = load(run / "config.json")
    original = {row["custom_id"]: row for row in read_requests(run / "batch_input.jsonl")}
    successes: dict[str, dict[str, Any]] = {}
    failures = dict.fromkeys(original, "No successful response")
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for directory in attempts(run):
        if not (directory / "download_complete.json").exists():
            download(directory)
        input_path = directory / "batch_input.jsonl"
        if directory != run and digest(input_path.read_bytes()) != load(directory / "retry_manifest.json")["input_sha256"]:
            raise ValueError("Frozen retry input changed")
        expected_requests = {row["custom_id"]: row for row in read_requests(input_path)}
        if not set(expected_requests).issubset(original):
            raise ValueError("Retry contains unknown requests")
        path = directory / "batch_output.jsonl"
        seen = set()
        for raw in read_requests(path) if path.exists() else []:
            request_id = raw.get("custom_id")
            if request_id not in expected_requests or request_id in seen:
                raise ValueError("Unknown or duplicate Batch result identifier")
            seen.add(request_id)
            response = raw.get("response") or {}
            body = response.get("body") or {}
            for key in usage:
                usage[key] += int((body.get("usage") or {}).get(key) or 0)
            try:
                if raw.get("error") or response.get("status_code") != 200 or body.get("status") != "completed":
                    raise ValueError("Failed or incomplete provider response")
                value = json.loads(BASE["extract_output_text"](body))
                payload = json.loads(original[request_id]["body"]["input"])
                expected = {row["statement_unit_id"]: row for row in payload["statements"]}
                validate_result(value, expected, config)
            except (ValueError, TypeError, KeyError, BASE["PassageClassificationError"]) as exc:
                if request_id not in successes:
                    failures[request_id] = str(exc)
                continue
            successes[request_id] = {**value, "veracity_response_id": body.get("id", ""),
                                     "veracity_response_model": body.get("model", ""),
                                     "veracity_batch_id": load(directory / "batch_job.json")["id"]}
            failures.pop(request_id, None)
    write(run / "pending_requests.json", failures)
    return successes, failures, usage


def repair(args: argparse.Namespace) -> None:
    run, manifest = resolve(args)
    # Resume a locally prepared retry before trying to download its nonexistent job.
    for directory in attempts(run)[1:]:
        if not (directory / "batch_job.json").exists():
            if digest((directory / "batch_input.jsonl").read_bytes()) != load(directory / "retry_manifest.json")["input_sha256"]:
                raise ValueError("Frozen retry input changed")
            submit_job(directory, manifest["run_id"], args.yes)
            return
    _, failures, _ = results(run)
    if not failures:
        print("No requests need retry.")
        return
    directory = run / f"retry_{len(attempts(run)):03d}"
    selected = [row for row in read_requests(run / "batch_input.jsonl") if row["custom_id"] in failures]
    for row in selected:
        row["body"]["max_output_tokens"] = max(row["body"]["max_output_tokens"], 14000)
    content = "".join(canonical(row) + "\n" for row in selected)
    freeze(directory / "batch_input.jsonl", content)
    write(directory / "retry_manifest.json", {"requests": len(selected), "input_sha256": digest(content.encode()),
                                             "reasons": failures, "created_at": BASE["utc_now"]()})
    print("Retry requests:", len(selected))
    submit_job(directory, manifest["run_id"], args.yes)


def augment(rows: list[dict[str, str]], labels: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    augmented = []
    for row in rows:
        additions = labels[row["statement_unit_id"]]
        if set(row) & set(additions):
            raise ValueError("New fields would overwrite existing columns")
        augmented.append({**row, **additions})
    return augmented


def collect(args: argparse.Namespace) -> None:
    run, manifest = resolve(args)
    successful, failures, usage = results(run)
    if failures:
        raise ValueError(f"{len(failures)} requests remain unresolved; inspect pending_requests.json and use repair --yes. No final CSV written.")
    config = load(run / "config.json")
    labels = {}
    for result in successful.values():
        for item in result["classifications"]:
            unit_id = item["statement_unit_id"]
            if unit_id in labels:
                raise ValueError("Duplicate statement across successful requests")
            labels[unit_id] = {
                **{("veracity_health_scope" if key == "health_scope" else key): value
                   for key, value in item.items() if key != "statement_unit_id"},
                **{key: value for key, value in result.items() if key.startswith("veracity_")},
                "veracity_run_id": manifest["run_id"], "veracity_prompt_version": config["prompt_version"],
                "veracity_evidence_mode": config["evidence_mode"],
                "veracity_assessment_date": manifest["assessment_date"],
                "veracity_source_units_sha256": manifest["files"]["source_statement_units.csv"],
                "veracity_source_instances_sha256": manifest["files"]["source_statement_instances.csv"],
                "veracity_status": "provisional_not_human_validated", "veracity_needs_human_review": 1,
                "human_veracity_label": "", "human_danger_label": "", "human_veracity_evidence_urls": "",
                "human_veracity_evidence_access_dates": "", "human_veracity_note": "",
            }
    units, instances = [read_csv((run / name).read_bytes().decode("utf-8")) for name in
                        ("source_statement_units.csv", "source_statement_instances.csv")]
    validate_inputs(units, instances)
    if set(labels) != {row["statement_unit_id"] for row in units}:
        raise ValueError("Not every statement received one classification")
    unit_rows, instance_rows = augment(units, labels), augment(instances, labels)
    summary = []
    health_units = [row for row in unit_rows if row["veracity_health_scope"] == "health"]
    health_instances = [row for row in instance_rows if row["veracity_health_scope"] == "health"]
    for field, categories in (("veracity_label", config["veracity"]), ("danger_label", config["danger"])):
        for category in categories:
            n_units = sum(row[field] == category for row in health_units)
            n_instances = sum(row[field] == category for row in health_instances)
            summary.append({"dimension": field, "category": category,
                            "all_unique_units": sum(row[field] == category for row in unit_rows),
                            "health_unique_units": n_units, "health_unique_denominator": len(health_units),
                            "health_unique_percent": round(100 * n_units / len(health_units), 6) if health_units else "",
                            "health_claim_instances": n_instances, "health_instance_denominator": len(health_instances)})
    outputs = {"statement_units.csv": csv_text(unit_rows, list(unit_rows[0])),
               "statement_instances.csv": csv_text(instance_rows, list(instance_rows[0])),
               "veracity_summary.csv": csv_text(summary, list(summary[0]))}
    # Preflight all outputs before writing; never overwrite a researcher's reviews.
    for name, content in outputs.items():
        if (run / name).exists() and (run / name).read_bytes() != content.encode("utf-8"):
            raise ValueError(f"Refusing to overwrite changed collected output: {name}")
    for name, content in outputs.items():
        freeze(run / name, content)
    write(run / "collection_summary.json", {
        "run_id": manifest["run_id"], "collected_at": BASE["utc_now"](),
        "statement_units": len(unit_rows), "claim_instances": len(instance_rows),
        "requests_completed": len(successful), "attempts": len(attempts(run)), "usage": usage,
        "health_scope": dict(Counter(row["veracity_health_scope"] for row in unit_rows)),
        "veracity": dict(Counter(row["veracity_label"] for row in unit_rows)),
        "danger": dict(Counter(row["danger_label"] for row in unit_rows)),
        "status": "provisional_model_knowledge_only_not_human_validated",
        "all_prior_columns_preserved": True, "collector_sha256": digest(Path(__file__).read_bytes()),
        "provider_output_sha256": {str(path.relative_to(run)): digest(path.read_bytes())
                                   for directory in attempts(run) for path in directory.glob("batch_*.jsonl")
                                   if path.name != "batch_input.jsonl"},
        "output_sha256": {name: digest(content.encode()) for name, content in outputs.items()},
    })
    print(f"Collected {len(unit_rows):,} units / {len(instance_rows):,} instances: {run}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "estimate", "submit", "status", "collect", "repair"))
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Stage-10 output directory")
    parser.add_argument("--run-id")
    parser.add_argument("--pilot-size", type=int, help="Prepare only this many health/both units for a technical pilot")
    parser.add_argument("--assessment-date", default=BASE["utc_now"]()[:10])
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        from datetime import date
        date.fromisoformat(args.assessment_date)
        globals()[args.command](args)
    except (ValueError, KeyError, OSError, BASE["PassageClassificationError"]) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
