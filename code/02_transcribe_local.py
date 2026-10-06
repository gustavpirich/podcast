#!/usr/bin/env python3
"""Transcribe one episode locally and for free: Whisper or Parakeet (MLX) + pyannote diarization.

Alternative to 02_transcribe_assemblyai.py that runs on this Mac. Reads the
same immutable raw record (rss_metadata.json), downloads the public RSS audio
to a temporary system folder (deleted afterwards), transcribes it with
Whisper, separates speakers with pyannote, and writes the same transcript
schema the downstream classifiers read. Speakers keep generic diarization
labels (A, B, ...); host/guest roles are assigned in a later step.

    # plan only
    python code/02_transcribe_local.py --show-directory huberman_lab --episode-id <id>
    # run (needs HF_TOKEN with the pyannote community-1 conditions accepted)
    python code/02_transcribe_local.py --show-directory huberman_lab --episode-id <id> --yes

Output: <output root>/<show>/<episode>/transcript.json.gz, transcript.md,
        local_job.json (tool versions, settings, audio checksum, timings)
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import importlib.metadata
import json
import os
import platform
import runpy
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_TRANSCRIPTS = ROOT / "data/raw/transcripts"
DEFAULT_OUTPUT = ROOT / "data/derived/transcripts_local"
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"  # English-only NVIDIA Parakeet TDT
# Long episodes are decoded in overlapping chunks to bound memory use.
PARAKEET_OPTIONS = {"chunk_duration": 120.0, "overlap_duration": 15.0}
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
SAMPLE_RATE = 16000
USER_AGENT = "podcast-observational-research/0.1"
# Whisper settings chosen to limit repetition loops and invented text in silence.
WHISPER_OPTIONS = {
    "language": "en",
    "word_timestamps": True,
    "condition_on_previous_text": False,
    "hallucination_silence_threshold": 2.0,
}
FORMAT = runpy.run_path(str(ROOT / "code/02_transcribe_assemblyai.py"))


def shown(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def versions() -> dict[str, str]:
    found = {"python": platform.python_version(), "platform": platform.platform()}
    for package in ("mlx-whisper", "parakeet-mlx", "mlx", "pyannote.audio", "torch"):
        try:
            found[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            found[package] = "not installed"
    return found


def download(url: str, path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response, path.open("wb") as handle:
        while chunk := response.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
            handle.write(chunk)
    return digest.hexdigest(), size


def to_wav(source: Path, target: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(source),
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(target)],
        check=True,
    )


def whisper_words(wav: Path, model: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import mlx_whisper

    result = mlx_whisper.transcribe(str(wav), path_or_hf_repo=model, **WHISPER_OPTIONS)
    words = []
    for segment in result["segments"]:
        for word in segment.get("words", []):
            text = word["word"].strip()
            if text:
                words.append({
                    "text": text,
                    "start": int(round(word["start"] * 1000)),
                    "end": int(round(word["end"] * 1000)),
                    "confidence": float(word.get("probability", 0.0)),
                })
    return words, {"language": result.get("language"), "segments": len(result["segments"])}


def parakeet_words(wav: Path, model: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Words from Parakeet's sub-word tokens; a token starting with a space begins a word."""
    from parakeet_mlx import from_pretrained

    result = from_pretrained(model).transcribe(str(wav), **PARAKEET_OPTIONS)
    words: list[dict[str, Any]] = []
    current: list[Any] = []

    def flush() -> None:
        text = "".join(token.text for token in current).strip()
        if text:
            words.append({
                "text": text,
                "start": int(round(current[0].start * 1000)),
                "end": int(round(current[-1].end * 1000)),
                "confidence": float(min(token.confidence for token in current)),
            })

    for token in result.tokens:
        if current and token.text.startswith(" "):
            flush()
            current = []
        current.append(token)
    if current:
        flush()
    return words, {"language": "en", "segments": len(result.sentences)}


def diarize(wav: Path, min_speakers: int, max_speakers: int) -> list[tuple[int, int, str]]:
    """Exclusive (one speaker at a time) turns as (start_ms, end_ms, label)."""
    import numpy as np
    import torch
    from pyannote.audio import Pipeline
    from scipy.io import wavfile

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit("HF_TOKEN is not set; accept the pyannote community-1 conditions and set it")
    pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=token)
    if torch.backends.mps.is_available():
        pipeline.to(torch.device("mps"))
    rate, samples = wavfile.read(wav)
    waveform = torch.from_numpy(samples.astype(np.float32) / 32768.0).unsqueeze(0)
    output = pipeline({"waveform": waveform, "sample_rate": rate},
                      min_speakers=min_speakers, max_speakers=max_speakers)
    return [
        (int(turn.start * 1000), int(turn.end * 1000), str(speaker))
        for turn, _, speaker in output.exclusive_speaker_diarization.itertracks(yield_label=True)
    ]


def assign_speakers(words: list[dict[str, Any]], turns: list[tuple[int, int, str]]) -> None:
    """Give each word the speaker whose turn contains its midpoint (else the nearest turn)."""
    turns = sorted(turns)
    starts = [start for start, _, _ in turns]
    for word in words:
        middle = (word["start"] + word["end"]) // 2
        index = bisect.bisect_right(starts, middle) - 1
        candidates = [i for i in (index, index + 1) if 0 <= i < len(turns)]
        if not candidates:
            word["speaker"] = "UNKNOWN"
            continue

        def distance(i: int) -> int:
            start, end, _ = turns[i]
            return 0 if start <= middle <= end else min(abs(middle - start), abs(middle - end))

        word["speaker"] = turns[min(candidates, key=distance)][2]


GUEST_SEPARATORS = (" | ", " - ", " – ", " — ")


def title_guests(title: str) -> list[str] | None:
    """Guest names from an episode title, or None when the title does not clearly name people.

    Handles "#1858 - Josh Dubin & Derrick Hamilton", "JRE MMA Show #65 with Corey Anderson"
    and "Topic ... | Dr Andy Galpin". Names are split on '&', ' and ' and commas.
    """
    import re

    part = None
    match = re.search(r"\bwith\s+(.+)$", title)
    if re.match(r"^(#\s*\d+|JRE MMA Show)", title) and match:
        part = match.group(1)
    for separator in GUEST_SEPARATORS:
        if part is None and separator in title:
            part = title.rsplit(separator, 1)[1]
    if not part:
        return None
    names = [n.strip() for n in re.split(r"\s*&\s*|\s+and\s+|\s*,\s*", part) if n.strip()]
    if not names or len(names) > 5 or any(re.search(r"\d", n) or len(n.split()) > 5 for n in names):
        return None
    return names


def speaker_bounds(metadata: dict[str, Any], mode: str) -> tuple[int, int, str]:
    """(min, max, how) for pyannote: exact hosts+guests from the RSS title, else the 2-to-max range."""
    upper = int(metadata.get("podcast", {}).get("max_speakers_expected") or 4)
    expected = expected_speakers(metadata) if mode == "title" else None
    if expected:
        return expected, expected, "title_exact"
    return 2, upper, "range" if mode == "range" else "range_title_unparsed"


def expected_speakers(metadata: dict[str, Any]) -> int | None:
    """Hosts plus guests named in the RSS title; None when the title does not name guests."""
    guests = title_guests(str(metadata.get("episode", {}).get("title") or ""))
    hosts = metadata.get("podcast", {}).get("hosts") or []
    return len(hosts) + len(guests) if guests and hosts else None


SPEAKER_ASSIGNMENT = "sentence_majority_v1"
# A sentence keeps word-level speakers only when a second speaker covers at least
# this share of a sentence of at least this many words (a genuine interruption).
SPLIT_SHARE = 0.35
SPLIT_MIN_WORDS = 8
SENTENCE_END = (".", "?", "!", "…")


def sentence_groups(words: list[dict[str, Any]]) -> list[list[int]]:
    """Indices of words per sentence; a sentence ends at a word ending in . ? ! or …"""
    groups: list[list[int]] = [[]]
    for index, word in enumerate(words):
        groups[-1].append(index)
        if word["text"].rstrip("\"')").endswith(SENTENCE_END):
            groups.append([])
    return [group for group in groups if group]


def overlap_by_speaker(start: int, end: int, turns: list[tuple[int, int, str]]) -> dict[str, int]:
    shares: dict[str, int] = {}
    for turn_start, turn_end, speaker in turns:
        if turn_end <= start:
            continue
        if turn_start >= end:
            break
        shares[speaker] = shares.get(speaker, 0) + min(end, turn_end) - max(start, turn_start)
    return shares


def assign_by_sentence(words: list[dict[str, Any]], turns: list[tuple[int, int, str]]) -> dict[str, int]:
    """Give every word of a sentence the speaker who covers most of the sentence's time.

    Falls back to word-level assignment for sentences without any overlapping
    turn and for long sentences where a second speaker clearly takes part.
    Returns counts of how sentences were assigned.
    """
    turns = sorted(turns)
    assign_speakers(words, turns)  # word-level result, used as the fallback
    counts = {"sentence": 0, "word_level_interruption": 0, "word_level_no_overlap": 0}
    for group in sentence_groups(words):
        start, end = words[group[0]]["start"], words[group[-1]]["end"]
        shares = overlap_by_speaker(start, max(end, start + 1), turns)
        if not shares:
            counts["word_level_no_overlap"] += 1
            continue
        ranked = sorted(shares.items(), key=lambda item: -item[1])
        total = sum(shares.values())
        if len(ranked) > 1 and len(group) >= SPLIT_MIN_WORDS and ranked[1][1] / total >= SPLIT_SHARE:
            counts["word_level_interruption"] += 1
            continue
        for index in group:
            words[index]["speaker"] = ranked[0][0]
        counts["sentence"] += 1
    return counts


def relabel(words: list[dict[str, Any]]) -> list[str]:
    """Rename pyannote labels to A, B, C ... in order of first appearance."""
    order: dict[str, str] = {}
    for word in words:
        if word["speaker"] not in order:
            order[word["speaker"]] = chr(ord("A") + len(order)) if len(order) < 26 else f"S{len(order)}"
        word["speaker"] = order[word["speaker"]]
    return list(order.values())


def utterances(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    for word in words:
        if grouped and grouped[-1]["speaker"] == word["speaker"]:
            grouped[-1]["words"].append(word)
        else:
            grouped.append({"speaker": word["speaker"], "words": [word]})
    for item in grouped:
        item["text"] = " ".join(word["text"] for word in item["words"])
        item["start"] = item["words"][0]["start"]
        item["end"] = item["words"][-1]["end"]
        item["confidence"] = sum(word["confidence"] for word in item["words"]) / len(item["words"])
    return [{key: item[key] for key in ("speaker", "text", "confidence", "start", "end", "words")}
            for item in grouped]


def markdown(document: dict[str, Any]) -> str:
    episode, info = document["episode"], document["transcription"]
    stamp = FORMAT["format_timestamp"]
    quote = FORMAT["yaml_string"]
    lines = [
        "---",
        f"title: {quote(episode.get('title'))}",
        f"podcast: {quote(episode.get('podcast'))}",
        f"date: {quote((episode.get('published_at') or '')[:10])}",
        f"duration: {quote(stamp((info.get('audio_duration_seconds') or 0) * 1000))}",
        f"source_url: {quote(episode.get('source_url'))}",
        "transcription:",
        '  provider: "local"',
        f"  asr_model: {quote(info['asr_model'])}",
        f"  diarization_model: {quote(info['diarization_model'])}",
        "  speaker_identities_human_verified: false",
        "speakers:",
    ]
    for speaker in document["speakers"]:
        lines += [f"  - id: {quote(speaker['id'])}", f"    name: {quote(speaker['name'])}",
                  f"    role: {quote(speaker['role'])}"]
    lines += ["---", "", f"# {episode.get('title') or 'Podcast transcript'}", "", "## Transcript", ""]
    for item in document["utterances"]:
        lines += [f"**[{stamp(item['start'])}] {item['speaker']}:** {item['text']}", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_gzip_json(path: Path, value: Any) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False)


def build_document(metadata: dict[str, Any], url: str, audio_sha256: str, asr_model: str,
                   asr_options: dict[str, Any], diarization_model: str, language: str | None,
                   duration_s: float, words: list[dict[str, Any]], labels: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "generated_at": utc_now(),
        "episode": {
            "title": metadata["episode"].get("title"),
            "podcast": metadata.get("podcast", {}).get("name"),
            "published_at": metadata["episode"].get("published_at"),
            "episode_id": metadata.get("episode_id"),
            "rss_guid": metadata["episode"].get("guid"),
            "source_url": url,
            "audio_sha256": audio_sha256,
        },
        "transcription": {
            "provider": "local",
            "asr_model": asr_model,
            "asr_options": asr_options,
            "diarization_model": diarization_model,
            "speaker_assignment": SPEAKER_ASSIGNMENT,
            "language_code": language,
            "audio_duration_seconds": round(duration_s, 3),
            "speaker_identification_status": "not_run",
            "speaker_identities_human_verified": False,
        },
        "speakers": [{"id": label, "name": label, "role": "Unidentified"} for label in labels],
        "utterances": utterances(words),
    }


def fetch_audio(url: str, temp: Path, timings: dict[str, float]) -> tuple[Path, str, int, float]:
    source, wav = temp / "audio", temp / "audio.wav"
    began = time.monotonic()
    audio_sha256, audio_bytes = download(url, source)
    timings["download_s"] = time.monotonic() - began
    began = time.monotonic()
    to_wav(source, wav)
    timings["convert_s"] = time.monotonic() - began
    return wav, audio_sha256, audio_bytes, (wav.stat().st_size - 44) / (2 * SAMPLE_RATE)


def save_turns(path: Path, turns: list[tuple[int, int, str]], audio_sha256: str,
               bounds: tuple[int, int, str]) -> None:
    write_gzip_json(path, {"model": DIARIZATION_MODEL, "audio_sha256": audio_sha256,
                           "min_speakers": bounds[0], "max_speakers": bounds[1], "speaker_count": bounds[2],
                           "created_at": utc_now(), "turns": [list(turn) for turn in turns]})


def reassign(output: Path, metadata: dict[str, Any], url: str, bounds: tuple[int, int, str],
             rediarize: bool = False) -> int:
    """Redo only the speaker assignment of an existing transcript (text is kept)."""
    with gzip.open(output / "transcript.json.gz", "rt", encoding="utf-8") as handle:
        document = json.load(handle)
    words = [{key: value for key, value in word.items() if key != "speaker"}
             for utterance in document["utterances"] for word in utterance["words"]]
    job_path = output / "local_job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    turns_path = output / "diarization.json.gz"
    timings: dict[str, float] = {}
    if turns_path.exists() and not rediarize:
        with gzip.open(turns_path, "rt", encoding="utf-8") as handle:
            saved = json.load(handle)
        turns = [tuple(turn) for turn in saved["turns"]]
    else:
        with tempfile.TemporaryDirectory(prefix="podcast_local_") as temp:
            wav, audio_sha256, _, _ = fetch_audio(url, Path(temp), timings)
            began = time.monotonic()
            turns = diarize(wav, bounds[0], bounds[1])
            timings["diarization_s"] = time.monotonic() - began
        if audio_sha256 != document["episode"].get("audio_sha256"):
            print("  note: re-downloaded audio differs from the transcribed audio (e.g. different inserted ads)")
        save_turns(turns_path, turns, audio_sha256, bounds)
    counts = assign_by_sentence(words, turns)
    labels = relabel(words)
    document["speakers"] = [{"id": label, "name": label, "role": "Unidentified"} for label in labels]
    document["utterances"] = utterances(words)
    document["transcription"]["speaker_assignment"] = SPEAKER_ASSIGNMENT
    document["transcription"]["speaker_identification_status"] = "not_run"
    document["generated_at"] = utc_now()
    write_gzip_json(output / "transcript.json.gz", document)
    (output / "transcript.md").write_text(markdown(document), encoding="utf-8")
    stale = [name for name in ("speaker_roles.json", "transcript_annotated.json.gz", "transcript_annotated.md")
             if (output / name).exists()]
    for name in stale:  # GPT names refer to the old labels; 03_label_speakers_gpt.py recreates them
        (output / name).unlink()
    job.setdefault("reassignments", []).append({
        "at": utc_now(), "method": SPEAKER_ASSIGNMENT, "sentence_counts": counts,
        "speaker_bounds": list(bounds) if (rediarize or not job.get("reassignments")) else "from saved diarization",
        "timings_seconds": {k: round(v, 1) for k, v in timings.items()}, "removed_stale": stale,
    })
    job["speakers"] = len(labels)
    job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    print(f"Reassigned {shown(output)} by sentence: {counts}; {len(labels)} speakers; removed {stale or 'nothing'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show-directory", required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--asr", choices=("whisper", "parakeet"), default="whisper",
                        help="speech-to-text engine (both run locally via MLX)")
    parser.add_argument("--asr-model", help=f"default: {WHISPER_MODEL} or {PARAKEET_MODEL}")
    parser.add_argument("--skip-diarization", action="store_true",
                        help="transcribe only (all words get speaker A); for speed tests without HF_TOKEN")
    parser.add_argument("--reassign", action="store_true",
                        help="keep the existing text; redo speaker assignment by sentence "
                             "(re-runs diarization only if diarization.json.gz is missing)")
    parser.add_argument("--speaker-count", choices=("title", "range"), default="title",
                        help="title: exactly hosts + guests named in the RSS title (fallback: range); "
                             "range: 2 to max_speakers_expected")
    parser.add_argument("--rediarize", action="store_true",
                        help="with --reassign: run pyannote again even if diarization.json.gz exists")
    parser.add_argument("--yes", action="store_true", help="download the audio and run (free, local)")
    args = parser.parse_args()

    asr_model = args.asr_model or (WHISPER_MODEL if args.asr == "whisper" else PARAKEET_MODEL)
    asr_options = WHISPER_OPTIONS if args.asr == "whisper" else PARAKEET_OPTIONS
    metadata_path = RAW_TRANSCRIPTS / args.show_directory / args.episode_id / "rss_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    url = metadata["episode"]["enclosure_url"]
    max_speakers = int(metadata.get("podcast", {}).get("max_speakers_expected") or 4)
    bounds = speaker_bounds(metadata, args.speaker_count)
    output = (args.output_root if args.output_root.is_absolute() else ROOT / args.output_root)
    output = output / args.show_directory / args.episode_id
    print(f"Local transcription plan for {args.show_directory}/{args.episode_id}")
    print(f"  Title:        {metadata['episode']['title']}")
    if args.reassign:
        print(f"  Mode:         reassign speakers by sentence (text unchanged)")
    else:
        print(f"  Audio:        RSS enclosure, downloaded to a temporary folder and deleted")
        print(f"  ASR:          {asr_model} {asr_options}")
    print(f"  Diarization:  {'skipped' if args.skip_diarization else DIARIZATION_MODEL} "
          f"({bounds[0]} to {bounds[1]} speakers; {bounds[2]})")
    print(f"  Assignment:   {SPEAKER_ASSIGNMENT}")
    print(f"  Output:       {shown(output)}")
    if not args.yes:
        print("Plan only. Add --yes to run (no fees; uses this computer).")
        return 0
    if args.reassign:
        if not (output / "transcript.json.gz").exists():
            raise SystemExit(f"{shown(output)} has no transcript to reassign")
        return reassign(output, metadata, url, bounds, args.rediarize)
    if (output / "transcript.json.gz").exists():
        raise SystemExit(f"{shown(output)} already has a transcript; refusing to overwrite")

    timings: dict[str, float] = {}
    with tempfile.TemporaryDirectory(prefix="podcast_local_") as temp:
        wav, audio_sha256, audio_bytes, duration_s = fetch_audio(url, Path(temp), timings)
        began = time.monotonic()
        transcribe = whisper_words if args.asr == "whisper" else parakeet_words
        words, asr_info = transcribe(wav, asr_model)
        timings["asr_s"] = time.monotonic() - began
        if args.skip_diarization:
            turns = [(0, int(duration_s * 1000) + 1, "SPEAKER_00")]
        else:
            began = time.monotonic()
            turns = diarize(wav, bounds[0], bounds[1])
            timings["diarization_s"] = time.monotonic() - began
    output.mkdir(parents=True, exist_ok=True)
    if not args.skip_diarization:
        save_turns(output / "diarization.json.gz", turns, audio_sha256, bounds)
    counts = assign_by_sentence(words, turns)
    labels = relabel(words)
    document = build_document(metadata, url, audio_sha256, asr_model, asr_options,
                              "not_run" if args.skip_diarization else DIARIZATION_MODEL,
                              asr_info["language"], duration_s, words, labels)
    write_gzip_json(output / "transcript.json.gz", document)
    (output / "transcript.md").write_text(markdown(document), encoding="utf-8")
    job = {
        "created_at": utc_now(), "raw_metadata": str(metadata_path.relative_to(ROOT)),
        "audio_url": url, "audio_sha256": audio_sha256, "audio_bytes": audio_bytes,
        "audio_retained": False, "audio_duration_seconds": round(duration_s, 3),
        "versions": versions(), "timings_seconds": {k: round(v, 1) for k, v in timings.items()},
        "realtime_factor": {k: round(duration_s / v, 1) for k, v in timings.items() if k in ("asr_s", "diarization_s") and v},
        "words": len(words), "speakers": len(labels), "max_speakers_expected": max_speakers,
        "speaker_assignment": SPEAKER_ASSIGNMENT, "sentence_counts": counts,
        "speaker_bounds": list(bounds),
    }
    (output / "local_job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {shown(output)}: {len(words):,} words, {len(labels)} speakers ({counts})")
    print(f"Timings: {job['timings_seconds']}  speed (x real time): {job['realtime_factor']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
