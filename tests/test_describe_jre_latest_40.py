"""Tests for the latest-40 JRE descriptive aggregation."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "code/13_describe_jre_latest_40.py"))
episode_summaries = MODULE["episode_summaries"]


def row(window_id: int, health: int, science: int, status: str, claims: int) -> dict[str, str]:
    positive = int(bool(health or science))
    return {
        "episode_id": "episode-1",
        "episode_title": "#1 - Example",
        "window_id": str(window_id),
        "word_count": "256",
        "word_start_index": str(window_id * 128),
        "screen_health_related": str(health),
        "screen_science_related": str(science),
        "stage05_requested": str(positive),
        "fringe_status": status,
        "claim_count": str(claims),
        "unmatched_claim_text_count": "0",
        "inconsistent_claim_coding_count": "0",
    }


class Latest40DescriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = {"episodes": [{
            "episode_id": "episode-1",
            "episode_number": 1,
            "episode_kind": "numbered",
            "guest_name": "Example",
            "published_date": "2026-01-01",
        }]}

    def test_screen_negative_and_positive_no_claim_are_separate(self) -> None:
        rows = [
            row(0, 0, 0, "not_assessable", 0),
            row(1, 1, 0, "not_assessable", 0),
            row(2, 0, 1, "fringe", 2),
        ]
        episodes, overall = episode_summaries(rows, self.sample)
        self.assertEqual(overall["windows"], 3)
        self.assertEqual(overall["screen_positive_windows"], 2)
        self.assertEqual(overall["screen_negative_windows"], 1)
        self.assertEqual(overall["no_claim_windows"], 1)
        self.assertEqual(overall["fringe_windows"], 1)
        self.assertEqual(overall["claim_instances_with_overlap"], 2)
        self.assertAlmostEqual(episodes[0]["fringe_pct_all_windows"], 100 / 3)

    def test_stage05_selection_mismatch_fails(self) -> None:
        invalid = row(0, 1, 0, "fringe", 1)
        invalid["stage05_requested"] = "0"
        with self.assertRaisesRegex(ValueError, "Stage-05 selection"):
            episode_summaries([invalid], self.sample)


if __name__ == "__main__":
    unittest.main()
