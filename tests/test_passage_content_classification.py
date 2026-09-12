"""Tests for stage-05 passage construction and strict result validation."""

from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(
    str(PROJECT_ROOT / "code" / "05_classify_passage_content_openai_batch.py")
)
PassageClassificationError = MODULE["PassageClassificationError"]
build_batch_requests = MODULE["build_batch_requests"]
merge_positive_windows = MODULE["merge_positive_windows"]
parse_batch_results = MODULE["parse_batch_results"]


CONFIG = {
    "model": "gpt-5.6-luna",
    "reasoning_effort": "low",
    "max_output_tokens": 2000,
    "health_topics": {
        "mental_health_cognition": "Mental health.",
        "other_unclear_health": "Other health.",
    },
    "content_types": {
        "personal_experience": "Personal experience.",
        "general_conversation": "General conversation.",
    },
    "support_types": {
        "no_support_stated": "No support.",
        "personal_anecdote": "Anecdote.",
    },
    "science_content_types": {
        "research_or_data": "Research.",
        "general_science_discussion": "General science.",
    },
    "coding_rules": ["Test rule."],
    "rationale_rule": "At most 60 words.",
}


def word(index: int) -> dict[str, object]:
    return {
        "word_index": index,
        "utterance_id": index // 4,
        "speaker": "A" if index < 10 else "B",
        "start_ms": index * 100,
        "end_ms": index * 100 + 80,
        "confidence": 0.9,
        "text": f"word{index}",
    }


def screen(window_id: int, start: int, end: int, positive: bool) -> dict[str, object]:
    return {
        "episode_id": "episode1234",
        "window_id": window_id,
        "word_start_index": start,
        "word_end_index_exclusive": end,
        "health_related": positive,
        "science_related": False,
    }


def result(passage_id: str) -> dict[str, object]:
    return {
        "passage_id": passage_id,
        "confirmed_health_related": True,
        "confirmed_science_related": False,
        "primary_health_topic": "mental_health_cognition",
        "health_topics": ["mental_health_cognition"],
        "content_type": "personal_experience",
        "support_type": "personal_anecdote",
        "health_action_recommended": False,
        "claim_present": True,
        "science_content_type": "not_applicable",
        "rationale": "The speaker describes depression.",
    }


def output_row(custom_id: str, value: dict[str, object]) -> dict[str, object]:
    return {
        "custom_id": custom_id,
        "response": {
            "status_code": 200,
            "body": {
                "id": f"response-{custom_id}",
                "model": "gpt-5.6-luna",
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(value)}],
                }],
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            },
        },
        "error": None,
    }


class PassageConstructionTests(unittest.TestCase):
    def test_consecutive_positive_overlaps_are_merged(self) -> None:
        rows = [
            screen(0, 0, 8, True),
            screen(1, 4, 12, True),
            screen(2, 8, 16, False),
            screen(3, 12, 20, True),
        ]
        passages = merge_positive_windows(rows, [word(index) for index in range(20)], "episode1234")
        self.assertEqual(len(passages), 2)
        self.assertEqual(passages[0]["source_window_ids"], [0, 1])
        self.assertEqual((passages[0]["word_start_index"], passages[0]["word_end_index_exclusive"]), (0, 12))
        self.assertEqual(passages[0]["word_count"], 12)

    def test_negative_window_is_not_bridged(self) -> None:
        rows = [
            screen(0, 0, 8, True),
            screen(1, 4, 12, False),
            screen(2, 8, 16, True),
        ]
        passages = merge_positive_windows(rows, [word(index) for index in range(16)], "episode1234")
        self.assertEqual(len(passages), 2)
        self.assertEqual(passages[0]["word_end_index_exclusive"], 8)
        self.assertEqual(passages[1]["word_start_index"], 8)
        self.assertEqual(sum(item["word_count"] for item in passages), 16)

    def test_one_request_is_created_per_passage(self) -> None:
        passages = merge_positive_windows(
            [screen(0, 0, 8, True), screen(1, 4, 12, True)],
            [word(index) for index in range(12)],
            "episode1234",
        )
        requests, manifest = build_batch_requests(passages, CONFIG)
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(manifest), 1)
        payload = json.loads(requests[0]["body"]["input"])
        self.assertEqual(payload["passage"]["passage_id"], "episode1234-passage-0000")
        self.assertNotIn("text", payload["passage"])
        self.assertIn("speaker_segments", payload["passage"])


class ResultValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ids = ["episode1234-passage-0000", "episode1234-passage-0001"]
        self.manifest = {
            "requests": [
                {"custom_id": passage_id, "passage_id": passage_id}
                for passage_id in self.ids
            ]
        }

    def test_out_of_order_results_are_validated(self) -> None:
        rows = [output_row(self.ids[1], result(self.ids[1])), output_row(self.ids[0], result(self.ids[0]))]
        parsed, usage = parse_batch_results(rows, self.manifest, CONFIG)
        self.assertEqual(set(parsed), set(self.ids))
        self.assertEqual(usage["total_tokens"], 60)

    def test_missing_result_fails_closed(self) -> None:
        with self.assertRaises(PassageClassificationError):
            parse_batch_results([output_row(self.ids[0], result(self.ids[0]))], self.manifest, CONFIG)

    def test_cross_field_inconsistency_fails_closed(self) -> None:
        invalid = result(self.ids[0])
        invalid["confirmed_health_related"] = False
        with self.assertRaises(PassageClassificationError):
            parse_batch_results(
                [output_row(self.ids[0], invalid), output_row(self.ids[1], result(self.ids[1]))],
                self.manifest,
                CONFIG,
            )


if __name__ == "__main__":
    unittest.main()
