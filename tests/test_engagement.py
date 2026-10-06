"""Tests for YouTube matching and the engagement merge."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATCH = runpy.run_path(str(ROOT / "code/21_match_youtube_videos.py"))
MERGE = runpy.run_path(str(ROOT / "code/24_build_engagement_dataset.py"))


class MatchTest(unittest.TestCase):
    def test_episode_numbers(self) -> None:
        numbers = MATCH["numbers"]
        self.assertEqual(numbers("#2426 - Cameron Hanes"), {"2426"})
        self.assertEqual(numbers("Joe Rogan Experience #2426 - Cameron Hanes"), {"2426"})
        self.assertEqual(numbers("E445 Brianna Chickenfry"), {"445"})
        self.assertEqual(numbers("KT #787 - HARLAND WILLIAMS"), {"787"})
        self.assertEqual(numbers("Ep. 205 | 2 Bears"), {"205"})

    def test_dates_in_titles_must_agree(self) -> None:
        dates = MATCH["title_dates"]
        self.assertEqual(dates("Monday Morning Podcast 7-15-21"), {(7, 15, 21)})
        self.assertFalse(dates("Monday Morning Podcast 7-15-21") & dates("Monday Morning Podcast 5-11-23"))

    def test_guest_in_title(self) -> None:
        guest = MATCH["guest_in_title"]
        self.assertTrue(guest("Sylvester Stallone", "SYLVESTER STALLONE: I Wasn't Stupid"))
        self.assertFalse(guest("Bobby", "Bobby Lee Returns"))  # one-word names are not enough


class MergeTest(unittest.TestCase):
    def test_match_check(self) -> None:
        check = MERGE["match_check"]
        self.assertEqual(check(1, {}), "ok")
        self.assertEqual(check(400, {"episode_number_agrees": "1"}), "reupload_likely")
        self.assertEqual(check(700, {"episode_number_agrees": "0", "title_word_share": "0.5"}), "date_gap_check")

    def test_rates_and_replay_peak(self) -> None:
        self.assertEqual(MERGE["ratio"](50, 1000, 1000), 50.0)
        self.assertEqual(MERGE["ratio"]("", 1000), "")
        heatmap = [{"start_time": 0, "value": 0.2}, {"start_time": 600, "value": 1.0}]
        self.assertEqual(MERGE["replay_peak_minute"](heatmap), 10.0)


if __name__ == "__main__":
    unittest.main()
