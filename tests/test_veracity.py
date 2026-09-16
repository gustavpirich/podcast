import argparse
import copy
import csv
import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "code/12_classify_veracity.py"))
CONFIG = MODULE["load"](MODULE["CONFIG"])


def unit(unit_id="statement-a", claim_id="claim-a"):
    return {
        "statement_unit_id": unit_id, "exact_claim_text": "a test proposition",
        "representative_snippet_id": "window-1", "representative_snippet_text": "word " * 256,
        "representative_claim_instance_id": claim_id, "claim_instance_count": "1",
        "claim_instance_ids": claim_id, "source_span_status": "aligned",
        "show": "show", "episode_id": "episode", "published_date": "2026-01-01",
        "classification_reason": "Prior object rationale remains unchanged.",
        "human_note": "Existing researcher note",
    }


def instance(unit_id="statement-a", claim_id="claim-a"):
    return {"statement_unit_id": unit_id, "claim_instance_id": claim_id,
            "is_representative": "1", "episode_id": "episode", "existing_broad_status": "uncertain"}


def classification(unit_id="statement-a"):
    return {"statement_unit_id": unit_id, "health_scope": "health", "veracity_label": "supported",
            "danger_label": "no_clear_danger", "veracity_reason": "Claim meaning. Evidence basis. Category reason.",
            "danger_reason": "No clear harmful action identified.", "evidence_review_needed": "Verify the specific proposition."}


class VeracityTests(unittest.TestCase):
    def test_pilot_selection_reproducible_balanced_and_keeps_all_instances(self):
        units = [{**unit(f"s-{i}", f"c-{i}"), "show": "a" if i < 4 else "b",
                  "existing_claim_domain": "health"} for i in range(8)]
        instances = [instance(f"s-{i}", f"c-{i}") for i in range(8)]
        selected, linked = MODULE["select_pilot"](units, instances, 4)
        reversed_selected, _ = MODULE["select_pilot"](list(reversed(units)), instances, 4)
        self.assertEqual(selected, reversed_selected)
        self.assertEqual([row["show"] for row in selected], ["a", "b", "a", "b"])
        self.assertEqual({r["statement_unit_id"] for r in selected}, {r["statement_unit_id"] for r in linked})
        with self.assertRaises(ValueError):
            MODULE["select_pilot"](units, instances, 9)

    def validate(self, item, source=None):
        source = source or unit()
        MODULE["validate_result"]({"classifications": [item]}, {source["statement_unit_id"]: source}, CONFIG)

    def test_all_substantive_labels_and_independent_danger(self):
        for label in ("supported", "exaggerated", "unsupported", "contradicted", "uncertain"):
            for danger in ("dangerous", "no_clear_danger", "uncertain"):
                self.validate({**classification(), "veracity_label": label, "danger_label": danger})

    def test_scope_and_nonclaims_cannot_be_forced_into_truth_labels(self):
        for item in (
            {**classification(), "health_scope": "non_health"},
            {**classification(), "health_scope": "uncertain"},
            {**classification(), "veracity_label": "not_assessable"},
            {**classification(), "danger_label": "not_assessable"},
        ):
            with self.assertRaises(ValueError):
                self.validate(item)
        self.validate({**classification(), "health_scope": "non_health", "veracity_label": "not_applicable", "danger_label": "not_applicable"})
        self.validate({**classification(), "veracity_label": "not_assessable", "danger_label": "not_assessable"})

    def test_unmatched_quotation_requires_abstention(self):
        source = {**unit(), "source_span_status": "unmatched"}
        with self.assertRaises(ValueError):
            self.validate(classification(), source)
        self.validate({**classification(), "veracity_label": "not_assessable", "danger_label": "not_assessable"}, source)

    def test_missing_duplicate_and_unknown_ids_rejected(self):
        for values in ([], [classification(), classification()], [classification("statement-unknown")]):
            with self.assertRaises(ValueError):
                MODULE["validate_result"]({"classifications": values}, {"statement-a": unit()}, CONFIG)

    def test_invalid_enum_missing_reason_and_extra_fields_rejected(self):
        for item in ({**classification(), "veracity_label": "true"},
                     {**classification(), "veracity_reason": " "},
                     {**classification(), "invented_source": "fake"}):
            with self.assertRaises(ValueError):
                self.validate(item)

    def test_mapping_checks_dangling_duplicate_wrong_counts_and_representative(self):
        MODULE["validate_inputs"]([unit()], [instance()])
        for units, instances in (([unit()], [instance("unknown")]),
                                 ([unit()], [instance(), instance()]),
                                 ([{**unit(), "claim_instance_count": "2"}], [instance()]),
                                 ([unit()], [{**instance(), "is_representative": "0"}])):
            with self.assertRaises(ValueError):
                MODULE["validate_inputs"](units, instances)

    def test_requests_bound_size_and_hide_existing_judgments(self):
        units = [{**unit(f"statement-{i}", f"claim-{i}"), "existing_broad_status": "fringe"} for i in range(7)]
        requests = MODULE["make_requests"](units, CONFIG, "2026-09-16")
        self.assertEqual(len(requests), 3)
        ids = []
        for request in requests:
            self.assertNotIn("existing_broad_status", request["body"]["input"])
            payload = json.loads(request["body"]["input"])
            self.assertLessEqual(len(payload["statements"]), 3)
            ids.extend(row["statement_unit_id"] for row in payload["statements"])
        self.assertEqual(set(ids), {row["statement_unit_id"] for row in units})

    def test_augment_never_overwrites_previous_fields(self):
        rows = [unit()]
        original = copy.deepcopy(rows)
        output = MODULE["augment"](rows, {"statement-a": {"veracity_label": "uncertain"}})
        self.assertEqual(rows, original)
        for key, value in original[0].items():
            self.assertEqual(output[0][key], value)
        with self.assertRaises(ValueError):
            MODULE["augment"](rows, {"statement-a": {"human_note": "overwrite"}})

    def test_end_to_end_collect_is_order_independent_and_reproducible(self):
        units = [unit(), unit("statement-b", "claim-b")]
        instances = [instance(), instance("statement-b", "claim-b")]
        globals_ = MODULE["collect"].__globals__
        old_root = globals_["RUN_ROOT"]
        with tempfile.TemporaryDirectory() as tmp:
            globals_["RUN_ROOT"] = Path(tmp)
            try:
                run_id = "a" * 16
                run = Path(tmp) / run_id
                requests = MODULE["make_requests"](units, {**CONFIG, "statements_per_request": 1}, "2026-09-16")
                frozen = {"source_statement_units.csv": MODULE["csv_text"](units, list(units[0])),
                          "source_statement_instances.csv": MODULE["csv_text"](instances, list(instances[0])),
                          "config.json": json.dumps(CONFIG),
                          "batch_input.jsonl": "".join(json.dumps(row) + "\n" for row in requests)}
                for name, text in frozen.items():
                    MODULE["freeze"](run / name, text)
                MODULE["write"](run / "manifest.json", {"run_id": run_id, "assessment_date": "2026-09-16",
                    "files": {name: MODULE["digest"](text.encode()) for name, text in frozen.items()}})
                MODULE["write"](run / "batch_job.json", {"id": "batch-test"})
                MODULE["write"](run / "download_complete.json", {"status": "completed"})
                raw = []
                for request in reversed(requests):
                    source = json.loads(request["body"]["input"])["statements"][0]
                    raw.append({"custom_id": request["custom_id"], "response": {"status_code": 200, "body": {
                        "status": "completed", "id": "response-test", "model": CONFIG["model"],
                        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
                            {"classifications": [classification(source["statement_unit_id"])]})}]}]}}})
                MODULE["freeze"](run / "batch_output.jsonl", "".join(json.dumps(row) + "\n" for row in raw))
                args = argparse.Namespace(run_id=run_id)
                MODULE["collect"](args)
                original_bytes = (run / "statement_units.csv").read_bytes()
                MODULE["collect"](args)
                self.assertEqual(original_bytes, (run / "statement_units.csv").read_bytes())
                output = list(csv.DictReader(io.StringIO(original_bytes.decode())))
                for before, after in zip(units, output):
                    self.assertEqual(before, {key: after[key] for key in before})
                    self.assertEqual(after["veracity_label"], "supported")
                # A local review must survive collection, even when it differs from the blank export.
                (run / "statement_units.csv").write_text(original_bytes.decode().replace("Existing researcher note", "Updated review"))
                with self.assertRaises(ValueError):
                    MODULE["collect"](args)
                # Incomplete provider coverage cannot publish a partial final dataset.
                for name in ("statement_units.csv", "statement_instances.csv", "veracity_summary.csv"):
                    (run / name).unlink()
                (run / "batch_output.jsonl").write_text(json.dumps(raw[0]) + "\n")
                with self.assertRaisesRegex(ValueError, "1 requests remain unresolved"):
                    MODULE["collect"](args)
                self.assertFalse((run / "statement_units.csv").exists())
                self.assertEqual(len(MODULE["load"](run / "pending_requests.json")), 1)
                # Duplicate provider IDs cannot silently overwrite another result.
                (run / "batch_output.jsonl").write_text((json.dumps(raw[0]) + "\n") * 2)
                with self.assertRaisesRegex(ValueError, "duplicate Batch result"):
                    MODULE["collect"](args)
            finally:
                globals_["RUN_ROOT"] = old_root

    def test_duplicate_csv_headers_rejected(self):
        with self.assertRaises(ValueError):
            MODULE["read_csv"]("id,id\na,b\n")


if __name__ == "__main__":
    unittest.main()
