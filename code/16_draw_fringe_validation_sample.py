#!/usr/bin/env python3
"""Draw a stratified human-validation sample of model-coded fringe claims.

Strata are show x speaker role (host/guest) x fringe tier. Allocation is equal
across strata, capped at stratum size, so each cell has usable precision; the
key file records the stratum weights needed for population estimates. The
coding sheet is blind: model labels and reasons are only in the key file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = "e5112711aca03600"
SOURCE = ROOT / f"data/derived/descriptives/fringe_supply_pilot_20_{RUN}"
STATEMENTS = SOURCE / "statements.csv"
INSTANCES = ROOT / f"data/derived/classifications/health_objects/{RUN}/statement_instances.csv"
PODCASTS = ROOT / "config/podcasts.json"
TRANSCRIPTS = ROOT / "data/derived/transcripts"
OUTPUT = SOURCE / "validation_v1"
SAMPLE_SIZE = 150
SEED = "fringe_validation_v1_2026-10-01"
ROLES = ("guest", "host")
CONTEXT_BEFORE = 2
CONTEXT_AFTER = 1
CODING_COLUMNS = [
    "coder", "h_empirical_general", "h_fringe_tier", "h_advanced",
    "h_own_view", "h_note",
]

csv.field_size_limit(sys.maxsize)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def order_key(value: str) -> str:
    return hashlib.sha256(f"{SEED}:{value}".encode()).hexdigest()


def allocate(sizes: dict[Any, int], total: int) -> dict[Any, int]:
    """Equal allocation capped at stratum size; leftovers go to uncapped strata."""
    if total > sum(sizes.values()):
        raise ValueError("Sample larger than population")
    allocation = {key: 0 for key in sizes}
    remaining = total
    open_keys = sorted(key for key, size in sizes.items() if size > 0)
    while remaining and open_keys:
        share, extra = divmod(remaining, len(open_keys))
        for index, key in enumerate(open_keys):
            add = min(share + (index < extra), sizes[key] - allocation[key])
            allocation[key] += add
            remaining -= add
        open_keys = [key for key in open_keys if allocation[key] < sizes[key]]
    return allocation


def context(transcript: dict[str, Any], word_start: int) -> tuple[str, str]:
    """Return surrounding utterances and the utterance containing the claim."""
    utterances = transcript["utterances"]
    offset = 0
    for index, utterance in enumerate(utterances):
        if offset + len(utterance["words"]) > word_start:
            break
        offset += len(utterance["words"])
    else:
        raise ValueError(f"Word {word_start} is beyond the transcript")
    lines = []
    for position in range(max(0, index - CONTEXT_BEFORE), min(len(utterances), index + CONTEXT_AFTER + 1)):
        marker = ">> " if position == index else ""
        lines.append(f"{marker}{utterances[position]['speaker']}: {utterances[position]['text']}")
    start_ms = int(utterances[index]["start"])
    return "\n\n".join(lines), f"{start_ms // 3_600_000:02d}:{start_ms // 60_000 % 60:02d}:{start_ms // 1000 % 60:02d}"


def main() -> int:
    statements = [row for row in read_csv(STATEMENTS) if row["fringe_advanced"] == "1"]
    population: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    excluded = 0
    for row in statements:
        if row["speaker_role"] in ROLES:
            population[(row["show"], row["speaker_role"], row["fringe_tier"])].append(row)
        else:
            excluded += 1
    allocation = allocate({key: len(rows) for key, rows in population.items()}, SAMPLE_SIZE)

    reasons = {
        row["statement_unit_id"]: row["existing_reason"]
        for row in read_csv(INSTANCES) if row["is_representative"] == "1"
    }
    podcasts = json.loads(PODCASTS.read_text(encoding="utf-8"))["podcasts"]
    transcripts: dict[tuple[str, str], dict[str, Any]] = {}

    sampled = []
    for key in sorted(population):
        chosen = sorted(population[key], key=lambda row: order_key(row["statement_unit_id"]))[: allocation[key]]
        for row in chosen:
            sampled.append((key, row))

    sheet, answer_key = [], []
    for key, row in sorted(sampled, key=lambda item: order_key("order:" + item[1]["statement_unit_id"])):
        episode = (row["show"], row["episode_id"])
        if episode not in transcripts:
            path = TRANSCRIPTS / podcasts[row["show"]]["raw_directory"] / row["episode_id"] / "transcript.json"
            transcripts[episode] = json.loads(path.read_text(encoding="utf-8"))
        context_text, timestamp = context(transcripts[episode], int(row["source_word_start"]))
        item_id = f"v1-{len(sheet) + 1:03d}"
        sheet.append({
            "item_id": item_id,
            "show": row["show"],
            "episode_title": row["episode_title"],
            "timestamp": timestamp,
            "speaker": row["speaker"],
            "claim_text": row["exact_claim_text"],
            "context": context_text,
            **{column: "" for column in CODING_COLUMNS},
        })
        stratum_n = len(population[key])
        answer_key.append({
            "item_id": item_id,
            "statement_unit_id": row["statement_unit_id"],
            "stratum": "|".join(key),
            "stratum_population": stratum_n,
            "stratum_sample": allocation[key],
            "weight": round(stratum_n / allocation[key], 6),
            "speaker_role": row["speaker_role"],
            "model_fringe_tier": row["fringe_tier"],
            "model_scientific_position": row["scientific_position"],
            "model_stance": row["stance"],
            "model_exaggeration": row["exaggeration"],
            "model_reason": reasons.get(row["statement_unit_id"], ""),
        })

    if len({row["statement_unit_id"] for row in answer_key}) != len(answer_key):
        raise ValueError("Duplicate statement in sample")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "coding_sheet.csv", sheet)
    write_csv(OUTPUT / "answer_key.csv", answer_key)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED,
        "sample_size": len(sheet),
        "population_fringe_advanced": len(statements),
        "excluded_unidentified_speaker": excluded,
        "strata": {
            "|".join(key): {"population": len(population[key]), "sample": allocation[key]}
            for key in sorted(population)
        },
        "inputs": {str(path.relative_to(ROOT)): sha256(path) for path in (STATEMENTS, INSTANCES, PODCASTS)},
        "coded_file_destination": "data/raw/human_coding/fringe_validation_v1_coded.csv",
        "codebook": "notes/FRINGE_VALIDATION_CODING.md",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("sample_size", "population_fringe_advanced",
                                                 "excluded_unidentified_speaker", "strata")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
