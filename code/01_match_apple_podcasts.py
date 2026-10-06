#!/usr/bin/env python3
"""Propose an Apple Podcasts match (and RSS feed) for every Edison Top-50 show.

Reads the raw Apple search snapshots (a later snapshot replaces earlier results
for the shows it contains) and, for each show, ranks the
returned podcasts by how well their title matches any printed Edison name for
that show. Exact matches (after normalizing case, punctuation, '&'/'and' and a
leading 'The') are marked `exact`; everything else is marked `review` and must
be checked by a person before use. No network access.

Output: data/derived/popularity/apple_matches.csv (one row per show)
"""

from __future__ import annotations

import csv
import difflib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ALIASES = ROOT / "config/edison_show_aliases.csv"
TRANSCRIBED = ROOT / "config/edison_top50_transcribed.csv"
SEARCH_ROOT = ROOT / "data/raw/popularity/apple_search"
OUTPUT = ROOT / "data/derived/popularity/apple_matches.csv"


def normalize(name: str) -> str:
    text = name.casefold().replace("&", " and ").replace("w/", "with ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^the ", "", text)


def rank_candidates(printed_names: list[str], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score each Apple result against all printed names for the show."""
    targets = {normalize(name) for name in printed_names}
    ranked = []
    for result in results:
        title = normalize(result.get("collectionName", ""))
        if title in targets:
            kind, score = "exact", 1.0
        else:
            score = max(difflib.SequenceMatcher(None, title, target).ratio() for target in targets)
            kind = "review"
        ranked.append({**result, "match": kind, "similarity": round(score, 3)})
    # Exact first, then most similar, then the larger catalog (Apple's trackCount).
    ranked.sort(key=lambda r: (r["match"] == "exact", r["similarity"], r.get("trackCount", 0)), reverse=True)
    return ranked


def main() -> int:
    snapshots = sorted(path for path in SEARCH_ROOT.glob("*/manifest.json"))
    if not snapshots:
        raise SystemExit("No Apple search snapshot; run 01_lookup_apple_podcasts.py --yes first")
    latest: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in snapshots:  # oldest first, so later snapshots win
        for record in json.loads(path.read_text(encoding="utf-8"))["shows"]:
            latest[record["show"]] = (record, path.parent)

    printed: dict[str, list[str]] = defaultdict(list)
    with ALIASES.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            printed[row["canonical_show"]].append(row["printed_name"])
    producers: dict[str, set[str]] = defaultdict(set)
    releases: dict[str, set[str]] = defaultdict(set)
    alias = {name: canon for canon, names in printed.items() for name in names}
    with TRANSCRIBED.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            producers[alias[row["show"]]].add(row["publisher"])
            releases[alias[row["show"]]].add(row["release"])

    rows = []
    for show in sorted(latest, key=str.casefold):
        record, snapshot = latest[show]
        results = []
        if record["status"] == "ok":
            results = json.loads((snapshot / record["file"]).read_text(encoding="utf-8"))["results"]
        ranked = rank_candidates(printed[show], results)
        best = ranked[0] if ranked else {}
        runner = ranked[1] if len(ranked) > 1 else {}
        rows.append({
            "show": show,
            "edison_releases": len(releases[show]),
            "edison_producers": " / ".join(sorted(producers[show])),
            "match": best.get("match", "no_result"),
            "similarity": best.get("similarity", ""),
            "apple_collection_id": best.get("collectionId", ""),
            "apple_title": best.get("collectionName", ""),
            "apple_artist": best.get("artistName", ""),
            "apple_primary_genre": best.get("primaryGenreName", ""),
            "apple_genres": " | ".join(best.get("genres", [])),
            "apple_episode_count": best.get("trackCount", ""),
            "apple_latest_release": str(best.get("releaseDate", ""))[:10],
            "feed_url": best.get("feedUrl", ""),
            "runner_up_title": runner.get("collectionName", ""),
            "runner_up_artist": runner.get("artistName", ""),
            "runner_up_collection_id": runner.get("collectionId", ""),
            "search_snapshot": snapshot.name,
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = defaultdict(int)
    for row in rows:
        counts[row["match"]] += 1
    print(f"{len(rows)} shows: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
