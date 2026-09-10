"""Tests for the transparent health/science screening rules."""

from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(PROJECT_ROOT / "code" / "03_classify_content.py"))
apply_context = MODULE["apply_context"]
classify_direct = MODULE["classify_direct"]
deterministic_audit_sample = MODULE["deterministic_audit_sample"]
interval_union_seconds = MODULE["interval_union_seconds"]
validate_path_component = MODULE["validate_path_component"]

CONFIG = {
    "health_terms": ["mental health", "sleep"],
    "health_prefixes": ["depress"],
    "science_terms": ["study", "evidence"],
    "science_prefixes": ["scien"],
    "context_rule": {"max_words": 3, "max_gap_ms": 15000},
}


class DirectClassificationTests(unittest.TestCase):
    def test_labels_are_independent(self) -> None:
        utterances = [
            {"start": 0, "end": 1000, "text": "I experienced depression."},
            {"start": 2000, "end": 3000, "text": "The evidence supports better sleep."},
            {"start": 4000, "end": 5000, "text": "A scientific theory."},
            {"start": 6000, "end": 7000, "text": "We recorded an album."},
        ]
        rows = classify_direct(utterances, CONFIG)
        self.assertEqual(
            [(row["health_related"], row["science_related"]) for row in rows],
            [(1, 0), (1, 1), (0, 1), (0, 0)],
        )

    def test_everyday_theory_is_not_automatically_science(self) -> None:
        utterances = [
            {"start": 0, "end": 1000, "text": "That is my theory about the band."}
        ]
        project_config = json.loads(
            (PROJECT_ROOT / "config" / "content_classification.json").read_text()
        )
        rows = classify_direct(utterances, project_config)
        self.assertEqual(rows[0]["science_related"], 0)

    def test_short_reply_inherits_adjacent_direct_context(self) -> None:
        utterances = [
            {"start": 0, "end": 1000, "text": "I cannot sleep."},
            {"start": 1100, "end": 1300, "text": "Really?"},
        ]
        rows = classify_direct(utterances, CONFIG)
        apply_context(rows, CONFIG)
        self.assertEqual(rows[1]["health_related"], 1)
        self.assertEqual(rows[1]["health_direct"], 0)
        self.assertEqual(rows[1]["health_context_source"], "previous")


class MeasurementTests(unittest.TestCase):
    def test_interval_union_does_not_double_count_overlap(self) -> None:
        self.assertEqual(interval_union_seconds([(0, 1000), (500, 2000)]), 2.0)

    def test_audit_sample_is_reproducible(self) -> None:
        first = deterministic_audit_sample("episode:42", 0.1)
        second = deterministic_audit_sample("episode:42", 0.1)
        self.assertEqual(first, second)

    def test_cli_folder_values_cannot_escape_the_project(self) -> None:
        with self.assertRaises(MODULE["ClassificationError"]):
            validate_path_component("../another_project", "--show-directory")


if __name__ == "__main__":
    unittest.main()
