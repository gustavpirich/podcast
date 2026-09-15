import runpy
import unittest
from pathlib import Path


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "code/10_classify_health_objects.py"))


def row(snippet_id, window_id, text, claims):
    return {
        "snippet_id": snippet_id,
        "show": "show", "episode_id": "episode", "episode_title": "Title",
        "guest": "Guest", "published_date": "2026-01-01",
        "window_id": str(window_id), "word_start_index": str(window_id * 128),
        "word_end_index_exclusive": str(window_id * 128 + 256),
        "start_ms": "0", "end_ms": "1000", "snippet_text": text,
        "claims_json": MODULE["canonical"](claims), "claim_count": str(len(claims)),
        "health_related": "1", "science_related": "0",
    }


def claim(claim_id, quote, method="exact"):
    return {
        "claim_id": claim_id, "exact_claim_text": quote,
        "model_claim_text": quote, "quote_match_method": method,
        "claim_domain": "health",
    }


def words(start, count=256):
    return " ".join(f"word{i}" for i in range(start, start + count))


class StatementUnitTests(unittest.TestCase):
    def test_overlap_repetition_maps_to_one_unit(self):
        text0, text1 = words(0), words(128)
        quote = "word140 word141 word142"
        units, instances = MODULE["build_statement_units"]([
            row("window-0", 0, text0, [claim("claim-a", quote)]),
            row("window-1", 1, text1, [claim("claim-b", quote)]),
        ])
        self.assertEqual(len(units), 1)
        self.assertEqual(len(instances), 2)
        self.assertEqual(units[0]["source_word_start"], 140)
        self.assertEqual(units[0]["claim_instance_count"], 2)

    def test_representative_is_most_centered_window(self):
        quote = "word200 word201"
        units, _ = MODULE["build_statement_units"]([
            row("window-0", 0, words(0), [claim("claim-a", quote)]),
            row("window-1", 1, words(128), [claim("claim-b", quote)]),
        ])
        self.assertEqual(units[0]["representative_snippet_id"], "window-1")

    def test_unmatched_claims_remain_singletons(self):
        units, instances = MODULE["build_statement_units"]([
            row("window-0", 0, words(0), [
                claim("claim-a", "not in source", "unmatched"),
                claim("claim-b", "not in source", "unmatched"),
            ])
        ])
        self.assertEqual(len(units), 2)
        self.assertTrue(all(unit["source_span_status"] == "unmatched" for unit in units))
        self.assertEqual(len({item["statement_unit_id"] for item in instances}), 2)

    def test_repeated_quote_inside_one_window_is_ambiguous(self):
        text = ("same quote " * 128).strip()
        units, _ = MODULE["build_statement_units"]([
            row("window-0", 0, text, [claim("claim-a", "same quote")])
        ])
        self.assertEqual(units[0]["source_span_status"], "ambiguous_location")

    def test_every_instance_has_one_unit(self):
        units, instances = MODULE["build_statement_units"]([
            row("window-0", 0, words(0), [claim("a", "word10"), claim("b", "word20")])
        ])
        self.assertEqual(sum(unit["claim_instance_count"] for unit in units), len(instances))
        self.assertTrue(all(item["statement_unit_id"] for item in instances))


class ClassificationValidationTests(unittest.TestCase):
    def setUp(self):
        self.config = MODULE["load"](MODULE["CONFIG"])
        self.base = {
            "statement_unit_id": "statement-1",
            "extraction_quality": "atomic_checkable",
            "primary_object": "vaccines_immunization",
            "secondary_objects": [],
            "claim_focus": "risk_safety",
            "product_maturity": "established_marketed",
            "classification_reason": "The statement concerns vaccine safety and describes a possible adverse outcome.",
        }

    def validate(self, item):
        MODULE["validate_classification"](
            {"snippet_id": "window", "classifications": [item]},
            "window", {"statement-1"}, self.config,
        )

    def test_valid_product_classification(self):
        self.validate(self.base)

    def test_secondary_must_be_distinct_from_primary(self):
        item = {**self.base, "secondary_objects": ["vaccines_immunization"]}
        with self.assertRaises(ValueError):
            self.validate(item)

    def test_no_more_than_two_secondary_objects(self):
        item = {**self.base, "secondary_objects": [
            "disease_condition", "healthcare_public_health", "other_health"
        ]}
        with self.assertRaises(ValueError):
            self.validate(item)

    def test_nonclaim_combination_is_conservative(self):
        item = {
            **self.base, "extraction_quality": "not_checkable",
            "primary_object": "unclear", "secondary_objects": [],
            "claim_focus": "unclear", "product_maturity": "not_applicable",
        }
        self.validate(item)

    def test_nonclaim_cannot_receive_product_category(self):
        item = {**self.base, "extraction_quality": "not_checkable"}
        with self.assertRaises(ValueError):
            self.validate(item)

    def test_unclear_fragment_can_retain_observable_focus(self):
        item = {
            **self.base, "extraction_quality": "unclear_fragment",
            "primary_object": "unclear", "claim_focus": "regulation_policy",
            "product_maturity": "not_applicable",
        }
        self.validate(item)

    def test_missing_unit_fails(self):
        value = {"snippet_id": "window", "classifications": []}
        with self.assertRaises(ValueError):
            MODULE["validate_classification"](value, "window", {"statement-1"}, self.config)

    def test_small_opaque_id_corruption_is_uniquely_recovered(self):
        value = {"snippet_id": "window", "classifications": [
            {**self.base, "statement_unit_id": "statement-1234567890abcde"}
        ]}
        recovered, count = MODULE["recover_statement_ids"](
            value, {"statement-1234567890abcdef"}
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            recovered["classifications"][0]["statement_unit_id"],
            "statement-1234567890abcdef",
        )

    def test_ambiguous_id_recovery_does_not_guess(self):
        value = {"snippet_id": "window", "classifications": [
            {**self.base, "statement_unit_id": "statement-1234567890abcde"}
        ]}
        recovered, count = MODULE["recover_statement_ids"](
            value, {"statement-1234567890abcdef", "statement-1234567890abcdeg"}
        )
        self.assertEqual(count, 0)
        self.assertEqual(recovered["classifications"][0]["statement_unit_id"], "statement-1234567890abcde")

    def test_provider_custom_id_remains_authoritative_for_snippet(self):
        item = {**self.base}
        value = {"snippet_id": "corrupted", "classifications": [item]}
        value["snippet_id"] = "window"
        MODULE["validate_classification"](value, "window", {"statement-1"}, self.config)

    def test_summary_keeps_unique_and_instance_denominators(self):
        units = [{"primary_object": "vaccines_immunization"}, {"primary_object": "other_health"}]
        instances = [
            {"primary_object": "vaccines_immunization"},
            {"primary_object": "vaccines_immunization"},
            {"primary_object": "other_health"},
        ]
        summary = MODULE["summary_rows"](
            units, instances, "primary_object", ["vaccines_immunization", "other_health"]
        )
        self.assertEqual(summary[0]["unique_statement_units"], 1)
        self.assertEqual(summary[0]["claim_instances"], 2)
        self.assertEqual(summary[0]["unique_statement_percent"], 50.0)


if __name__ == "__main__":
    unittest.main()
