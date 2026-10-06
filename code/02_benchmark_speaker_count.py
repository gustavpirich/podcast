#!/usr/bin/env python3
"""Does telling pyannote the expected number of speakers improve diarization?

For episodes that have both a local transcript and an AssemblyAI transcript,
downloads the audio once, runs pyannote with several speaker-count settings,
assigns the existing local words by sentence, and measures speaker agreement
with AssemblyAI (each local label mapped to the AssemblyAI speaker it shares
most words with). The expected count comes from the RSS title: hosts plus the
guests named in it. Free; uses this computer. Writes a CSV to output/.

    python code/02_benchmark_speaker_count.py --episode-id jre-2520-16b0c9ec7c39 --episode-id ...
"""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import json
import runpy
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL = runpy.run_path(str(ROOT / "code/02_transcribe_local.py"))
COMPARE = runpy.run_path(str(ROOT / "code/02_compare_local_transcripts.py"))
SHOW_DIRECTORY = "the_joe_rogan_experience"
LOCAL_ROOT = ROOT / "data/derived/transcripts_local_parakeet" / SHOW_DIRECTORY
REFERENCE_ROOT = ROOT / "data/derived/transcripts" / SHOW_DIRECTORY
OUTPUT = ROOT / "output/local_vs_assemblyai/speaker_count_benchmark.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode-id", action="append", required=True)
    args = parser.parse_args()
    rows = []
    for episode_id in args.episode_id:
        metadata = json.loads((ROOT / "data/raw/transcripts" / SHOW_DIRECTORY / episode_id / "rss_metadata.json")
                              .read_text(encoding="utf-8"))
        expected = LOCAL["expected_speakers"](metadata)
        settings = {"A_current_2_to_4": (2, 4), "B_exact": (expected, expected), "C_exact_plus_1": (expected, expected + 1)}
        reference = COMPARE["load"](REFERENCE_ROOT / episode_id / "transcript.json.gz")
        document = COMPARE["load"](LOCAL_ROOT / episode_id / "transcript.json.gz")
        words = [{k: v for k, v in w.items() if k != "speaker"} for u in document["utterances"] for w in u["words"]]
        print(f"{episode_id}: {metadata['episode']['title']!r} -> expected {expected} speakers")
        with tempfile.TemporaryDirectory(prefix="podcast_bench_") as temp:
            wav, _, _, _ = LOCAL["fetch_audio"](metadata["episode"]["enclosure_url"], Path(temp), {})
            for name, (low, high) in settings.items():
                began = time.monotonic()
                turns = LOCAL["diarize"](wav, low, high)
                seconds = time.monotonic() - began
                assigned = copy.deepcopy(words)
                LOCAL["assign_by_sentence"](assigned, turns)
                labels = LOCAL["relabel"](assigned)
                result = COMPARE["compare"](reference, {"utterances": LOCAL["utterances"](assigned)})
                rows.append({"episode_id": episode_id, "setting": name, "min_speakers": low, "max_speakers": high,
                             "speakers_found": len(labels), "speaker_agreement": result["speaker_agreement"],
                             "diarization_seconds": round(seconds, 1), "mapping": result["local_to_assemblyai"]})
                print(f"   {name:18} speakers found {len(labels)}, agreement {result['speaker_agreement']:.1%} "
                      f"({seconds:.0f}s) {result['local_to_assemblyai']}", flush=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
