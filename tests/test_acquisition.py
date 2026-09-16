"""Small standard-library tests for the deterministic acquisition logic."""

from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "code" / "01_download.py")
)
ARCHIVE_MODULE = runpy.run_path(
    str(
        Path(__file__).resolve().parents[1]
        / "code"
        / "01_build_jre_rss_archive.py"
    )
)
DownloadError = MODULE["DownloadError"]
extract_youtube_id = MODULE["extract_youtube_id"]
match_rss_episode = MODULE["match_rss_episode"]
match_rss_guid = MODULE["match_rss_guid"]
normalize_title = MODULE["normalize_title"]
load_sample = MODULE["load_sample"]
episode_kind_and_number = ARCHIVE_MODULE["episode_kind_and_number"]
archive_episode_id = ARCHIVE_MODULE["episode_id"]
parse_duration = ARCHIVE_MODULE["parse_duration"]


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

    def test_pre_registered_guid_match_is_unique(self) -> None:
        items = [
            {"guid": "episode-1", "title": "A"},
            {"guid": "episode-2", "title": "B"},
        ]
        item, method = match_rss_guid("episode-2", items)
        self.assertEqual(item["title"], "B")
        self.assertEqual(method, "pre-registered unique RSS GUID")

    def test_missing_pre_registered_guid_is_rejected(self) -> None:
        with self.assertRaises(DownloadError):
            match_rss_guid("missing", [{"guid": "episode-1"}])


class FrozenSampleTests(unittest.TestCase):
    def test_doac_sample_has_ten_unique_episodes(self) -> None:
        show_id, episodes = load_sample(
            Path(__file__).resolve().parents[1] / "config" / "doac_starter_sample.json"
        )
        self.assertEqual(show_id, "doac")
        self.assertEqual(len(episodes), 10)
        self.assertEqual(len({row["youtube_url"] for row in episodes}), 10)
        self.assertEqual(len({row["rss_guid"] for row in episodes}), 10)
        document = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "config"
                / "doac_starter_sample.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(all(row.get("guest_name") for row in document["episodes"]))

    def test_jre_sample_has_pilot_plus_nine_unique_episodes(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "jre_starter_sample.json"
        )
        show_id, episodes = load_sample(path)
        self.assertEqual(show_id, "jre")
        self.assertEqual(len(episodes), 10)
        self.assertEqual(len({row["youtube_url"] for row in episodes}), 10)
        self.assertEqual(len({row["rss_guid"] for row in episodes}), 10)
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["episodes"][0]["youtube_id"], "BAhcDwMGKYU")
        self.assertTrue(all(row.get("guest_name") for row in document["episodes"]))


class JreArchiveRuleTests(unittest.TestCase):
    def test_numbered_and_mma_releases_are_included(self) -> None:
        self.assertEqual(episode_kind_and_number("#2553 - Guest"), ("numbered", 2553))
        self.assertEqual(
            episode_kind_and_number("JRE MMA Show #184 with Guest"),
            ("mma", 184),
        )
        self.assertEqual(archive_episode_id("#2553 - Guest"), "jre-2553")
        self.assertEqual(
            archive_episode_id("JRE MMA Show #184 with Guest"), "jre-mma-184"
        )

    def test_fight_companion_and_unnumbered_specials_are_excluded(self) -> None:
        self.assertIsNone(episode_kind_and_number("#706 - Fight Companion (Part 1)"))
        self.assertIsNone(episode_kind_and_number("Joe Rogan: End of the World"))

    def test_rss_durations_are_normalized_to_seconds(self) -> None:
        self.assertEqual(parse_duration("3601"), 3601.0)
        self.assertEqual(parse_duration("1:02:03"), 3723.0)

if __name__ == "__main__":
    unittest.main()
