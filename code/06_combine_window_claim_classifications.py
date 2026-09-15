#!/usr/bin/env python3
"""Combine compatible Stage-05 window CSVs with provenance checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DERIVED_ROOT = PROJECT_ROOT / "data" / "derived"
VALID_STATUSES = {"fringe", "not_fringe", "uncertain", "not_assessable"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    inputs = [(PROJECT_ROOT / path).resolve() for path in args.input]
    output_dir = (PROJECT_ROOT / args.output_dir).resolve()
    if not inside(output_dir, DERIVED_ROOT):
        parser.error("--output-dir must be inside data/derived")
    if len(set(inputs)) != len(inputs):
        parser.error("Every --input must be unique")

    rows: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    sources: list[dict[str, object]] = []
    for input_path in inputs:
        if not inside(input_path, DERIVED_ROOT):
            parser.error(f"Input is outside data/derived: {input_path}")
        with input_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            current_fields = reader.fieldnames
            current_rows = list(reader)
        if not current_fields:
            parser.error(f"Input has no CSV header: {input_path}")
        if fieldnames is None:
            fieldnames = current_fields
        elif current_fields != fieldnames:
            parser.error(f"Input headers differ: {input_path}")
        summary_path = input_path.with_name("classification_summary.json")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary["totals"]["windows"] != len(current_rows):
            parser.error(f"Summary row count differs for {input_path}")
        sources.append({
            "csv": str(input_path.relative_to(PROJECT_ROOT)),
            "csv_sha256": sha256(input_path),
            "summary": str(summary_path.relative_to(PROJECT_ROOT)),
            "summary_sha256": sha256(summary_path),
            "batch_id": summary["method"]["batch_id"],
            "rows": len(current_rows),
        })
        rows.extend(current_rows)

    required = {
        "show", "episode_id", "window_id", "word_start_index", "word_count",
        "stage05_requested", "fringe_status", "claim_count",
    }
    if fieldnames is None or not required.issubset(fieldnames):
        parser.error("Inputs are missing required Stage-05 columns")
    keys = [(row["show"], row["episode_id"], row["window_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        parser.error("Combined show/episode/window keys are not unique")
    if any(int(row["word_count"]) != 256 for row in rows):
        parser.error("Every combined row must contain exactly 256 words")
    if any(row["fringe_status"] not in VALID_STATUSES for row in rows):
        parser.error("Combined rows contain an invalid fringe status")

    rows.sort(key=lambda row: (
        row["show"], row["episode_id"], int(row["word_start_index"])
    ))
    episode_starts: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        episode_starts.setdefault(
            (row["show"], row["episode_id"]), []
        ).append(int(row["word_start_index"]))
    for key, starts in episode_starts.items():
        if any(second - first != 128 for first, second in zip(starts, starts[1:])):
            parser.error(f"Window stride is not 128 for {key[0]} / {key[1]}")

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "pilot_20_window_claim_classification.csv"
    temporary_csv = csv_path.with_suffix(".csv.tmp")
    with temporary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary_csv.replace(csv_path)

    summary = {
        "schema_version": "0.1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "provisional_model_assisted_not_human_validated",
        "unit": "one_overlapping_256_word_window_per_row_with_128_word_stride",
        "sources": sources,
        "totals": {
            "shows": len({row["show"] for row in rows}),
            "episodes": len(episode_starts),
            "windows": len(rows),
            "stage05_requested_windows": sum(int(row["stage05_requested"]) for row in rows),
            "claims_extracted_in_windows": sum(int(row["claim_count"]) for row in rows),
            "window_fringe_statuses": dict(sorted(Counter(
                row["fringe_status"] for row in rows
            ).items())),
        },
        "checks": {
            "unique_show_episode_window_keys": True,
            "all_windows_256_words": True,
            "within_episode_stride_128_words": True,
            "source_headers_identical": True,
        },
    }
    summary_path = output_dir / "pilot_20_classification_summary.json"
    temporary_summary = summary_path.with_suffix(".json.tmp")
    temporary_summary.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary_summary.replace(summary_path)
    print(f"Combined {len(rows)} windows from {len(episode_starts)} episodes")
    print(f"CSV: {csv_path.relative_to(PROJECT_ROOT)}")
    print(f"Summary: {summary_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
