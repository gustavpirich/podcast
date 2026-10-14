"""Tests for the DOAC full-length inclusion rule and identifiers."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "code" / "01_build_doac_rss_archive.py"))
eligible = MODULE["eligible"]
guest_label = MODULE["guest_label"]
episode_id = MODULE["episode_id"]


class DoacArchiveTests(unittest.TestCase):
    def test_full_length_interview_is_eligible(self) -> None:
        self.assertTrue(eligible("Rick Rubin: What Jay-Z Did in 30 Minutes Left Me Speechless!", "full", 166 * 60))
        self.assertTrue(eligible("E226: Zara Larsson: How To Stop Caring What Others Think!", "full", 65 * 60))

    def test_clips_bonus_and_short_items_are_excluded(self) -> None:
        self.assertFalse(eligible("Most Replayed Moment: A Guilt-Free Way to Handle Work and Life", "bonus", 32 * 60))
        self.assertFalse(eligible("Moment 211: Dr. Andrew Huberman: The Real Reason", "full", 61 * 60))
        self.assertFalse(eligible("CEO Diaries: The Brutal Mistake That Almost Crippled Snapchat!", "full", 75 * 60))
        self.assertFalse(eligible("The Diary Of A CEO Trailer", "full", 60 * 60))
        self.assertFalse(eligible("Andrew Huberman: Sleep", "full", 59 * 60))
        self.assertFalse(eligible("Andrew Huberman: Sleep", "bonus", 120 * 60))

    def test_guest_label(self) -> None:
        self.assertEqual(guest_label("Druski: They're Lying To You About Overnight Success!"), "Druski")
        self.assertEqual(guest_label("Human Lie Detector: The #1 Sign | Dr Leanne ten Brinke"), "Dr Leanne ten Brinke")
        self.assertEqual(guest_label("Seth Rogen Opens Up About His Self-Doubt"), "Guest not encoded in RSS title")

    def test_episode_id_is_stable_and_dated(self) -> None:
        first = episode_id("2026-09-21", "guid-1")
        self.assertEqual(first, episode_id("2026-09-21", "guid-1"))
        self.assertTrue(first.startswith("doac-2026-09-21-"))
        self.assertNotEqual(first, episode_id("2026-09-21", "guid-2"))


if __name__ == "__main__":
    unittest.main()
