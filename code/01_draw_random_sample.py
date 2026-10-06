#!/usr/bin/env python3
"""Draw a reproducible random sample of episodes from a frozen episode list.

Episodes are stratified by publication year: the sample size is split across
years in proportion to each year's number of eligible episodes (largest
remainder), then episodes are drawn at random within each year with a fixed
seed. The result is a new frozen sample file in the format the transcription
runners read. Nothing is downloaded and nothing is overwritten.

    python code/01_draw_random_sample.py \\
        --source config/jre_full_archive_2026-09-15.json \\
        --start 2019-01-01 --end 2025-12-31 --n 10 --seed 20261003
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "config/samples"


def allocate(counts: dict[str, int], n: int) -> dict[str, int]:
    """Split n across strata in proportion to their sizes (largest remainder)."""
    total = sum(counts.values())
    if n > total:
        raise ValueError(f"Sample of {n} is larger than the {total} eligible episodes")
    exact = {key: n * size / total for key, size in counts.items()}
    shares = {key: int(value) for key, value in exact.items()}
    leftover = n - sum(shares.values())
    for key in sorted(exact, key=lambda k: (exact[k] - shares[k], k), reverse=True)[:leftover]:
        shares[key] += 1
    return shares


def eligible(episodes: list[dict[str, Any]], start: str, end: str, min_minutes: float) -> list[dict[str, Any]]:
    return [
        episode for episode in episodes
        if start <= episode["published_date"] <= end
        and float(episode.get("duration_seconds") or 0) >= min_minutes * 60
    ]


def draw(episodes: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        by_year[episode["published_date"][:4]].append(episode)
    shares = allocate({year: len(items) for year, items in by_year.items()}, n)
    rng = random.Random(seed)
    chosen = []
    for year in sorted(by_year):
        pool = sorted(by_year[year], key=lambda e: e["episode_id"])
        chosen += rng.sample(pool, shares[year])
    return sorted(chosen, key=lambda e: e["published_date"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="frozen sample/archive JSON with an episodes list")
    parser.add_argument("--start", required=True, help="first publication date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="last publication date, YYYY-MM-DD")
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--min-minutes", type=float, default=20.0)
    parser.add_argument("--exclude-sample", type=Path, action="append", default=[],
                        help="earlier sample file whose episodes may not be drawn again (repeatable)")
    args = parser.parse_args()

    source = args.source if args.source.is_absolute() else ROOT / args.source
    frame = json.loads(source.read_text(encoding="utf-8"))
    excluded: set[str] = set()
    for path in args.exclude_sample:
        earlier = json.loads((path if path.is_absolute() else ROOT / path).read_text(encoding="utf-8"))
        excluded |= {episode["episode_id"] for episode in earlier["episodes"]}
    pool = [e for e in eligible(frame["episodes"], args.start, args.end, args.min_minutes)
            if e["episode_id"] not in excluded]
    chosen = draw(pool, args.n, args.seed)
    sample_id = (f"{frame['show_id']}_random_{args.start[:4]}_{args.end[:4]}"
                 f"_n{args.n}_seed{args.seed}" + ("_extension" if excluded else ""))
    path = SAMPLES / f"{sample_id}.json"
    if path.exists():
        raise SystemExit(f"{path.relative_to(ROOT)} exists; a frozen sample is never overwritten")
    sample = {
        "schema_version": "0.2",
        "sample_id": sample_id,
        "show_id": frame["show_id"],
        "selected_at": datetime.now(timezone.utc).date().isoformat(),
        "selection_rule": (
            f"Random sample of {args.n} episodes published {args.start} to {args.end} with a declared "
            f"duration of at least {args.min_minutes:g} minutes, stratified by publication year "
            f"(proportional allocation, largest remainder), seed {args.seed}."
            + (f" Episodes in {', '.join(str(p) for p in args.exclude_sample)} were excluded." if excluded else "")
        ),
        "source": {"path": str(source.relative_to(ROOT)),
                   "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "eligible_episodes": len(pool)},
        "storage_strategy": "metadata_only_rss_direct_transcription",
        "episodes": [
            {key: episode[key] for key in ("episode_id", "rss_guid", "published_date", "guest_name", "duration_seconds")
             if key in episode}
            for episode in chosen
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(sample, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    hours = sum(float(e["duration_seconds"]) for e in chosen) / 3600
    print(f"{len(pool)} eligible episodes; drew {len(chosen)} ({hours:.1f} h) -> {path.relative_to(ROOT)}")
    for episode in chosen:
        print(f"  {episode['published_date']}  {float(episode['duration_seconds']) / 60:5.0f} min  "
              f"{episode['episode_id']}  {episode.get('guest_name', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
