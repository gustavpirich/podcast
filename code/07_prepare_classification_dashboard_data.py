#!/usr/bin/env python3
"""Prepare a compact, browser-readable dataset for the local dashboard."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    PROJECT_ROOT / "data" / "derived" / "classifications"
    / "broad_fringe" / "5a165612d6459da0"
    / "broad_window_classification.csv"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "dashboard" / "public" / "data" / "classifications.json"
DEFAULT_STATEMENTS = (
    PROJECT_ROOT / "data" / "derived" / "classifications" / "health_objects"
    / "e5112711aca03600" / "statement_instances.csv"
)
STATUSES = ("fringe", "uncertain", "not_fringe", "not_assessable", "not_screened")


def as_bool(value: str) -> bool:
    return value == "1"


def as_int(value: str) -> int:
    return int(value or 0)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_claim(claim: dict[str, object], statement: dict[str, str] | None = None) -> dict[str, object]:
    if "broad_status" in claim:
        result = {
            "id": claim["claim_id"],
            "text": claim["exact_claim_text"] or claim["model_claim_text"],
            "modelText": claim["model_claim_text"],
            "domain": claim["claim_domain"],
            "type": claim["stance"],
            "consensus": claim["scientific_position"],
            "exaggeration": claim["exaggeration"],
            "advancedStatus": claim["advanced_status"],
            "status": claim["broad_status"],
            "modelStatus": claim["model_broad_status"],
            "reason": claim["reason"],
            "matchMethod": claim["quote_match_method"],
            "textMatched": claim["quote_match_method"] != "unmatched",
            "codingConsistent": True,
        }
        if statement:
            result.update({
                "statementUnitId": statement["statement_unit_id"],
                "unitInstanceCount": as_int(statement["statement_unit_instance_count"]),
                "isRepresentative": as_bool(statement["is_representative"]),
                "primaryObject": statement["primary_object"],
                "secondaryObjects": statement["secondary_objects"].split(" | ") if statement["secondary_objects"] else [],
                "claimFocus": statement["claim_focus"],
                "productMaturity": statement["product_maturity"],
                "extractionQuality": statement["extraction_quality"],
                "objectReason": statement["classification_reason"],
                "objectResponseId": statement["response_id"],
            })
        return result
    return {
        "id": claim.get("claim_id"),
        "text": claim.get("exact_claim_text") or claim.get("model_claim_text") or "",
        "modelText": claim.get("model_claim_text") or "",
        "domain": claim.get("claim_domain"),
        "type": claim.get("claim_type"),
        "consensus": claim.get("consensus_relation"),
        "status": claim.get("fringe_status"),
        "modelStatus": claim.get("model_fringe_status"),
        "reason": claim.get("fringe_reason"),
        "matchMethod": claim.get("claim_text_match_method"),
        "textMatched": bool(claim.get("claim_text_matched")),
        "codingConsistent": bool(claim.get("consensus_fringe_consistent")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--statements", type=Path, default=DEFAULT_STATEMENTS)
    args = parser.parse_args()
    input_path = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    statement_path = args.statements if args.statements.is_absolute() else PROJECT_ROOT / args.statements
    with statement_path.open(newline="", encoding="utf-8") as handle:
        statement_rows = list(csv.DictReader(handle))
    statements = {row["claim_instance_id"]: row for row in statement_rows}
    if len(statement_rows) != 8504 or len(statements) != len(statement_rows):
        raise ValueError("Expected 8,504 unique classified claim instances")
    statement_source_hashes = {row["source_csv_sha256"] for row in statement_rows}

    records: list[dict[str, object]] = []
    episode_rows: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with input_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            broad = "broad_status" in row
            if broad:
                raw_claims = json.loads(row["claims_json"])
                row.update({
                    "fringe_status": row["broad_status"],
                    "stage05_requested": row["stage08_requested"],
                    "screen_health_related": row["health_related"],
                    "screen_science_related": row["science_related"],
                    "fringe_claim_count": str(sum(c["broad_status"] == "fringe" for c in raw_claims)),
                    "uncertain_claim_count": str(sum(c["broad_status"] == "uncertain" for c in raw_claims)),
                    "not_fringe_claim_count": str(sum(c["broad_status"] == "not_fringe" for c in raw_claims)),
                    "inconsistent_claim_coding_count": "0",
                    "non_exact_claim_text_count": str(sum(c["quote_match_method"] != "exact" for c in raw_claims)),
                    "unmatched_claim_text_count": row["unmatched_claim_count"],
                    "speakers": "",
                    "stage04_health_rationale": "",
                    "stage04_science_rationale": "",
                })
            claims = [compact_claim(item, statements.get(item["claim_id"])) for item in json.loads(row["claims_json"])]
            if any("primaryObject" not in claim for claim in claims):
                raise ValueError(f"Missing statement classification for {row['snippet_id']}")
            record = {
                "id": row["snippet_id"],
                "show": row["show"],
                "episodeId": row["episode_id"],
                "episodeTitle": row["episode_title"],
                "guest": row.get("guest", ""),
                "publishedDate": row.get("published_date", ""),
                "advancedStatus": row.get("advanced_status", row["fringe_status"]),
                "windowId": as_int(row["window_id"]),
                "wordStart": as_int(row["word_start_index"]),
                "wordEnd": as_int(row["word_end_index_exclusive"]),
                "startMs": as_int(row["start_ms"]),
                "endMs": as_int(row["end_ms"]),
                "speakers": row["speakers"].split(" | ") if row["speakers"] else [],
                "screenHealth": as_bool(row["screen_health_related"]),
                "screenScience": as_bool(row["screen_science_related"]),
                "health": as_bool(row["health_related"]),
                "science": as_bool(row["science_related"]),
                "stage05Requested": as_bool(row["stage05_requested"]),
                "status": row["fringe_status"],
                "claimCount": as_int(row["claim_count"]),
                "fringeClaimCount": as_int(row["fringe_claim_count"]),
                "uncertainClaimCount": as_int(row["uncertain_claim_count"]),
                "notFringeClaimCount": as_int(row["not_fringe_claim_count"]),
                "codingInconsistencies": as_int(row["inconsistent_claim_coding_count"]),
                "nonExactClaims": as_int(row["non_exact_claim_text_count"]),
                "unmatchedClaims": as_int(row["unmatched_claim_text_count"]),
                "stage04HealthRationale": row["stage04_health_rationale"],
                "stage04ScienceRationale": row["stage04_science_rationale"],
                "snippet": row["snippet_text"],
                "claims": claims,
                "needsHumanReview": as_bool(row["needs_human_review"]),
                "humanDecision": row["human_decision"],
            }
            records.append(record)
            episode_rows[(row["show"], row["episode_id"])].append(row)

    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Duplicate snippet identifiers")
    if any(r["claimCount"] != len(r["claims"]) for r in records):
        raise ValueError("Claim count mismatch")

    episodes: list[dict[str, object]] = []
    for (show, episode_id), rows in sorted(episode_rows.items()):
        status_counts = Counter(row["fringe_status"] for row in rows)
        episodes.append({
            "show": show,
            "episodeId": episode_id,
            "title": rows[0]["episode_title"],
            "guest": rows[0].get("guest", ""),
            "publishedDate": rows[0].get("published_date", ""),
            "windows": len(rows),
            "healthWindows": sum(as_bool(row["health_related"]) for row in rows),
            "scienceWindows": sum(as_bool(row["science_related"]) for row in rows),
            "claims": sum(as_int(row["claim_count"]) for row in rows),
            "statuses": {status: status_counts[status] for status in STATUSES},
        })

    status_counts = Counter(str(record["status"]) for record in records)
    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": str(input_path.relative_to(PROJECT_ROOT)),
            "sourceSha256": sha256(input_path),
            "definition": "broad_fringe_science_v1" if broad else "legacy_narrow",
            "statementDefinition": "health_object_focus_v1",
            "statementSource": str(statement_path.relative_to(PROJECT_ROOT)),
            "statementSourceSha256": sha256(statement_path),
            "status": "provisional_model_assisted_not_human_validated",
            "unit": "256-word windows with 128-word stride",
        },
        "summary": {
            "shows": len({record["show"] for record in records}),
            "episodes": len(episodes),
            "windows": len(records),
            "stage05Requested": sum(bool(record["stage05Requested"]) for record in records),
            "healthWindows": sum(bool(record["health"]) for record in records),
            "scienceWindows": sum(bool(record["science"]) for record in records),
            "claims": sum(int(record["claimCount"]) for record in records),
            "statementUnits": len({claim["statementUnitId"] for record in records for claim in record["claims"]}),
            "repeatedClaimInstances": sum(
                bool(claim["unitInstanceCount"] > 1 and not claim["isRepresentative"])
                for record in records for claim in record["claims"]
            ),
            "statuses": {status: status_counts[status] for status in STATUSES},
        },
        "episodes": episodes,
        "windows": records,
    }
    if statement_source_hashes != {payload["meta"]["sourceSha256"]}:
        raise ValueError("Statement classifications do not match the broad source CSV")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    temporary.replace(output_path)
    print(f"Prepared {len(records)} windows and {payload['summary']['claims']} claim instances")
    print(f"Output: {output_path.relative_to(PROJECT_ROOT)} ({output_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
