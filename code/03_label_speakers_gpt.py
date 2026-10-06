#!/usr/bin/env python3
"""Name the diarized speakers of local transcripts (host / guest / producer / ad) with GPT.

For each transcript, sends the episode title, the start of its description,
the configured host names and short excerpts of every diarized speaker
(A, B, ...) to OpenAI, and asks for a name and role per speaker under the
rules in config/speaker_labeling.json. The original transcript is not
changed; the result is written next to it:

    speaker_roles.json            model answer, prompt version, usage, timestamp
    transcript_annotated.json.gz  transcript with names and roles applied
    transcript_annotated.md       readable version: "[00:01:23] Joe Rogan (host): ..."

    python code/03_label_speakers_gpt.py --sample config/samples/<id>.json          # plan
    python code/03_label_speakers_gpt.py --sample config/samples/<id>.json --yes    # call OpenAI
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import runpy
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/speaker_labeling.json"
PODCASTS = ROOT / "config/podcasts.json"
RAW_TRANSCRIPTS = ROOT / "data/raw/transcripts"
DEFAULT_ROOT = "data/derived/transcripts_local_parakeet"
LOCAL = runpy.run_path(str(ROOT / "code/02_transcribe_local.py"))


def load_json_gz(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def speaker_profiles(document: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Word share plus evenly spread excerpts for each diarized label."""
    words: Counter[str] = Counter()
    turns: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for utterance in document["utterances"]:
        words[utterance["speaker"]] += len(utterance["words"])
        turns[utterance["speaker"]].append(utterance)
    total = sum(words.values()) or 1
    profiles = []
    for label in sorted(turns):
        items = sorted(turns[label], key=lambda u: -len(u["words"]))[: 3 * config["excerpts_per_speaker"]]
        items = sorted(items, key=lambda u: u["start"])
        step = max(1, len(items) // config["excerpts_per_speaker"])
        excerpts = []
        for utterance in items[::step][: config["excerpts_per_speaker"]]:
            text = " ".join(utterance["text"].split()[: config["words_per_excerpt"]])
            excerpts.append(f"[{LOCAL['FORMAT']['format_timestamp'](utterance['start'])}] {text}")
        profiles.append({"label": label, "share_of_words": round(words[label] / total, 3),
                         "turns": len(turns[label]), "excerpts": excerpts})
    return profiles


def instructions(config: dict[str, Any]) -> str:
    roles = "\n".join(f"- {name}: {text}" for name, text in config["roles"].items())
    rules = "\n".join(f"- {rule}" for rule in config["rules"])
    return ("You identify the speakers in a diarized podcast transcript.\n\nRoles:\n" + roles +
            "\n\nRules:\n" + rules)


def schema(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False, "required": ["speakers"],
        "properties": {"speakers": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["label", "name", "role", "confidence", "evidence"],
            "properties": {
                "label": {"type": "string"},
                "name": {"type": "string"},
                "role": {"type": "string", "enum": list(config["roles"])},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "evidence": {"type": "string", "description": "At most 25 words: why this identity and role."},
            }}}},
    }


def request_input(document: dict[str, Any], metadata: dict[str, Any], hosts: list[str],
                  profiles: list[dict[str, Any]]) -> str:
    episode = metadata.get("episode", {})
    return json.dumps({
        "show": metadata.get("podcast", {}).get("name"),
        "configured_hosts": hosts,
        "episode_title": episode.get("title"),
        "episode_description_start": (episode.get("description") or "")[:600],
        "diarized_speakers": profiles,
    }, ensure_ascii=False)


def validate(answer: dict[str, Any], labels: set[str], config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_label = {item["label"]: item for item in answer["speakers"]}
    if set(by_label) != labels or len(by_label) != len(answer["speakers"]):
        raise ValueError(f"Model labels {sorted(by_label)} do not match transcript labels {sorted(labels)}")
    for item in by_label.values():
        if item["role"] not in config["roles"] or not item["name"].strip():
            raise ValueError(f"Invalid speaker entry: {item}")
    return by_label


def annotate(document: dict[str, Any], by_label: dict[str, dict[str, Any]], prompt_version: str) -> dict[str, Any]:
    annotated = json.loads(json.dumps(document))
    annotated["speakers"] = [
        {"id": label, "name": item["name"], "role": item["role"], "confidence": item["confidence"],
         "evidence": item["evidence"]}
        for label, item in sorted(by_label.items())
    ]
    for utterance in annotated["utterances"]:
        item = by_label[utterance["speaker"]]
        utterance["speaker_label"] = utterance["speaker"]
        utterance["speaker"] = item["name"]
        utterance["role"] = item["role"]
        for word in utterance["words"]:
            word["speaker"] = item["name"]
    annotated["transcription"]["speaker_identification_status"] = f"gpt:{prompt_version}"
    return annotated


def markdown(annotated: dict[str, Any]) -> str:
    stamp = LOCAL["FORMAT"]["format_timestamp"]
    episode = annotated["episode"]
    lines = [f"# {episode.get('title')}", "",
             "Speakers named by GPT from title, description and excerpts (not human-verified):", ""]
    lines += [f"- {s['id']}: **{s['name']}** ({s['role']}, {s['confidence']}) — {s['evidence']}"
              for s in annotated["speakers"]]
    lines += ["", "## Transcript", ""]
    for utterance in annotated["utterances"]:
        lines += [f"**[{stamp(utterance['start'])}] {utterance['speaker']} ({utterance['role']}):** {utterance['text']}", ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--transcript-root", default=DEFAULT_ROOT)
    parser.add_argument("--redo", action="store_true", help="relabel episodes that already have speaker_roles.json")
    parser.add_argument("--yes", action="store_true", help="call the OpenAI API (small cost)")
    args = parser.parse_args()

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    sample = json.loads((ROOT / args.sample).read_text(encoding="utf-8"))
    show = json.loads(PODCASTS.read_text(encoding="utf-8"))["podcasts"][sample["show_id"]]
    root = ROOT / args.transcript_root / show["raw_directory"]
    ready = [e for e in sample["episodes"] if (root / e["episode_id"] / "transcript.json.gz").exists()]
    todo = [e for e in ready if args.redo or not (root / e["episode_id"] / "speaker_roles.json").exists()]
    print(f"{len(sample['episodes'])} sample episodes; {len(ready)} transcribed; {len(todo)} to label "
          f"with {config['model']} ({config['prompt_version']})")
    if not args.yes or not todo:
        if not args.yes:
            print("Plan only. Add --yes to call the OpenAI API (sends speaker excerpts and episode metadata).")
        return 0
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set in this environment")
    from openai import OpenAI

    client = OpenAI()
    prompt = instructions(config)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    for episode in todo:
        folder = root / episode["episode_id"]
        document = load_json_gz(folder / "transcript.json.gz")
        metadata = json.loads((RAW_TRANSCRIPTS / show["raw_directory"] / episode["episode_id"] / "rss_metadata.json")
                              .read_text(encoding="utf-8"))
        profiles = speaker_profiles(document, config)
        response = client.responses.create(
            model=config["model"], reasoning={"effort": config["reasoning_effort"]},
            max_output_tokens=config["max_output_tokens"], store=False, instructions=prompt,
            input=request_input(document, metadata, show["hosts"], profiles),
            text={"format": {"type": "json_schema", "name": "speaker_roles", "schema": schema(config), "strict": True}},
        )
        by_label = validate(json.loads(response.output_text), {p["label"] for p in profiles}, config)
        record = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": config["model"], "response_model": response.model, "response_id": response.id,
            "prompt_version": config["prompt_version"], "instructions_sha256_16": prompt_hash,
            "usage": response.usage.model_dump() if response.usage else None,
            "profiles": profiles, "speakers": list(by_label.values()),
        }
        (folder / "speaker_roles.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        annotated = annotate(document, by_label, config["prompt_version"])
        with gzip.open(folder / "transcript_annotated.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(annotated, handle, ensure_ascii=False)
        (folder / "transcript_annotated.md").write_text(markdown(annotated), encoding="utf-8")
        summary = ", ".join(f"{s['label']}={s['name']} ({s['role']}, {p['share_of_words']:.0%})"
                            for s, p in zip(sorted(by_label.values(), key=lambda s: s["label"]), profiles))
        print(f"  {episode['episode_id']}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
