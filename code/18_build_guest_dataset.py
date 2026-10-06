#!/usr/bin/env python3
"""Build the episode/guest dataset for the popular-podcast frame from RSS text.

For every episode in the popular frame (01_build_popular_episode_frame.py),
reads the episode title and description from the frozen RSS file and applies
the rules in config/guest_rules.json to list the guests. Free and local: no
network access, no model, no API. Researcher decision 2026-10-03 (notes/PLAN.md).

    python code/18_build_guest_dataset.py                 # latest frame
    python code/18_build_guest_dataset.py --frame data/derived/popular_frame/20261003T092332Z

Output: data/derived/guest_dataset/<frame snapshot>/
    episodes.csv        one row per episode, guests in one column ("; "-separated)
    episode_guests.csv  one row per episode-guest pair, with the rule and the
                        title/description text the name was taken from
    shows.csv           one row per show, with its Edison ranking history
    summary.md          counts per show and year
    manifest.json       inputs, hashes and settings
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FRAME_ROOT = ROOT / "data/derived/popular_frame"
RULES = ROOT / "config/guest_rules.json"
PODCASTS = ROOT / "config/podcasts.json"
FEEDS = ROOT / "config/popular_show_feeds.csv"
ALIASES = ROOT / "config/edison_show_aliases.csv"
EDISON = ROOT / "config/edison_top50_transcribed.csv"
OUTPUT_ROOT = ROOT / "data/derived/guest_dataset"
DESCRIPTION_CHARS = 2000  # description text kept in episodes.csv for checking

# Words that never occur in a guest name as printed in these feeds; a candidate
# containing one is a topic phrase ("Storming Area 51"), not a person.
STOP_WORDS = set("""
the a an my our your his her their its how why what when where who whom is are was were be been we i it
this that these those best live part pt episode ep eps bonus special essentials guest guests series q&a
new last looks first second drink friday chit chat anonymous classics podcast podcasts show replay pilot
intro trailer recap mailbag listener listeners calls news update you me us do does did not no yes all
about on in at for from with to of or and vs vs. after dark leftovers h3tv ama year years day days night
week weekend morning afternoon monday tuesday wednesday thursday saturday sunday holiday christmas
halloween happy merry ranking reacting react reacts reaction nelk boys ufc wwe nfl nba patreon youtube
netflix spotify instagram tiktok twitter apple office ladies uncensored interview returns return again
edition compilation highlights tour family wedding birthday anniversary game games challenge prank story
stories murder murders trap boycott big squad crew gang everyone everybody experts expert sync synced
older people dropouts rotten tomatoes good sports trending topics game
""".split())
TITLE_PREFIXES = re.compile(
    r"^(?:the\s+)?(?:(?:former|breathing|legendary|comedian|actor|actress|rapper|senator|mayor|"
    r"president|professor|prof|ufc|wwe|nfl|nba|boxer|fighter|champion|champ|world|famous|youtuber|streamer|musician|more)\s+)+",
    re.IGNORECASE,
)
# Capitalized title verbs that end a name: "Robbie Robertson Talks Martin Scorsese".
CUT_WORDS = {"On", "ON", "Talks", "TALKS", "Discusses", "Reveals", "Explains", "Returns", "Says", "Speaks", "Calls",
             "Exposes", "Proves", "Is", "IS", "Was", "Joins", "Breaks", "Opens", "Shares", "Gets", "Makes", "Tells", "Hosted"}
PARTICLES = {"de", "da", "del", "der", "van", "von", "la", "le", "bin", "al", "y", "el"}
NAME_TOKEN = re.compile(r"^(?:[A-ZÀ-ÖØ-Þ][\w'’.\-]*|[A-Z]\.|de|da|del|der|van|von|la|le|bin|al|y|el)$")
TRAILING_JUNK = re.compile(
    r"(?:\s+(?:returns|is back|again|live|pt\.?\s*\d+|part\s*\d+|\d+|ii|iii|iv|interview|uncensored))+$",
    re.IGNORECASE,
)
SPLIT = re.compile(r"\s*(?:&|\+|,|/|;|:|\band\b|\bAND\b|\bx\b)\s*|\s+[-–—]\s+")

# Description phrases that introduce guests (applied when the title names nobody).
NAME = (r"(?:(?:Dr|Sen|Rep|Gov|Mr|Ms|Mrs|Prof)\.?\s+)?[A-Z][a-zA-Z'’\-]+"
        r"(?:\s+(?:[A-Z]\.|[A-Z][a-zA-Z'’\-]+|de|da|van|von|del|la|Jr\.?)){1,3}")
NAMES = rf"{NAME}(?:(?:\s*,\s*|\s*,?\s+and\s+|\s*&\s*){NAME})*"
DESCRIPTORS = r"(?:(?:the|a|an|our|my|his|her|their|good|old|dear)\s+)?(?:[a-z#0-9][\w'’\-]*,?\s+(?:and\s+)?){0,12}"
HOST_WORDS = (r"(?:(?:the\s+)?(?:boys|guys|ladies|girls|Theo|Joe|Mel|Jay|us|me|Dax|Monica|Logan|Bill|Bert|Tom|"
              r"show|podcast|pod|studio|Marc|Andrew|Amy|Christina|Jenna|Angela|Zach|Donald|Adam|Ethan|Hila|"
              r"Rhett|Link|Bobby|Andrew|Shane|Matt|Steven|d\.?a\.?w\.?g\.?z\.?|dawgz)(?!\w)"
              r"|the\s+(?:[\w']+\s+){0,3}(?:Show|Podcast)\b)")
DESCRIPTION_RULES = [
    ("desc_my_guest", rf"\b(?:[Mm]y|[Oo]ur|[Tt]oday['’]?s|[Tt]his week['’]?s)\s+guests?\s+(?:today\s+|this week\s+)?(?:is|are)\s+{DESCRIPTORS}(?P<g>{NAMES})"),
    ("desc_joined_by", rf"\bjoined\s+(?:(?:again|once again|live|in(?: the)? studio|today|this week)\s+)*by\s+{DESCRIPTORS}(?P<g>{NAMES})"),
    ("desc_sits_down", rf"\bsits?\s+down\s+(?:(?:once again|again|today)\s+)?with\s+{DESCRIPTORS}(?P<g>{NAMES})"),
    ("desc_talks_with", rf"\b(?:talks?|chats?|speaks?|catches up|rambles|hangs? out)\s+(?:to|with)\s+{DESCRIPTORS}(?P<g>{NAMES})"),
    ("desc_welcomes", rf"\b(?:welcomes?|interviews?)\s+{DESCRIPTORS}(?P<g>{NAMES})"),
    ("desc_conversation", rf"\bconversation\s+with\s+{DESCRIPTORS}(?P<g>{NAMES})"),
    ("desc_this_week_we_have", rf"\b[Tt]his week,?\s+we(?:'re|’re| are)?\s+(?:have|joined by|talking (?:to|with))\s+{DESCRIPTORS}(?P<g>{NAMES})"),
    ("desc_x_joins", rf"(?P<g>{NAMES})\s+(?:joins|join|returns to|stops by|comes on)\s+{HOST_WORDS}"),
    ("desc_x_is_a", rf"^(?P<g>{NAME})\s+(?:is|was)\s+(?:a|an|the)\s"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_text(value: str) -> str:
    """HTML description -> plain single-spaced text."""
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return " ".join(html.unescape(text).replace("’", "'").split())


def episode_key(item: ET.Element, show_id: str) -> str:
    """Same episode_id as 01_build_popular_episode_frame.py (hash of GUID, else enclosure URL)."""
    guid = (item.findtext("guid") or "").strip()
    enclosure = item.find("enclosure")
    key = guid or (enclosure.get("url", "") if enclosure is not None else "")
    return f"{show_id}-{hashlib.sha256(key.encode()).hexdigest()[:12]}" if key else ""


def read_descriptions(feed_file: Path, show_id: str) -> dict[str, str]:
    channel = ET.parse(feed_file).getroot().find("channel")
    found: dict[str, str] = {}
    for item in channel.findall("item"):
        text = item.findtext("description") or ""
        if not text.strip():
            for child in item:
                if child.tag.endswith("}summary") or child.tag.endswith("}encoded"):
                    text = child.text or ""
                    if text.strip():
                        break
        found.setdefault(episode_key(item, show_id), clean_text(text))
    return found


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def tidy(candidate: str) -> str:
    """Strip decoration around a name; title-case names printed in capitals."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]|\*[^*]*\*", " ", candidate)
    text = re.sub(r"[\"“”‘’'!?¿…:;.,|~]+$", "", text.strip())
    text = re.sub(r"^[\"“”‘'.,:;\-–—\s]+", "", text)
    text = re.sub(r"[^\w\s'’.\-&]", " ", text)  # emoji and symbols
    text = " ".join(text.split())
    text = TRAILING_JUNK.sub("", text).strip(" -–—.,")
    text = TITLE_PREFIXES.sub("", text)
    text = re.sub(r"^(?:\S+'s\s+)+", "", text)
    text = " ".join(word.strip("'\"‘’“”") for word in text.split())
    # A name is the leading run of capitalized words: "Jeff Ross on The End of Roasting" -> "Jeff Ross".
    words = text.split()
    for index, word in enumerate(words[1:], start=1):
        if (word[:1].islower() and word not in PARTICLES) or word in CUT_WORDS:
            text = " ".join(words[:index])
            break
    letters = [c for c in text if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 3:
        text = " ".join(word if re.fullmatch(r"[A-Z]\.", word) else word.capitalize() for word in text.split())
        text = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), text)
    return text


def is_name(candidate: str, allow_single: bool, allow_the: bool = False) -> bool:
    tokens = candidate.split()
    if allow_the and len(tokens) > 1 and tokens[0] == "The":
        tokens = tokens[1:]
    if not tokens or len(tokens) > 5 or len(candidate) > 40:
        return False
    if len(tokens) == 1 and not allow_single:
        return False
    if len(tokens) == 1 and len(candidate) < 3:
        return False
    if any(re.search(r"\d", token) or re.search(r"'s$", token) for token in tokens):
        return False
    if any(token.casefold().strip(".'’") in STOP_WORDS for token in tokens):
        return False
    return all(NAME_TOKEN.match(token) for token in tokens) and NAME_TOKEN.match(tokens[0]).group(0)[0].isupper()


class Show:
    def __init__(self, show_id: str, show_name: str, hosts: list[str], config: dict[str, Any], defaults: dict[str, Any]):
        self.show_id = show_id
        self.show_key = normalize(show_name)
        self.title_strip = re.compile(config["title_strip"]) if config.get("title_strip") else None
        self.hosts = hosts + config.get("extra_hosts", [])
        self.host_keys = {normalize(name) for name in self.hosts}
        self.host_tokens = [set(normalize(part) for part in name.split()) for name in self.hosts]
        self.title_only = bool(config.get("title_only"))
        # Show strict rules first, then the shared rules, then show loose rules.
        ordered = ([r for r in config.get("title", []) if r["kind"] != "loose"] + defaults.get("title", [])
                   + [r for r in config.get("title", []) if r["kind"] == "loose"])
        self.title_rules = [
            (rule["rule"], rule["kind"], bool(rule.get("allow_single")), re.compile(rule["pattern"]))
            for rule in ordered
        ]

    def is_host(self, name: str) -> bool:
        key = normalize(name)
        if key in self.host_keys or (len(key) > 3 and key in self.show_key):
            return True
        if any(len(host) > 6 and " " in name and host in key for host in self.host_keys):
            return True
        tokens = {normalize(part) for part in name.split() if normalize(part) not in {"dr", "mr", "ms"}}
        return any(tokens and tokens <= host for host in self.host_tokens)


def in_description(name: str, description: str) -> bool:
    """Every word of the name appears in the description, with the same capitalization."""
    words = set(re.findall(r"[\w'.\-]+", description))
    words |= {re.sub(r"'s$", "", word) for word in words}
    stripped = {word.strip(".") for word in words}
    return all(token in words or token.strip(".") in stripped for token in name.split() if token not in {"Dr.", "Dr"})


def title_guests(show: Show, title: str, description: str) -> tuple[list[str], str]:
    title = title.replace("’", "'")
    if show.title_strip:
        title = show.title_strip.sub("", title)
    for rule, kind, allow_single, pattern in show.title_rules:
        match = pattern.search(title)
        if not match:
            continue
        names = []
        captured = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", match.group("g"))
        for part in SPLIT.split(captured):
            name = tidy(part)
            if not is_name(name, allow_single=kind == "strict" or allow_single, allow_the=kind == "strict"):
                continue
            if kind == "loose" and not in_description(name, description):
                continue
            if not show.is_host(name):
                names.append(name)
        if names:
            return names, rule
    return [], ""


def description_guests(show: Show, description: str) -> tuple[list[str], str, str]:
    names, rules, evidence = [], [], []
    for rule, pattern in DESCRIPTION_RULES:
        for match in re.finditer(pattern, description):
            for part in SPLIT.split(match.group("g")):
                name = tidy(part)
                if is_name(name, allow_single=False) and not show.is_host(name) and name not in names:
                    names.append(name)
                    rules.append(rule)
                    evidence.append(match.group(0)[-200:])
    return names, "+".join(dict.fromkeys(rules)), " || ".join(dict.fromkeys(evidence))


def edison_history() -> dict[str, list[tuple[str, int]]]:
    """Canonical Edison show name -> [(release, rank), ...]."""
    with ALIASES.open(newline="", encoding="utf-8") as handle:
        alias = {row["printed_name"]: row["canonical_show"] for row in csv.DictReader(handle)}
    history: dict[str, list[tuple[str, int]]] = defaultdict(list)
    with EDISON.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            history[alias[row["show"]]].append((row["release"], int(row["rank"])))
    return history


def latest_frame() -> Path:
    frames = sorted(path.parent for path in FRAME_ROOT.glob("*/episodes.csv"))
    if not frames:
        raise SystemExit("No popular frame; run 01_build_popular_episode_frame.py first")
    return frames[-1]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frame", type=Path, help="popular-frame folder (default: latest)")
    args = parser.parse_args()
    frame = (args.frame if args.frame and args.frame.is_absolute() else ROOT / args.frame) if args.frame else latest_frame()

    rules = json.loads(RULES.read_text(encoding="utf-8"))
    roster = json.loads(PODCASTS.read_text(encoding="utf-8"))["podcasts"]
    with FEEDS.open(newline="", encoding="utf-8") as handle:
        canonical = {row["show_id"]: row["show"] for row in csv.DictReader(handle)}
    history = edison_history()
    with (frame / "shows.csv").open(newline="", encoding="utf-8") as handle:
        shows = {row["show_id"]: row for row in csv.DictReader(handle) if row["included"] == "1"}
    with (frame / "episodes.csv").open(newline="", encoding="utf-8") as handle:
        episodes = list(csv.DictReader(handle))

    missing = sorted(set(shows) - set(rules["shows"]))
    if missing:
        raise SystemExit(f"No guest rules for: {', '.join(missing)} (add them to {RULES.relative_to(ROOT)})")
    parsers = {}
    for show_id in shows:
        config = rules["shows"][show_id]
        hosts = config.get("hosts") or roster.get(show_id, {}).get("hosts", [])
        parsers[show_id] = Show(show_id, canonical[show_id], [h for h in hosts if h != "Host"], config, rules["all"])
    descriptions = {show_id: read_descriptions(ROOT / row["feed_file"], show_id) for show_id, row in shows.items()}

    episode_rows, guest_rows = [], []
    for episode in episodes:
        show_id = episode["show_id"]
        show = parsers[show_id]
        description = descriptions[show_id].get(episode["episode_id"], "")
        names, rule = title_guests(show, episode["title"], description)
        source, evidence = ("title", episode["title"]) if names else ("none", "")
        if not names and not show.title_only:
            names, rule, evidence = description_guests(show, description)
            source = "description" if names else "none"
        year = episode["published_date"][:4]
        ranks = history.get(canonical[show_id], [])
        year_ranks = [rank for release, rank in ranks if release[:4] == year]
        episode_rows.append({
            "show": canonical[show_id],
            "show_id": show_id,
            "episode_id": episode["episode_id"],
            "published_date": episode["published_date"],
            "year": year,
            "title": episode["title"],
            "guests": "; ".join(names),
            "n_guests": len(names),
            "guest_source": source,
            "guest_rule": rule,
            "duration_minutes": round(float(episode["duration_seconds"]) / 60, 1) if episode["duration_seconds"] else "",
            "episode_type": episode["episode_type"],
            "show_edison_ranked_this_year": int(bool(year_ranks)),
            "show_edison_best_rank_this_year": min(year_ranks) if year_ranks else "",
            "description": description[:DESCRIPTION_CHARS],
        })
        for name in names:
            guest_rows.append({
                "show": canonical[show_id], "show_id": show_id, "episode_id": episode["episode_id"],
                "published_date": episode["published_date"], "guest_name": name,
                "guest_key": normalize(name), "source": source, "rule": rule, "evidence_text": evidence,
            })

    output = OUTPUT_ROOT / frame.name
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "episodes.csv", episode_rows)
    write_csv(output / "episode_guests.csv", guest_rows, [
        "show", "show_id", "episode_id", "published_date", "guest_name", "guest_key", "source", "rule", "evidence_text"])

    by_show = defaultdict(list)
    for row in episode_rows:
        by_show[row["show_id"]].append(row)
    show_rows = []
    for show_id, rows in sorted(by_show.items(), key=lambda item: canonical[item[0]].casefold()):
        ranks = sorted(history.get(canonical[show_id], []))
        show_rows.append({
            "show": canonical[show_id], "show_id": show_id, "episodes": len(rows),
            "episodes_with_guest": sum(1 for row in rows if row["n_guests"]),
            "share_with_guest": round(sum(1 for row in rows if row["n_guests"]) / len(rows), 3),
            "first_episode": min(row["published_date"] for row in rows),
            "last_episode": max(row["published_date"] for row in rows),
            "edison_releases": len(ranks), "edison_best_rank": min((r for _, r in ranks), default=""),
            "edison_ranks": "; ".join(f"{release}:{rank}" for release, rank in ranks),
            "hosts_excluded": "; ".join(parsers[show_id].hosts),
        })
    write_csv(output / "shows.csv", show_rows)

    years = sorted({row["year"] for row in episode_rows})
    lines = [
        f"# Guest dataset ({frame.name})", "",
        f"Built {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `code/18_build_guest_dataset.py` "
        f"from `{frame.relative_to(ROOT)}` and `{RULES.relative_to(ROOT)}`. Rule-based reading of RSS titles and "
        "descriptions; no model, no cost. Names are as printed in the feed and are not verified.", "",
        f"- Episodes: {len(episode_rows):,}; with at least one guest: "
        f"{sum(1 for r in episode_rows if r['n_guests']):,}; guest mentions: {len(guest_rows):,}; "
        f"distinct guest names: {len({r['guest_key'] for r in guest_rows}):,}.",
        f"- Source: " + ", ".join(f"{k} {v:,}" for k, v in Counter(r["guest_source"] for r in episode_rows).most_common()), "",
        "| Show | Episodes | With guest | Share | " + " | ".join(years) + " |",
        "| --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in years) + " |",
    ]
    for row in show_rows:
        per_year = Counter(r["year"] for r in by_show[row["show_id"]])
        lines.append(f"| {row['show']} | {row['episodes']} | {row['episodes_with_guest']} | {row['share_with_guest']:.0%} | "
                     + " | ".join(str(per_year.get(y, "")) for y in years) + " |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "0.1", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "frame": str(frame.relative_to(ROOT)),
        "inputs": {str(path.relative_to(ROOT)): sha256(path) for path in
                   [RULES, PODCASTS, FEEDS, ALIASES, EDISON, frame / "episodes.csv", frame / "shows.csv"]},
        "feeds": {show_id: {"file": row["feed_file"], "sha256": sha256(ROOT / row["feed_file"])} for show_id, row in shows.items()},
        "script_sha256": sha256(Path(__file__)),
        "episodes": len(episode_rows), "guest_rows": len(guest_rows),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(episode_rows):,} episodes, {sum(1 for r in episode_rows if r['n_guests']):,} with a guest, "
          f"{len(guest_rows):,} guest rows -> {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
