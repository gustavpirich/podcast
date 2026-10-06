#!/usr/bin/env python3
"""Build the statement- and speaker-level supply dataset for the 20-episode pilot.

Applies the researcher's 2026-10-01 fringe definition to the frozen broad-fringe
and health-object labels and attributes each statement to the diarized speaker
who said it. No model calls are made; all labels remain provisional.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = "e5112711aca03600"
INSTANCES = ROOT / f"data/derived/classifications/health_objects/{RUN}/statement_instances.csv"
UNITS = ROOT / f"data/derived/classifications/health_objects/{RUN}/statement_units.csv"
PODCASTS = ROOT / "config/podcasts.json"
TRANSCRIPTS = ROOT / "data/derived/transcripts"
OUTPUT = ROOT / f"data/derived/descriptives/fringe_supply_pilot_20_{RUN}"
DEFINITION_VERSION = "fringe_tiers_v1_2026-10-01"

# Researcher decision 2026-10-01: emerging, speculative and consensus-contradicting
# positions are all fringe, reported as separate tiers. Exaggeration alone is not.
TIERS = {
    "emerging_non_mainstream": "A_emerging",
    "alternative_speculative": "B_speculative",
    "contradicts_consensus": "C_contradicts_consensus",
    "mainstream": "not_fringe",
    "uncertain": "uncertain",
}
FRINGE_TIERS = {"A_emerging", "B_speculative", "C_contradicts_consensus"}
ADVANCED_STANCES = {"asserted", "tentative"}
NORMALIZED_TOKEN = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)

csv.field_size_limit(sys.maxsize)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def normalized(text: str) -> str:
    return " ".join(
        match.group(0).casefold().replace("’", "'")
        for match in NORMALIZED_TOKEN.finditer(text)
    )


def fringe_tier(position: str) -> str:
    if position not in TIERS:
        raise ValueError(f"Unknown scientific position: {position!r}")
    return TIERS[position]


def flatten_words(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    """Same word order and indices as Stage 05 `flatten_transcript_words`."""
    words: list[dict[str, Any]] = []
    for utterance in transcript["utterances"]:
        for word in utterance["words"]:
            text = str(word.get("text") or "").strip()
            if not text:
                raise ValueError("Transcript contains an empty word")
            start_ms = int(word.get("start") or 0)
            words.append({
                "speaker": str(word.get("speaker") or utterance.get("speaker") or "Unknown speaker"),
                "start_ms": start_ms,
                "end_ms": int(word.get("end") or start_ms),
                "text": text,
            })
    return words


def speaker_roles(transcript: dict[str, Any], hosts: set[str]) -> dict[str, str]:
    """Map diarized speaker labels to host, guest or unidentified."""
    roles: dict[str, str] = {}
    for speaker in transcript["speakers"]:
        role = str(speaker.get("role") or "").casefold()
        name = str(speaker.get("name") or speaker["id"])
        if name in hosts:
            value = "host"
        elif role == "host":
            raise ValueError(f"Transcript host {name!r} is not a configured host")
        elif role == "guest":
            value = "guest"
        else:
            value = "unidentified"
        roles[name] = value
        roles[str(speaker["id"])] = value
    return roles


def attribute_span(
    words: list[dict[str, Any]], start: int, end: int, roles: dict[str, str]
) -> dict[str, Any]:
    """Attribute a word span to its majority speaker."""
    if not 0 <= start < end <= len(words):
        raise ValueError(f"Claim span {start}:{end} outside transcript of {len(words)} words")
    span = words[start:end]
    counts = Counter(word["speaker"] for word in span)
    speaker, n = max(counts.items(), key=lambda item: (item[1], item[0]))
    return {
        "speaker": speaker,
        "speaker_role": roles.get(speaker, "unidentified"),
        "speaker_word_share": round(n / len(span), 6),
        "span_crosses_speakers": int(len(counts) > 1),
        "start_ms": span[0]["start_ms"],
        "end_ms": span[-1]["end_ms"],
        "span_text": " ".join(word["text"] for word in span),
    }


def build_statements(
    instances: list[dict[str, str]],
    units: list[dict[str, str]],
    transcripts: dict[tuple[str, str], tuple[list[dict[str, Any]], dict[str, str]]],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in instances:
        groups[row["statement_unit_id"]].append(row)
    unit_by_id = {row["statement_unit_id"]: row for row in units}
    if len(unit_by_id) != len(units) or set(unit_by_id) != set(groups):
        raise ValueError("Statement units and instances do not reconcile")

    output: list[dict[str, Any]] = []
    for unit_id in sorted(groups):
        group = groups[unit_id]
        unit = unit_by_id[unit_id]
        reps = [row for row in group if row["is_representative"] == "1"]
        if len(reps) != 1:
            raise ValueError(f"{unit_id} needs exactly one representative instance")
        rep = reps[0]
        if len({(row["show"], row["episode_id"]) for row in group}) != 1:
            raise ValueError(f"{unit_id} crosses episode boundaries")

        tier = fringe_tier(rep["existing_scientific_position"])
        instance_fringe = [fringe_tier(row["existing_scientific_position"]) in FRINGE_TIERS for row in group]
        verified = unit["source_span_status"] == "aligned"
        advanced = rep["existing_stance"] in ADVANCED_STANCES

        attribution: dict[str, Any] = {
            "speaker": "", "speaker_role": "unknown", "speaker_word_share": "",
            "span_crosses_speakers": "", "start_ms": "", "end_ms": "",
        }
        text_match = ""
        if verified:
            words, roles = transcripts[(rep["show"], rep["episode_id"])]
            attribution = attribute_span(
                words, int(unit["source_word_start"]), int(unit["source_word_end_exclusive"]), roles
            )
            text_match = int(normalized(attribution.pop("span_text")) == normalized(unit["exact_claim_text"]))

        output.append({
            "statement_unit_id": unit_id,
            "show": rep["show"],
            "episode_id": rep["episode_id"],
            "episode_title": rep["episode_title"],
            "guest": rep["guest"],
            "published_date": rep["published_date"],
            "exact_claim_text": unit["exact_claim_text"],
            "claim_domain": rep["existing_claim_domain"],
            "primary_object": rep["primary_object"],
            "product_maturity": rep["product_maturity"],
            "scientific_position": rep["existing_scientific_position"],
            "stance": rep["existing_stance"],
            "exaggeration": rep["existing_exaggeration"],
            "fringe_tier": tier,
            "is_fringe_position": int(tier in FRINGE_TIERS),
            "is_advanced": int(advanced),
            "quote_verified": int(verified),
            "fringe_advanced": int(tier in FRINGE_TIERS and advanced and verified),
            "claim_instance_count": len(group),
            "any_instance_fringe_position": int(any(instance_fringe)),
            "all_instances_fringe_position": int(all(instance_fringe)),
            "source_span_status": unit["source_span_status"],
            "source_word_start": unit["source_word_start"],
            "source_word_end_exclusive": unit["source_word_end_exclusive"],
            **attribution,
            "transcript_text_match": text_match,
            "definition_version": DEFINITION_VERSION,
        })
    return output


def build_speakers(
    statements: list[dict[str, Any]],
    transcripts: dict[tuple[str, str], tuple[list[dict[str, Any]], dict[str, str]]],
) -> list[dict[str, Any]]:
    """One row per diarized speaker per episode, with raw counts (no thresholds)."""
    by_speaker: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in statements:
        if row["quote_verified"]:
            by_speaker[(row["show"], row["episode_id"], row["speaker"])].append(row)

    meta = {(row["show"], row["episode_id"]): row for row in statements}
    output: list[dict[str, Any]] = []
    for (show, episode_id), (words, roles) in sorted(transcripts.items()):
        word_counts = Counter(word["speaker"] for word in words)
        for speaker in sorted(word_counts):
            rows = by_speaker.get((show, episode_id, speaker), [])
            advanced = [row for row in rows if row["fringe_advanced"]]
            tiers = Counter(row["fringe_tier"] for row in advanced)
            output.append({
                "show": show,
                "episode_id": episode_id,
                "episode_title": meta[(show, episode_id)]["episode_title"],
                "published_date": meta[(show, episode_id)]["published_date"],
                "speaker": speaker,
                "speaker_role": roles.get(speaker, "unidentified"),
                "speaker_words": word_counts[speaker],
                "verified_statements": len(rows),
                "advanced_statements": sum(row["is_advanced"] for row in rows),
                "uncertain_statements": sum(row["fringe_tier"] == "uncertain" for row in rows),
                "fringe_advanced_statements": len(advanced),
                "fringe_advanced_A_emerging": tiers["A_emerging"],
                "fringe_advanced_B_speculative": tiers["B_speculative"],
                "fringe_advanced_C_contradicts_consensus": tiers["C_contradicts_consensus"],
                "exaggerated_advanced_statements": sum(
                    row["is_advanced"] and row["exaggeration"] == "yes" for row in rows
                ),
                "definition_version": DEFINITION_VERSION,
            })
    return output


def load_transcripts(
    episodes: set[tuple[str, str]],
) -> dict[tuple[str, str], tuple[list[dict[str, Any]], dict[str, str]]]:
    podcasts = json.loads(PODCASTS.read_text(encoding="utf-8"))["podcasts"]
    loaded = {}
    for show, episode_id in sorted(episodes):
        config = podcasts[show]
        path = TRANSCRIPTS / config["raw_directory"] / episode_id / "transcript.json"
        transcript = json.loads(path.read_text(encoding="utf-8"))
        loaded[(show, episode_id)] = (
            flatten_words(transcript),
            speaker_roles(transcript, set(config["hosts"])),
        )
    return loaded


def main() -> int:
    instances = read_csv(INSTANCES)
    units = read_csv(UNITS)
    episodes = {(row["show"], row["episode_id"]) for row in instances}
    transcripts = load_transcripts(episodes)
    statements = build_statements(instances, units, transcripts)
    speakers = build_speakers(statements, transcripts)

    verified = [row for row in statements if row["quote_verified"]]
    summary = {
        "definition_version": DEFINITION_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "provisional_model_assisted_not_human_validated",
        "inputs": {
            str(path.relative_to(ROOT)): sha256(path) for path in (INSTANCES, UNITS, PODCASTS)
        },
        "transcripts": {
            f"{show}/{episode_id}": sha256(
                TRANSCRIPTS / json.loads(PODCASTS.read_text())["podcasts"][show]["raw_directory"]
                / episode_id / "transcript.json"
            )
            for show, episode_id in sorted(episodes)
        },
        "counts": {
            "episodes": len(episodes),
            "statement_units": len(statements),
            "claim_instances": len(instances),
            "quote_verified": len(verified),
            "quote_unverified": len(statements) - len(verified),
            "transcript_text_match": sum(row["transcript_text_match"] == 1 for row in verified),
            "span_crosses_speakers": sum(row["span_crosses_speakers"] == 1 for row in verified),
            "fringe_tier": dict(sorted(Counter(row["fringe_tier"] for row in statements).items())),
            "fringe_position_unverified": sum(
                row["is_fringe_position"] and not row["quote_verified"] for row in statements
            ),
            "fringe_advanced": sum(row["fringe_advanced"] for row in statements),
            "fringe_advanced_by_role": dict(sorted(Counter(
                row["speaker_role"] for row in statements if row["fringe_advanced"]
            ).items())),
            "speaker_rows": len(speakers),
        },
    }
    if len({row["statement_unit_id"] for row in statements}) != len(statements):
        raise ValueError("Statement unit IDs are not unique")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "statements.csv", statements)
    write_csv(OUTPUT / "speakers.csv", speakers)
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
