"""Small standard-library tests for the deterministic acquisition logic."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "code" / "01_download.py")
)
DownloadError = MODULE["DownloadError"]
extract_youtube_id = MODULE["extract_youtube_id"]
match_rss_episode = MODULE["match_rss_episode"]
normalize_title = MODULE["normalize_title"]


class YouTubeIdTests(unittest.TestCase):
    def test_common_url_forms(self) -> None:
        expected = "BAhcDwMGKYU"
        values = [
            expected,
            f"https://www.youtube.com/watch?v={expected}",
            f"https://youtu.be/{expected}",
            f"https://www.youtube.com/shorts/{expected}",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(extract_youtube_id(value), expected)

    def test_non_youtube_url_is_rejected(self) -> None:
        with self.assertRaises(DownloadError):
            extract_youtube_id("https://example.com/watch?v=BAhcDwMGKYU")


class MetadataLogicTests(unittest.TestCase):
    def test_title_normalization(self) -> None:
        self.assertEqual(
            normalize_title("Joe Rogan Experience #2550 – Rick Springfield"),
            "2550 rick springfield",
        )

    def test_episode_number_match_is_unique(self) -> None:
        items = [
            {"title": "#2549 - Someone Else"},
            {"title": "#2550 - Rick Springfield"},
        ]
        item, method = match_rss_episode(
            "Joe Rogan Experience #2550 - Rick Springfield", items
        )
        self.assertEqual(item["title"], "#2550 - Rick Springfield")
        self.assertEqual(method, "unique episode number #2550")


if __name__ == "__main__":
    unittest.main()
