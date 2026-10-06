#!/usr/bin/env python3
"""Flag whether each guest's episode is about health or science, from RSS text.

For every row of the guest dataset (18_build_guest_dataset.py), looks at the
episode title and full RSS description, removes sponsor/ad sentences, and
matches the term lists in config/rss_topic_terms.json. Free and local: no
network, no model. The label belongs to the episode; every guest of the
episode gets it. It reflects what the feed text says the episode covers, not
what is said in the audio.

    python code/19_flag_guest_topics.py            # latest guest dataset

Output, next to the guest dataset (data/derived/guest_dataset/<frame>/):
    episode_guests_topics.csv  episode_guests.csv plus health_related,
                               science_related, the matched words and the
                               cleaned text they were found in
    episode_topics.csv         one row per episode with the same labels
    topics_summary.md          shares per show
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import runpy
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GUEST_ROOT = ROOT / "data/derived/guest_dataset"
TERMS = ROOT / "config/rss_topic_terms.json"
GUESTS = runpy.run_path(str(ROOT / "code/18_build_guest_dataset.py"))
CLEAN_CHARS = 1500  # cleaned text kept per row for checking


def compile_terms(terms: list[str], prefixes: list[str]) -> re.Pattern[str]:
    words = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    stems = sorted((re.escape(p) for p in prefixes), key=len, reverse=True)
    parts = [rf"(?<![\w-])(?:{'|'.join(words)})(?![\w-])"]
    if stems:
        parts.append(rf"(?<![\w-])(?:{'|'.join(stems)})[\w-]*")
    return re.compile("|".join(parts), re.IGNORECASE)


def sentences(text: str) -> list[str]:
    """Split a description into sentences and bullet items."""
    pieces = re.split(r"(?<=[.!?])\s+|\s*[•|]\s*|\s+-{2,}\s*|\s+–\s+(?=[A-Z])", text)
    return [piece.strip() for piece in pieces if piece.strip()]


def sentence_key(sentence: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sentence.casefold())


def boilerplate(descriptions: list[str], min_count: int, min_share: float) -> set[str]:
    """Sentences repeated across a show's episodes: plugs, recurring ads, links."""
    counts = Counter()
    for text in descriptions:
        counts.update({sentence_key(piece) for piece in sentences(text)})
    threshold = max(min_count, min_share * len(descriptions))
    return {key for key, count in counts.items() if key and count >= threshold}


def content_sentences(text: str, ad_pattern: re.Pattern[str], repeated: set[str]) -> list[str]:
    return [piece for piece in sentences(text) if not ad_pattern.search(piece) and sentence_key(piece) not in repeated]


def guest_text(name: str, title: str, pieces: list[str]) -> str:
    """Title (if it names the guest) plus sentences naming the guest and the sentence after each."""
    tokens = [t for t in re.findall(r"[\w'-]+", name) if len(t) >= 3 and t.casefold() not in {"dr", "the", "jr"}]
    mentions = lambda text: any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, re.IGNORECASE) for t in tokens)
    keep = [part for part in re.split(r"\s\+\s|\s\|\s", title) if mentions(part)]
    for index, piece in enumerate(pieces):
        if mentions(piece):
            keep.extend(pieces[index:index + 2])
    return " ".join(dict.fromkeys(keep))


def matches(pattern: re.Pattern[str], text: str, ignore: set[str], exclude: re.Pattern[str] | None = None) -> list[str]:
    if exclude is not None:
        text = exclude.sub(" ", text)
    found = []
    for match in pattern.finditer(text):
        word = match.group(0).casefold()
        if word not in ignore and word not in found:
            found.append(word)
    return found


def latest_dataset() -> Path:
    folders = sorted(path.parent for path in GUEST_ROOT.glob("*/episode_guests.csv"))
    if not folders:
        raise SystemExit("No guest dataset; run 18_build_guest_dataset.py first")
    return folders[-1]


def main() -> int:
    dataset = latest_dataset()
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    config = json.loads(TERMS.read_text(encoding="utf-8"))
    health = compile_terms(config["health_terms"], config["health_prefixes"])
    science = compile_terms(config["science_terms"], config["science_prefixes"])
    ad_pattern = re.compile(config["ad_sentence_pattern"], re.IGNORECASE)
    ignore = {show: {t.casefold() for t in rule.get("health_terms", [])} for show, rule in config["show_ignore"].items()}
    rule = config["boilerplate_rule"]
    exclude = re.compile("|".join(re.escape(p) for p in config.get("exclude_phrases", [])), re.IGNORECASE)

    descriptions = {
        show_id: GUESTS["read_descriptions"](ROOT / feed["file"], show_id)
        for show_id, feed in manifest["feeds"].items()
    }
    with (dataset / "episodes.csv").open(newline="", encoding="utf-8") as handle:
        episodes = list(csv.DictReader(handle))

    repeated = {
        show_id: boilerplate(list(found.values()), rule["min_count"], rule["min_share"])
        for show_id, found in descriptions.items()
    }
    labels: dict[str, dict[str, Any]] = {}
    pieces_by_episode: dict[str, tuple[str, str, list[str]]] = {}
    episode_rows = []
    for episode in episodes:
        show_id = episode["show_id"]
        description = descriptions[show_id].get(episode["episode_id"], "")
        pieces = content_sentences(description, ad_pattern, repeated[show_id])
        pieces_by_episode[episode["episode_id"]] = (show_id, episode["title"], pieces)
        text = " ".join([f"{episode['title']}."] + pieces)
        health_words = matches(health, text, ignore.get(show_id, set()))
        science_words = matches(science, text, set(), exclude)
        label = {
            "health_related": int(bool(health_words)),
            "science_related": int(bool(science_words)),
            "health_or_science": int(bool(health_words or science_words)),
            "health_terms_found": "; ".join(health_words),
            "science_terms_found": "; ".join(science_words),
            "text_checked": text[:CLEAN_CHARS],
        }
        labels[episode["episode_id"]] = label
        episode_rows.append({
            "show": episode["show"], "show_id": show_id, "episode_id": episode["episode_id"],
            "published_date": episode["published_date"], "title": episode["title"],
            "guests": episode["guests"], **label,
        })

    with (dataset / "episode_guests.csv").open(newline="", encoding="utf-8") as handle:
        guest_rows = []
        for row in csv.DictReader(handle):
            show_id, title, pieces = pieces_by_episode[row["episode_id"]]
            text = guest_text(row["guest_name"], title, pieces)
            health_words = matches(health, text, ignore.get(show_id, set()))
            science_words = matches(science, text, set(), exclude)
            episode_label = {f"episode_{k}": v for k, v in labels[row["episode_id"]].items()}
            guest_rows.append({
                **row,
                "health_related": int(bool(health_words)),
                "science_related": int(bool(science_words)),
                "health_or_science": int(bool(health_words or science_words)),
                "health_terms_found": "; ".join(health_words),
                "science_terms_found": "; ".join(science_words),
                "guest_text_checked": text[:CLEAN_CHARS],
                **episode_label,
            })

    for name, rows in (("episode_guests_topics.csv", guest_rows), ("episode_topics.csv", episode_rows)):
        with (dataset / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    by_show: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in guest_rows:
        by_show[row["show"]].append(row)
    lines = [
        f"# Health / science flags for guest rows ({dataset.name})", "",
        f"Built {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `code/19_flag_guest_topics.py` with "
        f"`{TERMS.relative_to(ROOT)}` (sha256 {hashlib.sha256(TERMS.read_bytes()).hexdigest()[:12]}). Dictionary screen of "
        "the episode title and RSS description with ad and repeated sentences removed. "
        "Not validated.", "",
        f"- Guest rows: {len(guest_rows):,}; health {sum(r['health_related'] for r in guest_rows):,}; "
        f"science {sum(r['science_related'] for r in guest_rows):,}; either "
        f"{sum(r['health_or_science'] for r in guest_rows):,}.", "",
        "Guest-level columns use only text about the guest; `episode_*` columns use the whole episode text.", "",
        "| Show | Guest rows | Health (guest) | Science (guest) | Either (guest) | Either (episode) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for show, rows in sorted(by_show.items(), key=lambda item: item[0].casefold()):
        n = len(rows)
        share = lambda key: f"{sum(r[key] for r in rows) / n:.0%}"
        lines.append(f"| {show} | {n} | {share('health_related')} | {share('science_related')} | {share('health_or_science')} "
                     f"| {share('episode_health_or_science')} |")
    (dataset / "topics_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(guest_rows):,} guest rows, {len(episode_rows):,} episodes -> {dataset.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
