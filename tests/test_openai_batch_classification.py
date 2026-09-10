"""Tests for local preparation and strict collection of OpenAI Batch results."""

from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(
    str(PROJECT_ROOT / "code" / "04_classify_content_openai_batch.py")
)
BatchClassificationError = MODULE["BatchClassificationError"]
build_batch_requests = MODULE["build_batch_requests"]
build_word_windows = MODULE["build_word_windows"]
flatten_transcript_words = MODULE["flatten_transcript_words"]
parse_batch_results = MODULE["parse_batch_results"]


def output_row(custom_id: str, result: dict[str, object]) -> dict[str, object]:
    return {
        "custom_id": custom_id,
        "response": {
            "status_code": 200,
            "body": {
                "id": f"response-{custom_id}",
                "model": "test-model",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(result)}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            },
        },
        "error": None,
    }


def item(window_id: int) -> dict[str, object]:
    return {
        "window_id": window_id,
        "health_related": window_id == 1,
        "science_related": window_id == 2,
        "health_rationale": "test health rationale",
        "science_rationale": "test science rationale",
    }


def word(index: int, speaker: str = "A") -> dict[str, object]:
    return {
        "word_index": index,
        "utterance_id": index // 3,
        "speaker": speaker,
        "start_ms": index * 100,
        "end_ms": index * 100 + 80,
        "confidence": 0.9,
        "text": f"word{index}",
    }


class RequestPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        config = {
            "window_words": 4,
            "stride_words": 2,
            "minimum_episode_words": 8,
            "model": "test-model",
            "reasoning_effort": "low",
            "max_output_tokens": 100,
            "labels": {"health_related": "health", "science_related": "science"},
            "coding_rules": ["test rule"],
            "rationale_rule": "brief",
        }
        self.config = config

    def test_windows_are_full_sized_and_overlap_by_stride(self) -> None:
        windows = build_word_windows([word(index) for index in range(9)], self.config)
        self.assertEqual(len(windows), 3)
        self.assertEqual(
            [window["word_start_index"] for window in windows], [0, 2, 4]
        )
        self.assertEqual(
            [window["word_end_index_exclusive"] for window in windows], [4, 6, 8]
        )
        self.assertTrue(all(window["word_count"] == 4 for window in windows))

    def test_one_batch_request_is_created_per_window(self) -> None:
        windows = build_word_windows([word(index) for index in range(8)], self.config)
        requests, request_windows = build_batch_requests(
            windows, "episode", self.config
        )
        self.assertEqual(len(requests), 3)
        self.assertEqual(
            [value["window_id"] for value in request_windows], [0, 1, 2]
        )
        second_payload = json.loads(requests[1]["body"]["input"])
        self.assertEqual(second_payload["target_window"]["window_id"], 1)
        segment_text = " ".join(
            segment["text"]
            for segment in second_payload["target_window"]["speaker_segments"]
        )
        self.assertEqual(segment_text, "word2 word3 word4 word5")

    def test_episode_below_minimum_is_rejected(self) -> None:
        with self.assertRaises(BatchClassificationError):
            build_word_windows([word(index) for index in range(7)], self.config)

    def test_paper_threshold_produces_five_full_windows(self) -> None:
        config = {
            "window_words": 256,
            "stride_words": 128,
            "minimum_episode_words": 768,
        }
        windows = build_word_windows(
            [word(index) for index in range(768)], config
        )
        self.assertEqual(len(windows), 5)
        self.assertEqual(windows[-1]["word_start_index"], 512)
        self.assertEqual(windows[-1]["word_end_index_exclusive"], 768)

    def test_flattening_preserves_word_order_and_utterance_ids(self) -> None:
        utterances = [
            {
                "speaker": "A",
                "words": [
                    {"text": "one", "start": 0, "end": 10, "confidence": 0.9},
                    {"text": "two", "start": 11, "end": 20, "confidence": 0.8},
                ],
            },
            {
                "speaker": "B",
                "words": [
                    {"text": "three", "start": 21, "end": 30, "confidence": 0.7}
                ],
            },
        ]
        flattened = flatten_transcript_words(utterances)
        self.assertEqual([value["text"] for value in flattened], ["one", "two", "three"])
        self.assertEqual([value["utterance_id"] for value in flattened], [0, 0, 1])


class ResultValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = {
            "input": {"windows": 4},
            "windows": [
                {"custom_id": f"window-{index}", "window_id": index}
                for index in range(4)
            ],
        }

    def test_output_order_does_not_matter(self) -> None:
        rows = [
            output_row("window-2", item(2)),
            output_row("window-0", item(0)),
            output_row("window-3", item(3)),
            output_row("window-1", item(1)),
        ]
        classifications, usage = parse_batch_results(rows, self.manifest)
        self.assertEqual(sorted(classifications), [0, 1, 2, 3])
        self.assertTrue(classifications[1]["health_related"])
        self.assertEqual(usage["total_tokens"], 60)

    def test_missing_window_fails_closed(self) -> None:
        rows = [output_row("window-0", item(0))]
        with self.assertRaises(BatchClassificationError):
            parse_batch_results(rows, self.manifest)

    def test_wrong_window_id_fails_closed(self) -> None:
        rows = [output_row(f"window-{index}", item(index)) for index in range(4)]
        rows[1] = output_row("window-1", item(2))
        with self.assertRaises(BatchClassificationError):
            parse_batch_results(rows, self.manifest)


if __name__ == "__main__":
    unittest.main()
