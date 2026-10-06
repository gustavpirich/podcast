"""Tests for the GPT speaker-labelling step (no API calls)."""

from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "code/03_label_speakers_gpt.py"))
CONFIG = json.loads((ROOT / "config/speaker_labeling.json").read_text())


def document():
    def utt(speaker, text, start):
        return {"speaker": speaker, "text": text, "start": start, "end": start + 1000,
                "words": [{"text": w, "speaker": speaker} for w in text.split()]}
    return {"transcription": {}, "episode": {"title": "#1 - Guest Person"},
            "utterances": [utt("A", "welcome to the show", 0), utt("B", "thanks for having me here today", 2000)]}


class ProfileTest(unittest.TestCase):
    def test_shares_and_excerpts(self) -> None:
        profiles = MODULE["speaker_profiles"](document(), CONFIG)
        self.assertEqual([p["label"] for p in profiles], ["A", "B"])
        self.assertAlmostEqual(profiles[0]["share_of_words"] + profiles[1]["share_of_words"], 1.0, places=2)
        self.assertTrue(profiles[1]["excerpts"][0].endswith("thanks for having me here today"))


class ValidateAnnotateTest(unittest.TestCase):
    answer = {"speakers": [
        {"label": "A", "name": "Joe Rogan", "role": "host", "confidence": "high", "evidence": "x"},
        {"label": "B", "name": "Guest Person", "role": "guest", "confidence": "high", "evidence": "y"}]}

    def test_missing_label_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE["validate"]({"speakers": self.answer["speakers"][:1]}, {"A", "B"}, CONFIG)

    def test_annotation_keeps_label_and_applies_name(self) -> None:
        by_label = MODULE["validate"](self.answer, {"A", "B"}, CONFIG)
        annotated = MODULE["annotate"](document(), by_label, "v1")
        first = annotated["utterances"][0]
        self.assertEqual((first["speaker"], first["role"], first["speaker_label"]), ("Joe Rogan", "host", "A"))
        self.assertEqual(first["words"][0]["speaker"], "Joe Rogan")
        self.assertIn("Joe Rogan (host)", MODULE["markdown"](annotated))


if __name__ == "__main__":
    unittest.main()
