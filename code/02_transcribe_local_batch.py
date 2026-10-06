#!/usr/bin/env python3
"""Transcribe every episode of a frozen sample locally (free), resumably.

Runs 02_transcribe_local.py once per episode, in sample order, skipping
episodes whose transcript already exists, continuing after a failure, and
keeping the Mac awake (macOS `caffeinate`) while it runs. Re-run the same
command to resume.

    python code/02_transcribe_local_batch.py --sample config/samples/<id>.json            # plan
    python code/02_transcribe_local_batch.py --sample config/samples/<id>.json --yes      # run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PODCASTS = ROOT / "config/podcasts.json"
SINGLE = ROOT / "code/02_transcribe_local.py"
DEFAULT_OUTPUT = "data/derived/transcripts_local_parakeet"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--asr", choices=("whisper", "parakeet"), default="parakeet")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT)
    parser.add_argument("--max-episodes", type=int, help="stop after this many new transcripts")
    parser.add_argument("--reassign", action="store_true",
                        help="redo speaker assignment by sentence for episodes that already have a transcript")
    parser.add_argument("--rediarize", action="store_true", help="with --reassign: run pyannote again")
    parser.add_argument("--speaker-count", choices=("title", "range"), default="title")
    parser.add_argument("--retries", type=int, default=3, help="attempts per episode (1 min apart)")
    parser.add_argument("--yes", action="store_true", help="run (free; uses this computer)")
    args = parser.parse_args()

    sample_path = args.sample if args.sample.is_absolute() else ROOT / args.sample
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    show_directory = json.loads(PODCASTS.read_text(encoding="utf-8"))["podcasts"][sample["show_id"]]["raw_directory"]
    output_root = ROOT / args.output_root
    episodes = sample["episodes"]
    done = [e for e in episodes if (output_root / show_directory / e["episode_id"] / "transcript.json.gz").exists()]
    todo = (done if args.reassign else [e for e in episodes if e not in done])[: args.max_episodes]
    hours = sum(float(e.get("duration_seconds") or 0) for e in todo) / 3600
    print(f"Sample {sample['sample_id']}: {len(episodes)} episodes, {len(done)} done, {len(todo)} to run ({hours:.1f} h of audio)")
    print(f"  Engine: {args.asr} + pyannote; output {args.output_root}/{show_directory}/")
    print(f"  Rough time at ~13x real time: {hours / 13:.1f} h")
    if not args.yes:
        print("Plan only. Add --yes to run.")
        return 0

    if shutil.which("caffeinate"):  # keep the Mac awake while this process lives
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    failures = []
    consecutive = pauses = 0
    for number, episode in enumerate(todo, start=1):
        began = time.monotonic()
        print(f"\n[{number}/{len(todo)}] {episode['episode_id']} ({episode.get('published_date')}, "
              f"{float(episode.get('duration_seconds') or 0) / 60:.0f} min)", flush=True)
        command = [
            sys.executable, str(SINGLE), "--show-directory", show_directory, "--episode-id", episode["episode_id"],
            "--asr", args.asr, "--output-root", args.output_root, "--yes",
            "--speaker-count", args.speaker_count,
            *(["--reassign"] if args.reassign else []), *(["--rediarize"] if args.rediarize else []),
        ]
        for attempt in range(1, args.retries + 1):
            result = subprocess.run(command, capture_output=True, text=True)
            print("\n".join(line for line in result.stdout.splitlines()
                            if line.startswith(("Wrote", "Timings", "Reassigned", "  note"))), flush=True)
            if result.returncode == 0:
                break
            tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-8:])
            print(f"  attempt {attempt} failed (exit {result.returncode}):\n{tail}", flush=True)
            if attempt < args.retries:
                time.sleep(60)
        status = "ok" if result.returncode == 0 else f"failed (exit {result.returncode})"
        print(f"  -> {status} in {(time.monotonic() - began) / 60:.1f} min", flush=True)
        if result.returncode == 0:
            consecutive = 0
            continue
        failures.append(episode["episode_id"])
        consecutive += 1
        if consecutive >= 3:  # likely a network or system problem, not the episode
            pauses += 1
            if pauses > 3:
                print("  Too many consecutive failures; stopping. Re-run the same command to resume.", flush=True)
                break
            print(f"  {consecutive} failures in a row; pausing 10 min (pause {pauses}/3)", flush=True)
            time.sleep(600)
            consecutive = 0
    print(f"\nFinished: {len(todo) - len(failures)}/{len(todo)} ok; failures: {failures or 'none'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
