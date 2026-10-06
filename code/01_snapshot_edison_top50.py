#!/usr/bin/env python3
"""Archive the Edison Research / SSRS "Top 50 Podcasts in the U.S." releases.

Downloads each release page listed in config/edison_top50_sources.json and the
ranking image(s) embedded in it (the full lists are published only as images)
into a new timestamped folder. Existing snapshots are never modified.

    python code/01_snapshot_edison_top50.py          # show the plan
    python code/01_snapshot_edison_top50.py --yes    # download
    python code/01_snapshot_edison_top50.py --yes --only 2020 2021Q2   # some releases

Output: data/raw/popularity/edison_top50/<UTC timestamp>/
    <release>/page.html, <release>/<image files>, manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "config/edison_top50_sources.json"
OUTPUT_ROOT = ROOT / "data/raw/popularity/edison_top50"
USER_AGENT = "Mozilla/5.0 (academic research; podcast_observational)"
# Ranking images are uploads whose file name contains "top-50"/"top50"/"top_50"
# (or "top-10"/"top-30" for the first two rankings, 2019-2020).
IMG_SRC = re.compile(r"<img\b[^>]*?\ssrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
RANKING_NAME = re.compile(r"top[-_ ]?(?:10|30|50)(?!\d)", re.IGNORECASE)


def fetch(url: str) -> tuple[bytes, str, str]:
    """Return (content, final URL after redirects, content type)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), response.geturl(), response.headers.get("Content-Type", "")


def ranking_images(html: str, page_url: str) -> list[str]:
    """Absolute URLs of embedded <img src> files that look like the Top-50 chart."""
    urls = []
    for src in IMG_SRC.findall(html):
        absolute = urljoin(page_url, src)
        if RANKING_NAME.search(Path(urlparse(absolute).path).name) and absolute not in urls:
            urls.append(absolute)
    return urls


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:  # "x" refuses to overwrite
        handle.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="download (otherwise only print the plan)")
    parser.add_argument("--only", nargs="+", metavar="RELEASE", help="download only these releases (e.g. 2019Q3-Q4)")
    args = parser.parse_args()

    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    releases = sources["releases"]
    if args.only:
        unknown = set(args.only) - {item["release"] for item in releases}
        if unknown:
            raise SystemExit(f"unknown release(s): {', '.join(sorted(unknown))}")
        releases = [item for item in releases if item["release"] in args.only]
    print(f"{len(releases)} Edison Top-50 releases in {SOURCES.relative_to(ROOT)}")
    for item in releases:
        print(f"  {item['release']:10} {item['url']}")
    if not args.yes:
        print("\nPlan only. Add --yes to download pages and ranking images (public web pages; free).")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = OUTPUT_ROOT / stamp
    if snapshot.exists():
        raise SystemExit(f"{snapshot} already exists; refusing to overwrite")
    manifest = {
        "schema_version": "0.1",
        "snapshot": stamp,
        "sources_config": str(SOURCES.relative_to(ROOT)),
        "sources_config_sha256": sha256(SOURCES.read_bytes()),
        "script_sha256": sha256(Path(__file__).read_bytes()),
        "user_agent": USER_AGENT,
        "only": args.only,
        "releases": [],
    }
    failures = 0
    for item in releases:
        record = {"release": item["release"], "url": item["url"]}
        try:
            html, final_url, content_type = fetch(item["url"])
            record.update(final_url=final_url, accessed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            if "html" not in content_type.lower():
                # A direct link to the ranking file itself (e.g. a PDF release).
                name = Path(urlparse(final_url).path).name
                write_new(snapshot / item["release"] / name, html)
                record["images"] = [{
                    "url": item["url"], "file": f"{item['release']}/{name}",
                    "sha256": sha256(html), "content_type": content_type, "bytes": len(html),
                }]
                record["status"] = "ok"
                manifest["releases"].append(record)
                print(f"  {item['release']:10} {record['status']:24} 1 file (direct link)")
                continue
            write_new(snapshot / item["release"] / "page.html", html)
            record["page"] = {"file": f"{item['release']}/page.html", "sha256": sha256(html), "content_type": content_type}
            record["images"] = []
            for image_url in ranking_images(html.decode("utf-8", errors="replace"), final_url):
                content, image_final, image_type = fetch(image_url)
                name = Path(urlparse(image_final).path).name
                write_new(snapshot / item["release"] / name, content)
                record["images"].append({
                    "url": image_url, "file": f"{item['release']}/{name}",
                    "sha256": sha256(content), "content_type": image_type, "bytes": len(content),
                })
            record["status"] = "ok" if record["images"] else "no_ranking_image_found"
        except Exception as error:  # record and continue; the manifest shows what failed
            record["status"] = f"error: {type(error).__name__}: {error}"
            failures += 1
        manifest["releases"].append(record)
        print(f"  {item['release']:10} {record['status']:24} {len(record.get('images', []))} image(s)")

    write_new(snapshot / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print(f"\nWrote {snapshot.relative_to(ROOT)} ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
