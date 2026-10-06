#!/usr/bin/env python3
"""Quality checks for annotated local transcripts when no reference transcript exists.

Per episode (reads transcript_annotated.json.gz; no network, no model calls):

Transcription
  words_per_minute       speaking rate over the whole audio (very low = dropped speech)
  low_conf_share         share of words with model confidence < 0.5
  gaps_over_15s          stretches of >15 s with no words (music, ads, or missed speech)
  repeated_phrase_loops  the same 4-word phrase three or more times in a row (decoder loop)

Speaker identification
  vocative checks        "Joe," / ", Joe" said by the speaker labelled Joe, or the guest's
                         first name used as address by the speaker labelled as that guest;
                         both indicate a wrong label (rate per 100 such addresses)
  mid_sentence_switches  share of speaker changes where the previous turn ends without
                         sentence punctuation and the next starts in lower case
  flag_low_host_share    host speaks < 25% of words: often two voices merged by diarization
                         (check by reading), though legitimate in multi-guest debates

Output: output/quality/<sample id>.csv and printed examples of each flag.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PODCASTS = ROOT / "config/podcasts.json"


def load(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def vocative(text: str, name: str) -> bool:
    """True when `name` is used to address someone ("Joe, ..." or "..., Joe." / "Joe?")."""
    pattern = rf"(^|[.!?]\s+){re.escape(name)},|,\s*{re.escape(name)}[.!?,]"
    return re.search(pattern, text) is not None


def check(document: dict[str, Any], host_first_names: list[str]) -> tuple[dict[str, Any], dict[str, list[str]]]:
    utterances = document["utterances"]
    words = [w for u in utterances for w in u["words"]]
    duration_min = (document["transcription"].get("audio_duration_seconds") or 1) / 60
    roles = {s["name"]: s["role"] for s in document["speakers"]}
    guests = [name for name, role in roles.items() if role == "guest" and name not in ("Guest", "Unknown")]
    guest_first = {name.split()[0]: name for name in guests}
    examples: dict[str, list[str]] = {"vocative_violation": [], "mid_sentence_switch": [], "gap": [], "loop": []}

    gaps = []
    for previous, current in zip(words, words[1:]):
        if current["start"] - previous["end"] > 15000:
            gaps.append((previous["end"], current["start"]))
    for start, end in gaps[:3]:
        examples["gap"].append(f"{start // 60000:02d}:{start // 1000 % 60:02d} – {end // 60000:02d}:{end // 1000 % 60:02d}")

    tokens = [w["text"].lower().strip(".,!?") for w in words]
    loops = 0
    i = 0
    while i + 12 <= len(tokens):
        phrase = tokens[i:i + 4]
        if tokens[i + 4:i + 8] == phrase and tokens[i + 8:i + 12] == phrase:
            loops += 1
            examples["loop"].append(" ".join(phrase))
            i += 12
        else:
            i += 1

    addresses = violations = 0
    for utterance in utterances:
        text, speaker = utterance["text"], utterance["speaker"]
        for host in host_first_names:
            if vocative(text, host):
                addresses += 1
                if speaker.split()[0] == host:
                    violations += 1
                    examples["vocative_violation"].append(f"{speaker}: …{text[:110]}")
        for first, full in guest_first.items():
            if vocative(text, first):
                addresses += 1
                if speaker == full:
                    violations += 1
                    examples["vocative_violation"].append(f"{speaker}: …{text[:110]}")

    switches = mid = 0
    for previous, current in zip(utterances, utterances[1:]):
        if previous["speaker"] != current["speaker"]:
            switches += 1
            if not re.search(r"[.!?…\"']\s*$", previous["text"]) and current["text"][:1].islower():
                mid += 1
                if len(examples["mid_sentence_switch"]) < 3:
                    examples["mid_sentence_switch"].append(
                        f"{previous['speaker']}: …{previous['text'][-60:]} | {current['speaker']}: {current['text'][:60]}…")

    shares: dict[str, int] = {}
    for utterance in utterances:
        shares[utterance["role"]] = shares.get(utterance["role"], 0) + len(utterance["words"])
    total = sum(shares.values()) or 1
    row = {
        "words": len(words),
        "words_per_minute": round(len(words) / duration_min, 1),
        "low_conf_share": round(sum(w["confidence"] < 0.5 for w in words) / max(len(words), 1), 4),
        "gaps_over_15s": len(gaps),
        "gap_minutes": round(sum(end - start for start, end in gaps) / 60000, 1),
        "repeated_phrase_loops": loops,
        "name_addresses": addresses,
        "vocative_violations": violations,
        "violation_rate": round(violations / addresses, 3) if addresses else "",
        "speaker_switches": switches,
        "mid_sentence_switch_share": round(mid / switches, 3) if switches else "",
        **{f"share_{role}": round(count / total, 3) for role, count in sorted(shares.items())},
        "flag_low_host_share": int(shares.get("host", 0) / total < 0.25),
    }
    return row, examples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--transcript-root", default="data/derived/transcripts_local_parakeet")
    args = parser.parse_args()
    sample = json.loads((ROOT / args.sample).read_text(encoding="utf-8"))
    show = json.loads(PODCASTS.read_text(encoding="utf-8"))["podcasts"][sample["show_id"]]
    hosts = [name.split()[0] for name in show["hosts"]]
    rows = []
    for episode in sample["episodes"]:
        path = ROOT / args.transcript_root / show["raw_directory"] / episode["episode_id"] / "transcript_annotated.json.gz"
        if not path.exists():
            continue
        document = load(path)
        row, examples = check(document, hosts)
        rows.append({"episode_id": episode["episode_id"], "title": document["episode"]["title"], **row})
        print(f"\n{document['episode']['title']}: {row['words_per_minute']} wpm, low-conf {row['low_conf_share']:.1%}, "
              f"gaps>15s {row['gaps_over_15s']}, loops {row['repeated_phrase_loops']}, "
              f"name-address violations {row['vocative_violations']}/{row['name_addresses']}, "
              f"mid-sentence switches {row['mid_sentence_switch_share']}"
              + ("  ⚠ LOW HOST SHARE - read to check for merged voices" if row["flag_low_host_share"] else ""))
        for kind, items in examples.items():
            for item in items[:3]:
                print(f"   [{kind}] {item}")
    output = ROOT / "output/quality" / f"{sample['sample_id']}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
