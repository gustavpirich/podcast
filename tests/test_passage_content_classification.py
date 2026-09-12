"""Tests for stage-05 passage construction and strict result validation."""

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(
    str(PROJECT_ROOT / "code" / "05_classify_passage_content_openai_batch.py")
)
PassageClassificationError = MODULE["PassageClassificationError"]
build_batch_requests = MODULE["build_batch_requests"]
merge_positive_windows = MODULE["merge_positive_windows"]
parse_batch_results = MODULE["parse_batch_results"]
response_schema = MODULE["response_schema"]
analytic_rows = MODULE["analytic_rows"]
build_summary = MODULE["build_summary"]


CONFIG = {
    "model": "gpt-5.6-luna",
    "reasoning_effort": "low",
    "max_output_tokens": 4000,
    "claim_domains": {
        "health": "Health.", "science": "Science.", "both": "Both.",
    },
    "claim_types": {
        "descriptive_empirical": "Empirical.",
        "causal_mechanistic": "Causal.",
    },
    "consensus_relations": {
        "consistent_with_consensus": "Consistent.",
        "within_legitimate_debate": "Debated.",
        "conflicts_with_consensus": "Conflicts.",
        "extraordinary_unsupported": "Extraordinary.",
        "insufficient_information": "Insufficient.",
    },
    "fringe_statuses": {
        "fringe": "Fringe.", "not_fringe": "Not fringe.",
        "uncertain": "Uncertain.",
    },
    "coding_rules": ["Test rule."],
    "passage_rationale_rule": "At most 60 words.",
    "fringe_reason_rule": "At most 80 words.",
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
        "passage_rationale": "The speaker makes a health claim.",
        "claims": [{
            "exact_claim_text": "Exercise reduces cardiovascular risk.",
            "claim_domain": "health",
            "claim_type": "descriptive_empirical",
            "consensus_relation": "consistent_with_consensus",
            "fringe_status": "not_fringe",
            "fringe_reason": "The claim is consistent with established health guidance.",
        }],
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

    def test_long_positive_region_is_split_without_overlap(self) -> None:
        rows = [
            screen(0, 0, 8, True),
            screen(1, 4, 12, True),
            screen(2, 8, 16, True),
            screen(3, 12, 20, True),
        ]
        passages = merge_positive_windows(
            rows, [word(index) for index in range(20)], "episode1234",
            max_passage_words=8,
        )
        self.assertGreater(len(passages), 1)
        self.assertTrue(all(passage["word_count"] <= 8 for passage in passages))
        self.assertEqual(sum(passage["word_count"] for passage in passages), 20)
        for left, right in zip(passages, passages[1:]):
            self.assertEqual(
                left["word_end_index_exclusive"], right["word_start_index"]
            )

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

    def test_structured_output_schema_uses_supported_array_keywords(self) -> None:
        claims = response_schema(CONFIG)["properties"]["claims"]
        self.assertNotIn("uniqueItems", claims)
        self.assertEqual(claims["items"]["type"], "object")
        self.assertFalse(claims["items"]["additionalProperties"])


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

    def test_duplicate_claim_text_fails_local_validation(self) -> None:
        invalid = result(self.ids[0])
        invalid["claims"] = [invalid["claims"][0], invalid["claims"][0]]
        with self.assertRaisesRegex(PassageClassificationError, "Duplicate claim text"):
            parse_batch_results(
                [
                    output_row(self.ids[0], invalid),
                    output_row(self.ids[1], result(self.ids[1])),
                ],
                self.manifest,
                CONFIG,
            )

    def test_uncertain_is_retained_as_a_separate_status(self) -> None:
        uncertain = result(self.ids[0])
        uncertain["claims"][0]["consensus_relation"] = "insufficient_information"
        uncertain["claims"][0]["fringe_status"] = "uncertain"
        parsed, _ = parse_batch_results(
            [
                output_row(self.ids[0], uncertain),
                output_row(self.ids[1], result(self.ids[1])),
            ],
            self.manifest,
            CONFIG,
        )
        self.assertEqual(parsed[self.ids[0]]["claims"][0]["fringe_status"], "uncertain")

    def test_consensus_and_fringe_status_must_agree(self) -> None:
        invalid = result(self.ids[0])
        invalid["claims"][0]["fringe_status"] = "fringe"
        with self.assertRaisesRegex(PassageClassificationError, "Consensus/fringe inconsistency"):
            parse_batch_results(
                [
                    output_row(self.ids[0], invalid),
                    output_row(self.ids[1], result(self.ids[1])),
                ],
                self.manifest,
                CONFIG,
            )


class AnalyticRowTests(unittest.TestCase):
    def passage(self) -> dict[str, object]:
        value = merge_positive_windows(
            [screen(0, 0, 8, True)],
            [word(index) for index in range(8)],
            "episode1234",
        )[0]
        value["episode_title"] = "Example episode"
        return value

    def provider_result(self, passage_id: str) -> dict[str, object]:
        return {
            **result(passage_id), "batch_custom_id": passage_id,
            "response_id": "response-1", "response_model": "gpt-5.6-luna",
        }

    def test_one_csv_row_is_created_per_claim(self) -> None:
        passage = self.passage()
        provider_result = self.provider_result(passage["passage_id"])
        provider_result["claims"] = [
            {
                **provider_result["claims"][0],
                "exact_claim_text": "word1 word2",
            },
            {
                **provider_result["claims"][0],
                "exact_claim_text": "word3 word4",
                "consensus_relation": "insufficient_information",
                "fringe_status": "uncertain",
                "fringe_reason": "The evidence is insufficient.",
            },
        ]
        rows = analytic_rows(
            [passage], {passage["passage_id"]: provider_result}, "sample-1", "jre"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["snippet_id"], rows[1]["snippet_id"])
        self.assertEqual(rows[1]["fringe_status"], "uncertain")
        self.assertEqual(rows[0]["claim_count_in_snippet"], 2)

        summary = build_summary(
            rows, [passage], {passage["passage_id"]: provider_result},
            {
                "sample_id": "sample-1", "show_id": "jre", "model": "gpt-5.6-luna",
                "prompt_version": "test-v1", "run_id": "run-1", "selection": {},
                "episodes": [{
                    "episode_id": "episode1234", "transcript_words": 20,
                    "candidate_passages": 1,
                }],
            },
            {"batch_id": "batch-1", "openai_python_version": "3.11.0"},
            {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )
        self.assertEqual(summary["totals"]["candidate_unique_words"], 8)
        self.assertEqual(summary["totals"]["claims_extracted"], 2)
        self.assertEqual(summary["totals"]["fringe_statuses"]["uncertain"], 1)

    def test_snippet_without_claim_gets_not_assessable_row(self) -> None:
        passage = self.passage()
        provider_result = self.provider_result(passage["passage_id"])
        provider_result["claims"] = []
        rows = analytic_rows(
            [passage], {passage["passage_id"]: provider_result}, "sample-1", "jre"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["claim_present"], 0)
        self.assertEqual(rows[0]["fringe_status"], "not_assessable")

    def test_claim_text_must_be_an_exact_snippet_substring(self) -> None:
        passage = self.passage()
        provider_result = self.provider_result(passage["passage_id"])
        with self.assertRaisesRegex(PassageClassificationError, "exact snippet quotation"):
            analytic_rows(
                [passage], {passage["passage_id"]: provider_result}, "sample-1", "jre"
            )


class BatchFileCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run_dir = Path(self.temporary.name)
        self.client = Mock()
        self.batch = SimpleNamespace(
            status="completed", output_file_id=None, error_file_id="file-errors",
            request_counts=SimpleNamespace(failed=1),
        )
        # Synthetic provider error: this is not evidence about the actual jobs.
        self.error_bytes = MODULE["jsonl_bytes"]([{
            "custom_id": "passage-0", "error": None,
            "response": {"status_code": 400, "body": {"error": {
                "code": "invalid_json_schema", "message": "Unsupported schema keyword",
            }}},
        }])
        self.client.files.content.return_value = SimpleNamespace(content=self.error_bytes)

    def test_all_failed_downloads_and_explains_error_without_output_id(self) -> None:
        with self.assertRaisesRegex(PassageClassificationError, "invalid_json_schema"):
            MODULE["download_batch_results"](self.client, self.batch, self.run_dir)
        self.assertEqual((self.run_dir / "batch_errors.jsonl").read_bytes(), self.error_bytes)
        self.client.files.content.assert_called_once_with("file-errors")
        self.assertFalse((self.run_dir / "claim_classification.csv").exists())

    def test_partial_success_preserves_both_provider_files(self) -> None:
        self.batch.output_file_id = "file-output"
        self.client.files.content.side_effect = [
            SimpleNamespace(content=self.error_bytes), SimpleNamespace(content=b"{}\n"),
        ]
        with self.assertRaisesRegex(PassageClassificationError, "1 failed request"):
            MODULE["download_batch_results"](self.client, self.batch, self.run_dir)
        self.assertTrue((self.run_dir / "batch_errors.jsonl").exists())
        self.assertEqual((self.run_dir / "batch_output.jsonl").read_bytes(), b"{}\n")

    def test_top_level_error_for_expired_batch_is_reported(self) -> None:
        self.batch.status = "expired"
        self.client.files.content.return_value = SimpleNamespace(content=MODULE["jsonl_bytes"]([{
            "custom_id": "passage-0", "response": None,
            "error": {"code": "batch_expired", "message": "Request could not finish"},
        }]))
        with self.assertRaisesRegex(PassageClassificationError, "batch_expired"):
            MODULE["download_batch_results"](self.client, self.batch, self.run_dir)

    def test_success_still_returns_the_output(self) -> None:
        self.batch.error_file_id = None
        self.batch.output_file_id = "file-output"
        self.batch.request_counts.failed = 0
        self.client.files.content.return_value = SimpleNamespace(content=b"{}\n")
        self.assertEqual(
            MODULE["download_batch_results"](self.client, self.batch, self.run_dir), b"{}\n"
        )

    def test_failed_count_without_error_file_never_publishes_results(self) -> None:
        self.batch.error_file_id = None
        with self.assertRaisesRegex(PassageClassificationError, "1 failed request"):
            MODULE["download_batch_results"](self.client, self.batch, self.run_dir)
        self.client.files.content.assert_not_called()


if __name__ == "__main__":
    unittest.main()
