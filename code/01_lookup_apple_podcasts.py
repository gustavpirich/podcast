#!/usr/bin/env python3
"""Look up every Edison Top-50 show in Apple's public podcast directory.

For each canonical show in config/edison_show_aliases.csv, queries the iTunes
Search API (US store, podcasts only) and stores the raw JSON response, which
includes the RSS feed URL and Apple genres. Choosing the right result is a
separate, reviewable step (01_match_apple_podcasts.py). Free; no API key.

    python code/01_lookup_apple_podcasts.py          # show the plan
    python code/01_lookup_apple_podcasts.py --yes    # query Apple (~3 s per show)
    python code/01_lookup_apple_podcasts.py --yes --only "ShxtsNGigs" \
        --term "The Always Sunny Podcast=Always Sunny Podcast Megawatt"   # re-search a few shows

Output: data/raw/popularity/apple_search/<UTC timestamp>/<show slug>.json,
        manifest.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIASES = ROOT / "config/edison_show_aliases.csv"
OUTPUT_ROOT = ROOT / "data/raw/popularity/apple_search"
SEARCH_URL = "https://itunes.apple.com/search"
USER_AGENT = "Mozilla/5.0 (academic research; podcast_observational)"
PAUSE_SECONDS = 3.0  # Apple asks for roughly 20 requests per minute
RESULT_LIMIT = 10


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:80]


def canonical_shows() -> list[str]:
    with ALIASES.open(newline="", encoding="utf-8") as handle:
        return sorted({row["canonical_show"] for row in csv.DictReader(handle)}, key=str.casefold)


def search(term: str) -> tuple[bytes, str]:
    query = urllib.parse.urlencode({
        "term": term, "country": "US", "media": "podcast", "entity": "podcast", "limit": RESULT_LIMIT,
    })
    url = f"{SEARCH_URL}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read(), url
        except urllib.error.HTTPError as error:
            if error.code not in (403, 429, 500, 502, 503) or attempt == 3:
                raise
            time.sleep(30 * (attempt + 1))  # back off when rate limited
    raise RuntimeError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="query Apple (otherwise only print the plan)")
    parser.add_argument("--only", action="append", default=[], help="search only this show (repeatable)")
    parser.add_argument("--term", action="append", default=[],
                        help="SHOW=SEARCH TERM: search with a different term (repeatable; implies --only)")
    args = parser.parse_args()

    terms = dict(item.split("=", 1) for item in args.term)
    shows = canonical_shows()
    wanted = set(args.only) | set(terms)
    if wanted:
        unknown = wanted - set(shows)
        if unknown:
            raise SystemExit(f"Not canonical show names: {sorted(unknown)}")
        shows = [show for show in shows if show in wanted]
    slugs = [slug(show) for show in shows]
    if len(set(slugs)) != len(slugs):
        raise SystemExit("Two shows share a file slug; rename one in the alias file")
    print(f"{len(shows)} shows from {ALIASES.relative_to(ROOT)}; about {len(shows) * PAUSE_SECONDS / 60:.0f} minutes")
    if not args.yes:
        print("Plan only. Add --yes to query the iTunes Search API (public, free).")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = OUTPUT_ROOT / stamp
    snapshot.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "0.1", "snapshot": stamp, "endpoint": SEARCH_URL,
        "parameters": {"country": "US", "media": "podcast", "entity": "podcast", "limit": RESULT_LIMIT},
        "aliases_sha256": hashlib.sha256(ALIASES.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shows": [],
    }
    failures = 0
    for number, (show, name) in enumerate(zip(shows, slugs), start=1):
        record = {"show": show, "file": f"{name}.json", "search_term": terms.get(show, show)}
        try:
            content, url = search(record["search_term"])
            with (snapshot / record["file"]).open("xb") as handle:
                handle.write(content)
            record.update(
                url=url, accessed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                sha256=hashlib.sha256(content).hexdigest(),
                result_count=json.loads(content)["resultCount"], status="ok",
            )
        except Exception as error:
            record["status"] = f"error: {type(error).__name__}: {error}"
            failures += 1
        manifest["shows"].append(record)
        print(f"  [{number:3d}/{len(shows)}] {record['status'][:40]:40} {record.get('result_count', '-'):>3} {show}")
        time.sleep(PAUSE_SECONDS)

    with (snapshot / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print(f"\nWrote {snapshot.relative_to(ROOT)} ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
