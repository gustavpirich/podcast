"""Tests for the read-only pipeline status inventory."""

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "code/00_pipeline_status.py"))
transcript_status = MODULE["transcript_status"]
transcript_speakers = MODULE["transcript_speakers"]
next_step = MODULE["next_step"]


class TranscriptStatusTest(unittest.TestCase):
    def test_states_follow_the_batch_runner_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertEqual(transcript_status(path), "not_started")
            (path / "assemblyai_job.json").write_text("{}")
            self.assertEqual(transcript_status(path), "submitted")
            (path / "transcript.md").write_text("")
            self.assertEqual(transcript_status(path), "incomplete_outputs")
            (path / "transcript.json.gz").write_bytes(b"")
            (path / "assemblyai_response.json.gz").write_bytes(b"")
            self.assertEqual(transcript_status(path), "complete")


class TranscriptSpeakersTest(unittest.TestCase):
    def test_word_share_of_unnamed_voices(self) -> None:
        transcript = {
            "transcription": {},
            "speakers": [
                {"id": "A", "name": "Host Name", "role": "Host"},
                {"id": "B", "name": "Guest Name", "role": "Guest"},
                {"id": "C", "name": "C", "role": "Unidentified"},
            ],
            "utterances": [
                {"speaker": "Host Name", "words": [{}] * 5},
                {"speaker": "Guest Name", "words": [{}] * 4},
                {"speaker": "C", "words": [{}]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "transcript.json").write_text(json.dumps(transcript))
            result = transcript_speakers(Path(directory))
        self.assertEqual(result["transcript_words"], 10)
        self.assertEqual((result["n_hosts"], result["n_guests"], result["n_unidentified"]), (1, 1, 1))
        self.assertEqual(result["unidentified_word_share"], 0.1)
        self.assertEqual(result["speaker_identification_status"], "not_recorded_in_transcript")


class NextStepTest(unittest.TestCase):
    done = {
        "transcript_status": "complete",
        "stage04_screen": "collected",
        "stage08_broad_claims": "collected",
        "stage10_statements": "collected",
        "stage14_speaker_dataset": "built",
    }

    def test_first_unfinished_stage_is_next(self) -> None:
        self.assertEqual(next_step(self.done), "done; awaiting human validation")
        row = {**self.done, "stage08_broad_claims": "not_started", "stage10_statements": "not_started"}
        self.assertTrue(next_step(row).startswith("08 "))
        row = {**self.done, "transcript_status": "not_started"}
        self.assertTrue(next_step(row).startswith("02 transcribe"))

    def test_submitted_transcription_is_collected_not_resubmitted(self) -> None:
        row = {**self.done, "transcript_status": "submitted"}
        self.assertIn("collect", next_step(row))


if __name__ == "__main__":
    unittest.main()
