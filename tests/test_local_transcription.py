"""Tests for the local Whisper + pyannote transcript assembly (no models are run)."""

from __future__ import annotations

import importlib.util
import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "code/02_transcribe_local.py"))


def word(text: str, start: int, end: int) -> dict:
    return {"text": text, "start": start, "end": end, "confidence": 0.9}


class AssignSpeakersTest(unittest.TestCase):
    def test_midpoint_and_nearest_turn(self) -> None:
        words = [word("hi", 0, 400), word("there", 1100, 1300), word("gap", 2050, 2150), word("late", 9000, 9100)]
        turns = [(0, 1000, "SPEAKER_01"), (1000, 2000, "SPEAKER_00"), (2200, 3000, "SPEAKER_01")]
        MODULE["assign_speakers"](words, turns)
        self.assertEqual([w["speaker"] for w in words], ["SPEAKER_01", "SPEAKER_00", "SPEAKER_00", "SPEAKER_01"])

    def test_no_turns_marks_unknown(self) -> None:
        words = [word("hi", 0, 100)]
        MODULE["assign_speakers"](words, [])
        self.assertEqual(words[0]["speaker"], "UNKNOWN")


class GroupingTest(unittest.TestCase):
    def test_relabel_in_order_of_appearance_and_group(self) -> None:
        words = [word("a", 0, 10), word("b", 10, 20), word("c", 20, 30)]
        for item, speaker in zip(words, ["SPEAKER_03", "SPEAKER_03", "SPEAKER_01"]):
            item["speaker"] = speaker
        self.assertEqual(MODULE["relabel"](words), ["A", "B"])
        grouped = MODULE["utterances"](words)
        self.assertEqual([(u["speaker"], u["text"], u["start"], u["end"]) for u in grouped],
                         [("A", "a b", 0, 20), ("B", "c", 20, 30)])
        self.assertEqual(grouped[0]["words"][0]["speaker"], "A")


class SentenceAssignmentTest(unittest.TestCase):
    def test_sentences_split_at_end_punctuation(self) -> None:
        words = [word(t, i * 100, i * 100 + 90) for i, t in enumerate(["Hi,", "Joe.", "Good", "to", "see", "you?", "Yes"])]
        self.assertEqual(MODULE["sentence_groups"](words), [[0, 1], [2, 3, 4, 5], [6]])

    def test_lagging_boundary_moves_whole_sentence(self) -> None:
        # "Is it really? I mean, if you're | smoking" - the turn boundary lands mid-sentence;
        # the sentence "I mean, if you're smoking." mostly overlaps speaker 2's turn.
        texts = ["Is", "it", "really?", "I", "mean,", "if", "you're", "smoking."]
        words = [word(t, i * 1000, i * 1000 + 900) for i, t in enumerate(texts)]
        turns = [(0, 4000, "S1"), (4000, 8000, "S2")]
        counts = MODULE["assign_by_sentence"](words, turns)
        self.assertEqual([w["speaker"] for w in words], ["S1"] * 3 + ["S2"] * 5)
        self.assertEqual(counts["sentence"], 2)

    def test_genuine_interruption_keeps_word_level(self) -> None:
        texts = ["so", "the", "thing", "is", "that", "we", "never", "really", "knew", "anything."]
        words = [word(t, i * 1000, i * 1000 + 900) for i, t in enumerate(texts)]
        turns = [(0, 5000, "S1"), (5000, 10000, "S2")]
        counts = MODULE["assign_by_sentence"](words, turns)
        self.assertEqual(counts["word_level_interruption"], 1)
        self.assertEqual([w["speaker"] for w in words], ["S1"] * 5 + ["S2"] * 5)


class ExpectedSpeakersTest(unittest.TestCase):
    def test_guest_names_from_titles(self) -> None:
        guests = MODULE["title_guests"]
        self.assertEqual(guests("#1858 - Josh Dubin & Derrick Hamilton"), ["Josh Dubin", "Derrick Hamilton"])
        self.assertEqual(guests("JRE MMA Show #65 with Corey Anderson"), ["Corey Anderson"])
        self.assertEqual(guests("Weight Loss! | Dr Andy Galpin"), ["Dr Andy Galpin"])
        self.assertIsNone(guests("#2539 - Protect Our Parks 17"))
        self.assertIsNone(guests("No guest in this title"))

    def test_expected_speakers_adds_hosts(self) -> None:
        expected = MODULE["expected_speakers"]
        self.assertEqual(expected({"podcast": {"hosts": ["Joe Rogan"]}, "episode": {"title": "#2520 - Tommy Lee"}}), 2)
        self.assertIsNone(expected({"podcast": {"hosts": ["Joe Rogan"]}, "episode": {"title": "#2539 - Protect Our Parks 17"}}))


    def test_speaker_bounds_exact_or_fallback(self) -> None:
        bounds = MODULE["speaker_bounds"]
        named = {"podcast": {"hosts": ["Joe Rogan"], "max_speakers_expected": 4},
                 "episode": {"title": "#1858 - Josh Dubin & Derrick Hamilton"}}
        unnamed = {"podcast": {"hosts": ["Joe Rogan"]}, "episode": {"title": "#2539 - Protect Our Parks 17"}}
        self.assertEqual(bounds(named, "title"), (3, 3, "title_exact"))
        self.assertEqual(bounds(named, "range"), (2, 4, "range"))
        self.assertEqual(bounds(unnamed, "title"), (2, 4, "range_title_unparsed"))


COMPARE = runpy.run_path(str(ROOT / "code/02_compare_local_transcripts.py"))


@unittest.skipUnless(importlib.util.find_spec("jiwer"), "jiwer not installed in this interpreter")
class CompareTest(unittest.TestCase):
    def test_label_mapping_and_agreement(self) -> None:
        def doc(spoken):
            return {"utterances": [{"speaker": s, "words": [{"text": w, "speaker": s} for w in ws.split()]}
                                   for s, ws in spoken]}
        reference = doc([("Host", "hello there friend"), ("Guest", "hi how are you")])
        local = doc([("A", "hello there"), ("B", "friend hi how are you")])
        result = COMPARE["compare"](reference, local)
        self.assertEqual(result["wer"], 0)
        self.assertEqual(result["aligned_words"], 7)
        self.assertAlmostEqual(result["speaker_agreement"], 6 / 7, places=3)
        self.assertEqual(result["local_to_assemblyai"], "A->Host; B->Guest")


if __name__ == "__main__":
    unittest.main()
