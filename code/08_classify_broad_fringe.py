#!/usr/bin/env python3
"""Prepare, submit and collect a separate broad-fringe window classification.

Uses frozen inputs; never edits the earlier Stage-05 classifications. All local
preparation and collection validation works without third-party Python packages.
Network commands require the OpenAI SDK and OPENAI_API_KEY in the environment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = runpy.run_path(str(ROOT / "code/05_classify_passage_content_openai_batch.py"))
DEFAULT_INPUT = ROOT / "data/derived/classifications/openai_passage_content/pilot_20_2026-09-12/pilot_20_window_claim_classification.csv"
CONFIG = ROOT / "config/broad_fringe_classification.json"
RUN_ROOT = ROOT / "data/derived/classifications/broad_fringe"
POSITIVE_POSITIONS = {"emerging_non_mainstream", "alternative_speculative", "contradicts_consensus"}
ADVANCED_STANCES = {"asserted", "tentative"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    BASE["write_json"](path, value)


def freeze(path, text):
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise ValueError(f"Refusing to overwrite frozen input: {path}")
    if not path.exists():
        BASE["atomic_write"](path, text)


def schema(config):
    fields = {
        "exact_claim_text": {"type": "string"},
        "claim_domain": {"type": "string", "enum": ["health", "science", "both"]},
        "scientific_position": {"type": "string", "enum": list(config["scientific_positions"])},
        "exaggeration": {"type": "string", "enum": list(config["exaggeration_labels"])},
        "stance": {"type": "string", "enum": list(config["stance_labels"])},
        "reason": {"type": "string"},
    }
    claim = {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    return {"type": "object", "properties": {
        "snippet_id": {"type": "string"}, "claims": {"type": "array", "items": claim},
    }, "required": ["snippet_id", "claims"], "additionalProperties": False}


def instructions(config):
    paragraphs = [
        "You are a helpful research assistant with knowledge of scientific reasoning, "
        "health research, and scientific consensus. Extract and provisionally classify "
        "the health/science claims in this podcast transcript window. Assess validity "
        "and scientific backing, preserving the distinction between non-mainstream "
        "ideas, exaggeration, and falsehood.",
    ]
    for key in ("scientific_positions", "exaggeration_labels", "stance_labels"):
        paragraphs.append(key + ":\n" + "\n".join(f"- {k}: {v}" for k, v in config[key].items()))
    paragraphs += ["Rules:\n" + "\n".join(f"- {r}" for r in config["rules"]),
                   "Reason format: " + config["reason_rule"],
                   "Return one structured window result, preserving snippet_id exactly."]
    return "\n\n".join(paragraphs)


def read_windows(input_path, sample_path=None):
    if not input_path.resolve().is_relative_to(ROOT / "data/derived"):
        raise ValueError("Input must be inside this project's data/derived")
    metadata = {}
    sources = []
    paths = ([sample_path] if sample_path else [
        ROOT / "config/jre_starter_sample.json",
        ROOT / "config/doac_starter_sample.json",
    ])
    for path in paths:
        path = path.resolve()
        if not path.is_relative_to(ROOT / "config"):
            raise ValueError("Sample configuration must be inside this project's config directory")
        sample = load(path)
        sources.append({"path": str(path.relative_to(ROOT)), "sha256": digest(path.read_bytes())})
        for e in sample["episodes"]:
            episode_id = e.get("episode_id") or e.get("youtube_id")
            key = (sample["show_id"], episode_id)
            if key in metadata:
                raise ValueError(f"Duplicate episode metadata: {key}")
            metadata[key] = e
    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    windows = []
    seen = set()
    intervals = {}
    for row in rows:
        key = (row["show"], row["episode_id"])
        episode = metadata[key]
        sid = row["snippet_id"]
        if sid in seen:
            raise ValueError("Duplicate snippet_id")
        seen.add(sid)
        start, end = int(row["word_start_index"]), int(row["word_end_index_exclusive"])
        window_id = int(row["window_id"])
        if end - start != 256 or start != window_id * 128:
            raise ValueError("Window size or stride differs from the approved unit")
        intervals.setdefault(key, []).append(window_id)
        labels = [int(row[n]) for n in ("screen_health_related", "screen_science_related")]
        if any(x not in (0, 1) for x in labels):
            raise ValueError("Invalid Stage-04 labels")
        windows.append({
            "snippet_id": sid, "show": row["show"], "episode_id": row["episode_id"],
            "episode_title": row["episode_title"], "guest": episode["guest_name"],
            "published_date": episode["published_date"], "window_id": window_id,
            "health_related": labels[0], "science_related": labels[1],
            "word_start_index": start, "word_end_index_exclusive": end,
            "start_ms": int(row["start_ms"]), "end_ms": int(row["end_ms"]),
            "snippet_text": row["snippet_text"],
            "speaker_segments": json.loads(row["speaker_segments_json"]),
            "stage04_response_id": row["stage04_response_id"],
            "stage04_response_model": row["stage04_response_model"],
        })
    if not windows:
        raise ValueError("Input contains no windows")
    if set(intervals) != set(metadata):
        raise ValueError("Input does not cover every episode in the two frozen pilot samples")
    for ids in intervals.values():
        if sorted(ids) != list(range(len(ids))) or len(ids) < 5:
            raise ValueError("Missing windows or episode shorter than five full windows")
    return sorted(windows, key=lambda r: (r["show"], r["episode_id"], r["window_id"])), sources


def prepare(args):
    config = load(CONFIG)
    sample_path = args.sample.resolve() if args.sample else None
    windows, sources = read_windows(args.input.resolve(), sample_path)
    prompt, output_schema = instructions(config), schema(config)
    requests = []
    for w in windows:
        if not (w["health_related"] or w["science_related"]):
            continue
        payload = {k: w[k] for k in ("snippet_id", "published_date", "speaker_segments")}
        payload["stage04_labels"] = {k: bool(w[k]) for k in ("health_related", "science_related")}
        requests.append({"custom_id": w["snippet_id"], "method": "POST", "url": "/v1/responses", "body": {
            "model": config["model"], "reasoning": {"effort": config["reasoning_effort"]},
            "max_output_tokens": config["max_output_tokens"], "store": False,
            "instructions": prompt, "input": canonical(payload),
            "text": {"format": {"type": "json_schema", "name": "broad_fringe_window",
                                   "schema": output_schema, "strict": True}},
        }})
    frozen = {
        "config.json": canonical(config) + "\n", "windows.json": canonical(windows) + "\n",
        "instructions.txt": prompt + "\n", "response_schema.json": canonical(output_schema) + "\n",
        "batch_input.jsonl": "".join(canonical(r) + "\n" for r in requests),
    }
    run_id = digest(canonical(frozen).encode())[:16]
    run = RUN_ROOT / run_id
    for name, content in frozen.items():
        freeze(run / name, content)
    if not (run / "manifest.json").exists():
        write(run / "manifest.json", {
            "run_id": run_id, "created_at": BASE["utc_now"](), "prompt_version": config["prompt_version"],
            "model": config["model"], "windows": len(windows), "requests": len(requests),
            "episodes": len({(w["show"], w["episode_id"]) for w in windows}),
            "source": str(args.input.resolve().relative_to(ROOT)), "source_sha256": digest(args.input.read_bytes()),
            "metadata_sources": sources, "script_sha256": digest(Path(__file__).read_bytes()),
            "files": {name: digest(content.encode()) for name, content in frozen.items()},
        })
    write(RUN_ROOT / "latest_prepared_run.json", {"run_id": run_id})
    print(f"Prepared {len(requests)} requests; retained {len(windows)} windows. Run: {run_id}")
    print(f"Prompt: {run / 'instructions.txt'}")
    print("Prepared locally; not submitted.")


def resolve(args):
    run_id = args.run_id or load(RUN_ROOT / "latest_prepared_run.json")["run_id"]
    if len(run_id) != 16 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("Invalid run ID")
    run = RUN_ROOT / run_id
    manifest = load(run / "manifest.json")
    for name, expected in manifest["files"].items():
        if digest((run / name).read_bytes()) != expected:
            raise ValueError(f"Frozen input changed: {name}")
    return run, manifest


def submit(args):
    run, manifest = resolve(args)
    if not args.yes:
        raise ValueError("submit --yes confirms the authorized upload and API charge")
    if (run / "batch_job.json").exists():
        print("Existing job:", load(run / "batch_job.json")["id"])
        return
    client, sdk = BASE["openai_client"]()
    upload = run / "upload.json"
    if not upload.exists():
        with (run / "batch_input.jsonl").open("rb") as handle:
            file = client.files.create(file=handle, purpose="batch")
        write(upload, {"file_id": file.id})
    batch = client.batches.create(input_file_id=load(upload)["file_id"], endpoint="/v1/responses",
                                  completion_window="24h", metadata={"run_id": manifest["run_id"]})
    write(run / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Submitted:", batch.id, "Status:", batch.status, "Requests:", manifest["requests"])


def retrieve(run):
    client, sdk = BASE["openai_client"]()
    batch = client.batches.retrieve(load(run / "batch_job.json")["id"])
    write(run / "batch_job.json", {**batch.model_dump(mode="json"), "sdk_version": sdk})
    print("Batch:", batch.id, "Status:", batch.status, "Counts:", batch.request_counts)
    return client, batch


def status(args):
    run, _ = resolve(args)
    retrieve(run)


def validate(value, sid, config):
    if not isinstance(value, dict) or set(value) != {"snippet_id", "claims"} or value["snippet_id"] != sid:
        raise ValueError(f"Invalid result or snippet ID: {sid}")
    if not isinstance(value["claims"], list):
        raise ValueError(f"Invalid claims array: {sid}")
    expected_keys = set(schema(config)["properties"]["claims"]["items"]["properties"])
    seen = set()
    for claim in value["claims"]:
        if not isinstance(claim, dict) or set(claim) != expected_keys:
            raise ValueError(f"Invalid claim fields: {sid}")
        for field, allowed in (
            ("scientific_position", config["scientific_positions"]),
            ("exaggeration", config["exaggeration_labels"]),
            ("stance", config["stance_labels"]), ("claim_domain", ("health", "science", "both")),
        ):
            if claim[field] not in allowed:
                raise ValueError(f"Invalid {field}: {sid}")
        quote, reason = claim["exact_claim_text"], claim["reason"]
        if not isinstance(quote, str) or not quote.strip() or quote in seen:
            raise ValueError(f"Empty or duplicate claim: {sid}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Invalid explanation: {sid}")
        seen.add(quote)


def broad_flag(claim):
    if claim["scientific_position"] in POSITIVE_POSITIONS or claim["exaggeration"] == "yes":
        return "fringe"
    if claim["scientific_position"] == "uncertain" or claim["exaggeration"] == "uncertain":
        return "uncertain"
    return "not_fringe"


def aggregate(flags):
    for status in ("fringe", "uncertain", "not_fringe"):
        if status in flags:
            return status
    return "not_assessable"


def make_rows(windows, results):
    output = []
    for w in windows:
        selected = bool(w["health_related"] or w["science_related"])
        if selected and w["snippet_id"] not in results:
            raise ValueError(f"Missing requested window: {w['snippet_id']}")
        result = results.get(w["snippet_id"], {})
        claims = []
        for i, c in enumerate(result.get("claims", [])):
            exact, method = BASE["align_claim_text"](c["exact_claim_text"], w["snippet_text"])
            raw_flag = broad_flag(c)
            flag = raw_flag if method != "unmatched" else "uncertain"
            advanced = flag
            if c["stance"] in {"reported", "rejected"}:
                advanced = "not_fringe"
            elif c["stance"] == "unclear" and flag != "not_fringe":
                advanced = "uncertain"
            claims.append({**c, "claim_id": f"{w['snippet_id']}-broad-{i + 1:04d}",
                           "model_claim_text": c["exact_claim_text"], "exact_claim_text": exact,
                           "quote_match_method": method, "model_broad_status": raw_flag,
                           "reason_word_count": len(c["reason"].split()),
                           "reason_over_word_limit": int(len(c["reason"].split()) > 80),
                           "broad_status": flag, "advanced_status": advanced})
        row = {k: v for k, v in w.items() if k != "speaker_segments"}
        row.update({"stage08_requested": int(selected), "claim_count": len(claims),
                    "broad_status": aggregate([c["broad_status"] for c in claims]) if selected else "not_screened",
                    "advanced_status": aggregate([c["advanced_status"] for c in claims]) if selected else "not_screened",
                    "unmatched_claim_count": sum(c["quote_match_method"] == "unmatched" for c in claims),
                    "long_explanation_count": sum(c["reason_over_word_limit"] for c in claims),
                    "claims_json": canonical(claims), "response_id": result.get("response_id", ""),
                    "response_model": result.get("response_model", ""),
                    "needs_human_review": 1, "human_decision": "", "evidence_sources": ""})
        output.append(row)
    return output


def collect(args):
    run, manifest = resolve(args)
    output_path = run / "batch_output.jsonl"
    if not output_path.exists():
        client, batch = retrieve(run)
        if batch.status not in BASE["TERMINAL_BATCH_STATUSES"]:
            raise ValueError(f"Batch still {batch.status}; collect once complete")
        BASE["download_batch_results"](client, batch, run)
    config, windows = load(run / "config.json"), load(run / "windows.json")
    expected = {w["snippet_id"] for w in windows if w["health_related"] or w["science_related"]}
    results, usage = {}, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for raw in BASE["parse_jsonl"](output_path.read_bytes(), "broad-fringe batch output"):
        sid = raw.get("custom_id")
        response = raw.get("response") or {}
        if sid not in expected or sid in results or raw.get("error") or response.get("status_code") != 200:
            raise ValueError(f"Unexpected, duplicate or failed result: {sid}")
        body = response.get("body") or {}
        if body.get("status") not in (None, "completed"):
            raise ValueError(f"Incomplete response: {sid}")
        value = json.loads(BASE["extract_output_text"](body))
        validate(value, sid, config)
        results[sid] = {**value, "response_id": body.get("id", ""), "response_model": body.get("model", "")}
        for field in usage:
            usage[field] += (body.get("usage") or {}).get(field, 0) or 0
    if set(results) != expected:
        raise ValueError(f"Missing {len(expected - set(results))} results; refusing partial prevalence estimates")
    rows = make_rows(windows, results)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    BASE["atomic_write"](run / "broad_window_classification.csv", buffer.getvalue())
    write(run / "collection_summary.json", {
        "run_id": manifest["run_id"], "prompt_version": config["prompt_version"],
        "windows": len(rows), "requests_completed": len(results), "usage": usage,
        "claims_with_overlap": sum(r["claim_count"] for r in rows),
        "broad_present_windows": sum(r["broad_status"] == "fringe" for r in rows),
        "broad_advanced_windows": sum(r["advanced_status"] == "fringe" for r in rows),
        "unmatched_claims": sum(r["unmatched_claim_count"] for r in rows),
        "long_explanations": sum(r["long_explanation_count"] for r in rows),
        "collector_sha256": digest(Path(__file__).read_bytes()),
        "batch_output_sha256": digest(output_path.read_bytes()),
        "status": "provisional_model_assisted_not_human_validated",
        "collected_at": BASE["utc_now"](),
    })
    print("Collected complete classification:", run / "broad_window_classification.csv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "submit", "status", "collect"))
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--sample", type=Path, help="Frozen sample metadata for this input")
    parser.add_argument("--run-id")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        globals()[args.command](args)
    except (ValueError, KeyError, OSError, BASE["PassageClassificationError"]) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
