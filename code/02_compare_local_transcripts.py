#!/usr/bin/env python3
"""Compare local (Whisper + pyannote) transcripts with AssemblyAI for the same episodes.

For every episode present in both data/derived/transcripts_local/ and
data/derived/transcripts/, reports:

* text difference: word error rate of the local text with AssemblyAI as the
  reference (both can be wrong, so this is disagreement, not true error);
* speaker agreement: the two word sequences are aligned; each local speaker
  label is mapped to the AssemblyAI speaker it shares most words with, and
  agreement is the share of aligned words whose mapped label matches.

No network access. Output: output/local_vs_assemblyai/comparison.csv and one
side-by-side page per episode, output/local_vs_assemblyai/<show>__<episode>.html
(AssemblyAI text with the local differences marked; open it in a browser).
"""

from __future__ import annotations

import csv
import gzip
import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "data/derived/transcripts_local"
ASSEMBLYAI = ROOT / "data/derived/transcripts"
OUTPUT = ROOT / "output/local_vs_assemblyai/comparison.csv"


def tokens(document: dict[str, Any], with_utterance: bool = False):
    """Normalized word tokens and the speaker of each token (optionally its utterance index)."""
    words, speakers, utterance_index = [], [], []
    for index, utterance in enumerate(document["utterances"]):
        for word in utterance.get("words", []):
            text = re.sub(r"[^a-z0-9' ]+", " ", str(word["text"]).lower())
            for token in text.split():
                words.append(token)
                speakers.append(str(word.get("speaker") or utterance.get("speaker")))
                utterance_index.append(index)
    return (words, speakers, utterance_index) if with_utterance else (words, speakers)


def compare(reference: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    import jiwer

    ref_words, ref_speakers = tokens(reference)
    hyp_words, hyp_speakers = tokens(local)
    result = jiwer.process_words(" ".join(ref_words), " ".join(hyp_words))
    pairs = []
    for chunk in result.alignments[0]:
        if chunk.type == "equal":
            for offset in range(chunk.ref_end_idx - chunk.ref_start_idx):
                pairs.append((ref_speakers[chunk.ref_start_idx + offset], hyp_speakers[chunk.hyp_start_idx + offset]))
    overlap: dict[str, Counter[str]] = defaultdict(Counter)
    for ref, hyp in pairs:
        overlap[hyp][ref] += 1
    mapping = {hyp: counts.most_common(1)[0][0] for hyp, counts in overlap.items()}
    agree = sum(mapping[hyp] == ref for ref, hyp in pairs)
    return {
        "reference_words": len(ref_words),
        "local_words": len(hyp_words),
        "wer": round(result.wer, 4),
        "substitutions": result.substitutions,
        "deletions": result.deletions,
        "insertions": result.insertions,
        "aligned_words": len(pairs),
        "speaker_agreement": round(agree / len(pairs), 4) if pairs else "",
        "assemblyai_speakers": len(set(ref_speakers)),
        "local_speakers": len(set(hyp_speakers)),
        "local_to_assemblyai": "; ".join(f"{hyp}->{ref}" for hyp, ref in sorted(mapping.items())),
    }


def render_html(reference: dict[str, Any], local: dict[str, Any], row: dict[str, Any]) -> str:
    """AssemblyAI text in order, with words the local transcript missed, added or changed."""
    import jiwer

    ref_words, ref_speakers, ref_utt = tokens(reference, with_utterance=True)
    hyp_words, hyp_speakers = tokens(local)
    mapping = dict(item.split("->") for item in row["local_to_assemblyai"].split("; ") if item)
    result = jiwer.process_words(" ".join(ref_words), " ".join(hyp_words))
    pieces: list[tuple[int, str]] = []  # (reference utterance index, html)
    last = 0
    for chunk in result.alignments[0]:
        ref = range(chunk.ref_start_idx, chunk.ref_end_idx)
        hyp = range(chunk.hyp_start_idx, chunk.hyp_end_idx)
        if chunk.type == "equal":
            for r, h in zip(ref, hyp):
                word = html.escape(ref_words[r])
                if mapping.get(hyp_speakers[h]) != ref_speakers[r]:
                    word = f'<span class="spk" title="local speaker {hyp_speakers[h]}">{word}</span>'
                pieces.append((ref_utt[r], word))
                last = ref_utt[r]
        elif chunk.type == "delete":
            text = html.escape(" ".join(ref_words[r] for r in ref))
            pieces.append((ref_utt[ref.start], f'<del title="missing in local">{text}</del>'))
            last = ref_utt[ref.start]
        elif chunk.type == "insert":
            text = html.escape(" ".join(hyp_words[h] for h in hyp))
            pieces.append((last, f'<ins title="only in local">{text}</ins>'))
        else:
            old = html.escape(" ".join(ref_words[r] for r in ref))
            new = html.escape(" ".join(hyp_words[h] for h in hyp))
            pieces.append((ref_utt[ref.start], f'<del>{old}</del><ins>{new}</ins>'))
            last = ref_utt[ref.start]
    by_utterance: dict[int, list[str]] = defaultdict(list)
    for index, piece in pieces:
        by_utterance[index].append(piece)
    utterances = reference["utterances"]
    body = []
    for index in sorted(by_utterance):
        start = int(utterances[index].get("start") or 0) // 1000
        stamp = f"{start // 3600:02d}:{start % 3600 // 60:02d}:{start % 60:02d}"
        speaker = html.escape(str(utterances[index].get("speaker")))
        body.append(f'<p><span class="t">[{stamp}] {speaker}:</span> {" ".join(by_utterance[index])}</p>')
    title = html.escape(f"{row['show']} / {row['episode_id']}")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font:15px/1.55 -apple-system,sans-serif;max-width:900px;margin:2em auto;padding:0 16px}}
del{{background:#fde2e2;color:#a40000}} ins{{background:#dff5e1;color:#0a6b1d;text-decoration:none}}
.spk{{border-bottom:2px solid #e69500}} .t{{color:#666;font-weight:600}} .box{{background:#f4f4f4;padding:10px 14px;border-radius:6px}}</style>
</head><body><h1>{title}</h1><div class="box">
AssemblyAI text (reference) with the local Whisper + pyannote differences.
<del>red</del> = missing in local; <ins>green</ins> = only in local;
<span class="spk">orange underline</span> = local assigned a different speaker.<br>
Word error rate {row['wer']:.1%}; speaker agreement {row['speaker_agreement']:.1%};
speakers {row['local_speakers']} local vs {row['assemblyai_speakers']} AssemblyAI; mapping {html.escape(row['local_to_assemblyai'])}.
Words are lower-cased and stripped of punctuation for the comparison.</div>
{''.join(body)}</body></html>"""


def load(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, default=LOCAL,
                        help="folder with local transcripts (e.g. data/derived/transcripts_local_parakeet)")
    args = parser.parse_args()
    local_root = args.local_root if args.local_root.is_absolute() else ROOT / args.local_root
    output = OUTPUT.parent / local_root.name / OUTPUT.name if local_root != LOCAL else OUTPUT
    rows = []
    for local_path in sorted(local_root.glob("*/*/transcript.json.gz")):
        show, episode = local_path.parent.parent.name, local_path.parent.name
        reference_path = ASSEMBLYAI / show / episode / "transcript.json.gz"
        if not reference_path.is_file():
            continue
        job = json.loads((local_path.parent / "local_job.json").read_text(encoding="utf-8"))
        row = {"show": show, "episode_id": episode,
               "audio_minutes": round(job["audio_duration_seconds"] / 60, 1),
               **{f"speed_{k}": v for k, v in job.get("realtime_factor", {}).items()},
               **compare(load(reference_path), load(local_path))}
        rows.append(row)
        page = output.parent / f"{show}__{episode}.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(render_html(load(reference_path), load(local_path), row), encoding="utf-8")
        print(f"{show}/{episode}: WER {row['wer']:.1%}, speaker agreement "
              f"{row['speaker_agreement']:.1%} ({row['local_speakers']} local vs "
              f"{row['assemblyai_speakers']} AssemblyAI speakers)")
    if not rows:
        print("No episodes transcribed both ways yet.")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
