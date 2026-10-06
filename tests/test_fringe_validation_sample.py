"""Tests for the stratified fringe validation sample."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "code/16_draw_fringe_validation_sample.py"))
allocate = MODULE["allocate"]
context = MODULE["context"]


class AllocateTest(unittest.TestCase):
    def test_equal_allocation_with_cap_and_redistribution(self) -> None:
        result = allocate({"a": 100, "b": 100, "c": 3}, 30)
        self.assertEqual(result["c"], 3)
        self.assertEqual(result["a"] + result["b"], 27)
        self.assertLessEqual(abs(result["a"] - result["b"]), 1)

    def test_total_is_exact_and_never_exceeds_strata(self) -> None:
        sizes = {"a": 179, "b": 7, "c": 21, "d": 19}
        result = allocate(sizes, 50)
        self.assertEqual(sum(result.values()), 50)
        self.assertTrue(all(result[key] <= sizes[key] for key in sizes))

    def test_sample_larger_than_population_fails(self) -> None:
        with self.assertRaises(ValueError):
            allocate({"a": 2}, 3)


class ContextTest(unittest.TestCase):
    transcript = {"utterances": [
        {"speaker": "Host", "text": "one two", "start": 0, "words": [{}, {}]},
        {"speaker": "Guest", "text": "three four", "start": 61_000, "words": [{}, {}]},
        {"speaker": "Host", "text": "five", "start": 3_723_000, "words": [{}]},
    ]}

    def test_marks_claim_utterance_and_formats_timestamp(self) -> None:
        text, stamp = context(self.transcript, 3)
        self.assertIn(">> Guest: three four", text)
        self.assertIn("Host: one two", text)
        self.assertEqual(stamp, "00:01:01")
        _, late = context(self.transcript, 4)
        self.assertEqual(late, "01:02:03")

    def test_word_beyond_transcript_fails(self) -> None:
        with self.assertRaises(ValueError):
            context(self.transcript, 5)


if __name__ == "__main__":
    unittest.main()
