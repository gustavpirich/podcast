#!/usr/bin/env python3
"""Show how far every episode has moved through the pipeline.

Read-only inventory: scans the raw episode records, transcripts and collected
classification runs, then writes one row per episode with its status at each
stage and the next script to run. No API calls are made and nothing in
data/raw/ is changed. Run it any time, for example after each batch:

    python code/00_pipeline_status.py

Outputs (overwritten on each run, because they describe the current state):
    data/derived/pipeline_status/episode_status.csv
    output/pipeline_status/status_report.md
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
RAW_TRANSCRIPTS = ROOT / "data/raw/transcripts"
TRANSCRIPTS = ROOT / "data/derived/transcripts"
CLASSIFICATIONS = ROOT / "data/derived/classifications"
DESCRIPTIVES = ROOT / "data/derived/descriptives"
CSV_OUTPUT = ROOT / "data/derived/pipeline_status/episode_status.csv"
REPORT_OUTPUT = ROOT / "output/pipeline_status/status_report.md"

# Collected outputs of the claim-level stages. Each file has `show` and
# `episode_id` columns; an episode counts as done when it appears in one.
CLAIM_STAGE_OUTPUTS = {
    "stage05_narrow_claims": "openai_passage_content/*/*/window_claim_classification.csv",
    "stage08_broad_claims": "broad_fringe/*/broad_window_classification.csv",
    "stage10_statements": "health_objects/*/statement_instances.csv",
    "stage12_veracity": "veracity/*/statement_instances.csv",
}
# The current main path for one episode. Stage 05 (narrow) and 12 (veracity)
# are reported but are not required for the supply dataset.
NEXT_STEPS = [
    ("transcript_status", "complete", "02 transcribe (AssemblyAI)"),
    ("stage04_screen", "collected", "04 health/science screen"),
    ("stage08_broad_claims", "collected", "08 extract claims (broad fringe)"),
    ("stage10_statements", "collected", "10 objects + merge duplicate claims"),
    ("stage14_speaker_dataset", "built", "14 attribute claims to speakers"),
]

csv.field_size_limit(sys.maxsize)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def show_ids() -> dict[str, str]:
    """Map raw directory names (the_joe_rogan_experience) to show IDs (jre)."""
    podcasts = read_json(CONFIG / "podcasts.json")["podcasts"]
    return {item["raw_directory"]: show_id for show_id, item in podcasts.items()}


def sample_memberships() -> dict[tuple[str, str], list[str]]:
    """Return the frozen sample IDs each (show, episode) belongs to."""
    members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for path in sorted(CONFIG.glob("*.json")):
        document = read_json(path)
        episodes = document.get("episodes") if isinstance(document, dict) else None
        if not isinstance(episodes, list) or "show_id" not in document:
            continue
        for episode in episodes:
            episode_id = episode.get("episode_id") or episode.get("youtube_id")
            members[(document["show_id"], episode_id)].append(document["sample_id"])
    return members


def episode_metadata(episode_dir: Path) -> dict[str, Any]:
    """Read the immutable RSS record written by the acquisition scripts."""
    path = episode_dir / "rss_metadata.json"
    if not path.is_file():
        return {"metadata": "missing"}
    record = read_json(path)
    episode = record.get("episode") or {}
    media = record.get("media") or {}
    podcast = record.get("podcast") or {}
    duration = media.get("duration_seconds") or episode.get("duration_declared") or ""
    return {
        "metadata": "present",
        "title": episode.get("title", ""),
        "published_date": str(episode.get("published_at", ""))[:10],
        "duration_hours": round(float(duration) / 3600, 3) if duration else "",
        "guest_label": podcast.get("guest_label_candidate") or "",
        "audio_kept_locally": int(any(episode_dir.glob("*.m4a"))),
    }


def transcript_status(episode_dir: Path) -> str:
    """Same rule as 02_transcribe_assemblyai_batch.py, without raising."""
    finals = [
        (episode_dir / "transcript.md").exists(),
        any((episode_dir / name).exists() for name in ("transcript.json", "transcript.json.gz")),
        any(
            (episode_dir / name).exists()
            for name in ("assemblyai_response.json", "assemblyai_response.json.gz")
        ),
    ]
    if all(finals):
        return "complete"
    if any(finals):
        return "incomplete_outputs"
    if (episode_dir / "assemblyai_job.json").exists():
        return "submitted"
    return "not_started"


def transcript_speakers(episode_dir: Path) -> dict[str, Any]:
    """Summarize diarized speakers: names, host/guest roles and word shares."""
    path = episode_dir / "transcript.json"
    if path.is_file():
        transcript = read_json(path)
    else:
        with gzip.open(episode_dir / "transcript.json.gz", "rt", encoding="utf-8") as handle:
            transcript = json.load(handle)
    roles = {}
    for speaker in transcript["speakers"]:
        role = str(speaker.get("role") or "").casefold()
        role = role if role in ("host", "guest") else "unidentified"
        roles[str(speaker.get("name") or speaker["id"])] = role
    words: Counter[str] = Counter()
    for utterance in transcript["utterances"]:
        words[roles.get(utterance["speaker"], "unidentified")] += len(utterance.get("words") or [])
    total = sum(words.values())
    status = (transcript.get("transcription") or {}).get("speaker_identification_status")
    return {
        "transcript_words": total,
        "speakers": " | ".join(f"{name} ({role})" for name, role in roles.items()),
        "n_hosts": sum(role == "host" for role in roles.values()),
        "n_guests": sum(role == "guest" for role in roles.values()),
        "n_unidentified": sum(role == "unidentified" for role in roles.values()),
        "unidentified_word_share": round(words["unidentified"] / total, 4) if total else "",
        "speaker_identification_status": status or "not_recorded_in_transcript",
    }


def screen_status(show_directory: str, episode_id: str) -> dict[str, Any]:
    """Stage 04: per-episode run folders, collected when the CSV exists."""
    episode_dir = CLASSIFICATIONS / "openai_batch" / show_directory / episode_id
    if not episode_dir.is_dir():
        return {"stage04_screen": "not_started"}
    collected = sorted(episode_dir.glob("*/window_classification.csv"))
    if not collected:
        submitted = any(episode_dir.glob("*/batch_job.json"))
        return {"stage04_screen": "submitted" if submitted else "prepared"}
    with collected[-1].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    positive = sum(
        row["health_related"] in ("1", "True", "true") or row["science_related"] in ("1", "True", "true")
        for row in rows
    )
    return {
        "stage04_screen": "collected",
        "stage04_run": collected[-1].parent.name,
        "windows": len(rows),
        "screen_positive_windows": positive,
    }


def claim_stage_coverage() -> dict[str, dict[tuple[str, str], list[str]]]:
    """For each claim stage, map (show, episode) to the collected run IDs."""
    coverage: dict[str, dict[tuple[str, str], list[str]]] = {}
    for stage, pattern in CLAIM_STAGE_OUTPUTS.items():
        found: dict[tuple[str, str], list[str]] = defaultdict(list)
        for path in sorted(CLASSIFICATIONS.glob(pattern)):
            for key in episodes_in_csv(path):
                found[key].append(path.parent.name)
        coverage[stage] = found
    found = defaultdict(list)
    for path in sorted(DESCRIPTIVES.glob("*/statements.csv")):
        for key in episodes_in_csv(path):
            found[key].append(path.parent.name)
    coverage["stage14_speaker_dataset"] = found
    return coverage


def uncollected_veracity_episodes() -> set[tuple[str, str]]:
    """Episodes in a veracity run that was submitted but never collected."""
    pending: set[tuple[str, str]] = set()
    for run in sorted((CLASSIFICATIONS / "veracity").glob("*/")):
        if (run / "batch_job.json").exists() and not (run / "statement_instances.csv").exists():
            pending |= episodes_in_csv(run / "source_statement_instances.csv")
    return pending


def episodes_in_csv(path: Path) -> set[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {(row["show"], row["episode_id"]) for row in csv.DictReader(handle)}


def next_step(row: dict[str, Any]) -> str:
    if row["transcript_status"] == "submitted":
        return "02 collect submitted transcription (rerun the batch command)"
    if row["transcript_status"] == "incomplete_outputs":
        return "02 inspect incomplete transcript outputs by hand"
    for column, done, label in NEXT_STEPS:
        if row[column] != done:
            return label
    return "done; awaiting human validation"


def build_rows() -> list[dict[str, Any]]:
    shows = show_ids()
    samples = sample_memberships()
    coverage = claim_stage_coverage()
    veracity_pending = uncollected_veracity_episodes()
    episode_dirs = {
        (path.parent.name, path.name): path
        for root in (RAW_TRANSCRIPTS, TRANSCRIPTS)
        for path in root.glob("*/*")
        if path.is_dir()
    }
    rows = []
    for (show_directory, episode_id) in sorted(episode_dirs):
        if show_directory not in shows:
            raise ValueError(f"{show_directory} is not a raw_directory in config/podcasts.json")
        show = shows[show_directory]
        key = (show, episode_id)
        row: dict[str, Any] = {
            "show": show,
            "episode_id": episode_id,
            "samples": "; ".join(samples.get(key, [])),
            **episode_metadata(RAW_TRANSCRIPTS / show_directory / episode_id),
            "transcript_status": transcript_status(TRANSCRIPTS / show_directory / episode_id),
        }
        if row["transcript_status"] == "complete":
            row.update(transcript_speakers(TRANSCRIPTS / show_directory / episode_id))
        row.update(screen_status(show_directory, episode_id))
        for stage, found in coverage.items():
            done = "built" if stage == "stage14_speaker_dataset" else "collected"
            row[stage] = done if key in found else "not_started"
            row[f"{stage}_runs"] = "; ".join(found.get(key, []))
        if row["stage12_veracity"] == "not_started" and key in veracity_pending:
            row["stage12_veracity"] = "submitted_not_collected"
        row["next_step"] = next_step(row)
        rows.append(row)
    return rows


COLUMNS = [
    "show", "episode_id", "title", "published_date", "duration_hours", "guest_label",
    "samples", "metadata", "audio_kept_locally", "transcript_status",
    "transcript_words", "speaker_identification_status", "n_hosts", "n_guests",
    "n_unidentified", "unidentified_word_share", "speakers", "stage04_screen", "stage04_run", "windows", "screen_positive_windows",
    "stage05_narrow_claims", "stage05_narrow_claims_runs",
    "stage08_broad_claims", "stage08_broad_claims_runs",
    "stage10_statements", "stage10_statements_runs",
    "stage12_veracity", "stage12_veracity_runs",
    "stage14_speaker_dataset", "stage14_speaker_dataset_runs", "next_step",
]


def write_csv(rows: list[dict[str, Any]]) -> None:
    CSV_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, restval="")
        writer.writeheader()
        writer.writerows(rows)


def hours(rows: list[dict[str, Any]]) -> str:
    return f"{sum(float(row['duration_hours'] or 0) for row in rows):,.1f}"


def stage_table(groups: dict[str, list[dict[str, Any]]], label: str) -> list[str]:
    stages = [
        ("Transcribed", "transcript_status", "complete"),
        ("Screened (04)", "stage04_screen", "collected"),
        ("Narrow claims (05)", "stage05_narrow_claims", "collected"),
        ("Broad claims (08)", "stage08_broad_claims", "collected"),
        ("Statements (10)", "stage10_statements", "collected"),
        ("Veracity (12)", "stage12_veracity", "collected"),
        ("Speaker dataset (14)", "stage14_speaker_dataset", "built"),
    ]
    lines = [
        f"| {label} | Episodes | Hours | " + " | ".join(name for name, _, _ in stages) + " |",
        "| --- | ---: | ---: | " + " | ".join("---:" for _ in stages) + " |",
    ]
    for name, members in groups.items():
        counts = [sum(row[column] == done for row in members) for _, column, done in stages]
        lines.append(
            f"| {name} | {len(members)} | {hours(members)} | "
            + " | ".join(str(count) for count in counts) + " |"
        )
    return lines


def report(rows: list[dict[str, Any]], generated_at: str) -> str:
    by_show: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_show[row["show"]].append(row)
        for sample in filter(None, row["samples"].split("; ")):
            by_sample[sample].append(row)
    transcribed = [row for row in rows if row["transcript_status"] == "complete"]
    words = sum(int(row["transcript_words"]) for row in transcribed)
    flagged = sorted(
        (row for row in transcribed if row["n_unidentified"] or not row["n_guests"]),
        key=lambda row: -float(row["unidentified_word_share"] or 0),
    )
    in_progress = [
        row for row in rows
        if row["transcript_status"] in ("submitted", "incomplete_outputs")
        or row["stage04_screen"] in ("prepared", "submitted")
        or row["stage12_veracity"] == "submitted_not_collected"
    ]
    lines = [
        "# Pipeline status",
        "",
        f"Generated {generated_at} by `code/00_pipeline_status.py` (read-only scan).",
        f"Row-level detail: `{CSV_OUTPUT.relative_to(ROOT)}`.",
        "",
        "Each cell counts episodes that have finished that stage. A stage is",
        "*collected* only when its final CSV exists; submitted Batch jobs are not counted.",
        "",
        f"Transcribed so far: {len(transcribed)} episodes, {hours(transcribed)} hours, "
        f"{words:,} words.",
        "",
        "## By show",
        "",
        *stage_table(dict(sorted(by_show.items())), "Show"),
        "",
        "## By frozen sample (config/*.json)",
        "",
        *stage_table(dict(sorted(by_sample.items())), "Sample"),
        "",
        "## Next step for each episode",
        "",
        "| Next step | Episodes | Hours |",
        "| --- | ---: | ---: |",
    ]
    steps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        steps[row["next_step"]].append(row)
    for step, members in sorted(steps.items()):
        lines.append(f"| {step} | {len(members)} | {hours(members)} |")
    lines += ["", "## Work in progress", ""]
    if in_progress:
        lines += [
            f"- {row['show']}/{row['episode_id']}: transcript {row['transcript_status']}, "
            f"screen {row['stage04_screen']}, veracity {row['stage12_veracity']}"
            for row in in_progress[:50]
        ]
        if len(in_progress) > 50:
            lines.append(f"- ... and {len(in_progress) - 50} more (see the CSV)")
    else:
        lines.append("- None.")
    lines += ["", "## Transcripts whose speaker names need attention", ""]
    if flagged:
        lines += [
            "Diarized voices without a host/guest name (often a producer, an ad or a",
            "second guest), sorted by their share of the episode's words. Claims spoken",
            "by these voices cannot be attributed to host or guest.",
            "",
            "| Episode | Title | Unnamed voices | Share of words | Identification status |",
            "| --- | --- | ---: | ---: | --- |",
        ]
        lines += [
            f"| {row['show']}/{row['episode_id']} | {row['title'].replace('|', '/')} | "
            f"{row['n_unidentified']} | "
            f"{float(row['unidentified_word_share'] or 0):.1%} | {row['speaker_identification_status']} |"
            for row in flagged
        ]
    else:
        lines.append("- None.")
    lines += [
        "",
        "All speaker names are machine-inferred until verified by a person; all",
        "classification labels are provisional model output.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    rows = build_rows()
    keys = [(row["show"], row["episode_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate (show, episode_id) keys")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_csv(rows)
    REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUTPUT.write_text(report(rows, generated_at), encoding="utf-8")
    counts = Counter(row["next_step"] for row in rows)
    print(f"{len(rows)} episodes scanned")
    for step, count in sorted(counts.items()):
        print(f"  {count:5d}  next: {step}")
    print(f"Wrote {CSV_OUTPUT.relative_to(ROOT)}")
    print(f"Wrote {REPORT_OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
