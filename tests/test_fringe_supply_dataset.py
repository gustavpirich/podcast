"""Tests for the pilot fringe-supply dataset builder."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "code/14_build_fringe_supply_dataset.py"))
fringe_tier = MODULE["fringe_tier"]
attribute_span = MODULE["attribute_span"]
speaker_roles = MODULE["speaker_roles"]


def words(*speakers: str) -> list[dict[str, object]]:
    return [
        {"speaker": speaker, "start_ms": 100 * index, "end_ms": 100 * index + 90, "text": f"w{index}"}
        for index, speaker in enumerate(speakers)
    ]


class FringeTierTest(unittest.TestCase):
    def test_all_three_non_mainstream_positions_are_fringe_tiers(self) -> None:
        self.assertEqual(fringe_tier("emerging_non_mainstream"), "A_emerging")
        self.assertEqual(fringe_tier("alternative_speculative"), "B_speculative")
        self.assertEqual(fringe_tier("contradicts_consensus"), "C_contradicts_consensus")
        self.assertEqual(fringe_tier("mainstream"), "not_fringe")
        self.assertEqual(fringe_tier("uncertain"), "uncertain")

    def test_unknown_position_fails(self) -> None:
        with self.assertRaises(ValueError):
            fringe_tier("exaggerated")


class SpeakerAttributionTest(unittest.TestCase):
    roles = {"Guest Name": "guest", "Host Name": "host"}

    def test_majority_speaker_and_crossing_flag(self) -> None:
        result = attribute_span(words("Host Name", "Guest Name", "Guest Name", "Guest Name"), 1, 4, self.roles)
        self.assertEqual(result["speaker"], "Guest Name")
        self.assertEqual(result["speaker_role"], "guest")
        self.assertEqual(result["span_crosses_speakers"], 0)
        self.assertEqual(result["start_ms"], 100)

        crossing = attribute_span(words("Host Name", "Guest Name", "Guest Name"), 0, 3, self.roles)
        self.assertEqual(crossing["speaker"], "Guest Name")
        self.assertEqual(crossing["span_crosses_speakers"], 1)
        self.assertAlmostEqual(crossing["speaker_word_share"], 2 / 3, places=5)

    def test_unknown_speaker_is_unidentified(self) -> None:
        result = attribute_span(words("C", "C"), 0, 2, self.roles)
        self.assertEqual(result["speaker_role"], "unidentified")

    def test_span_outside_transcript_fails(self) -> None:
        with self.assertRaises(ValueError):
            attribute_span(words("Host Name"), 0, 2, self.roles)


class SpeakerRoleTest(unittest.TestCase):
    def test_configured_host_and_guest(self) -> None:
        transcript = {"speakers": [
            {"id": "A", "name": "Guest Name", "role": "Guest"},
            {"id": "B", "name": "Host Name", "role": "Host"},
            {"id": "C", "name": "C", "role": "Unidentified"},
        ]}
        roles = speaker_roles(transcript, {"Host Name"})
        self.assertEqual(roles["Guest Name"], "guest")
        self.assertEqual(roles["Host Name"], "host")
        self.assertEqual(roles["C"], "unidentified")

    def test_unconfigured_host_fails(self) -> None:
        transcript = {"speakers": [{"id": "A", "name": "Someone Else", "role": "Host"}]}
        with self.assertRaises(ValueError):
            speaker_roles(transcript, {"Host Name"})


if __name__ == "__main__":
    unittest.main()
