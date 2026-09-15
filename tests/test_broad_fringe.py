"""Substantive outcome/denominator checks for the broad-fringe implementation."""
import json
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "code/08_classify_broad_fringe.py"))
P = runpy.run_path(str(ROOT / "code/09_plot_fringe_extent.py"))
CONFIG = json.loads((ROOT / "config/broad_fringe_classification.json").read_text())


def claim(position="mainstream", exaggeration="no", stance="asserted", text="A specific test claim."):
    return {"exact_claim_text": text, "claim_domain": "science", "scientific_position": position,
            "exaggeration": exaggeration, "stance": stance,
            "reason": "Synthetic test explanation; not an evidence assessment."}


class BroadFringeTests(unittest.TestCase):
    def test_emerging_claim_counts_even_when_responsibly_qualified(self):
        self.assertEqual(M["broad_flag"](claim("emerging_non_mainstream", "no", "tentative")), "fringe")

    def test_mainstream_claim_can_be_exaggerated(self):
        self.assertEqual(M["broad_flag"](claim("mainstream", "yes")), "fringe")

    def test_unknown_is_not_recoded_as_fringe(self):
        self.assertEqual(M["broad_flag"](claim("uncertain", "no")), "uncertain")
        self.assertEqual(M["broad_flag"](claim("mainstream", "uncertain")), "uncertain")
        self.assertEqual(M["broad_flag"](claim("mainstream", "no")), "not_fringe")

    def test_positive_dimension_not_erased_by_other_unknown_dimension(self):
        self.assertEqual(M["broad_flag"](claim("uncertain", "yes")), "fringe")

    def row(self, c):
        window = {"snippet_id": "test-window-000000", "health_related": 1, "science_related": 0,
                  "snippet_text": "A specific test claim."}
        return M["make_rows"]([window], {window["snippet_id"]: {"claims": [c]}})[0]

    def test_debunked_claim_present_but_not_advanced(self):
        row = self.row(claim("contradicts_consensus", "no", "rejected"))
        self.assertEqual(row["broad_status"], "fringe")
        self.assertEqual(row["advanced_status"], "not_fringe")

    def test_unclear_stance_not_counted_as_assertion(self):
        row = self.row(claim("alternative_speculative", "no", "unclear"))
        self.assertEqual(row["broad_status"], "fringe")
        self.assertEqual(row["advanced_status"], "uncertain")

    def test_unmatched_quote_cannot_establish_positive(self):
        row = self.row(claim("contradicts_consensus", text="Absent from source."))
        self.assertEqual(row["broad_status"], "uncertain")
        self.assertEqual(row["unmatched_claim_count"], 1)
        self.assertEqual(json.loads(row["claims_json"])[0]["model_broad_status"], "fringe")

    def test_missing_request_is_not_silently_a_negative(self):
        with self.assertRaises(ValueError):
            M["make_rows"]([{"snippet_id": "missing", "health_related": 1, "science_related": 0}], {})

    def test_duplicate_or_invalid_results_rejected(self):
        valid = {"snippet_id": "test", "claims": [claim()]}
        M["validate"](valid, "test", CONFIG)
        valid["claims"].append(claim())
        with self.assertRaises(ValueError):
            M["validate"](valid, "test", CONFIG)

    def test_long_explanation_preserved_and_flagged_without_changing_classification(self):
        c = claim("emerging_non_mainstream")
        c["reason"] = " ".join(["word"] * 84)
        M["validate"]({"snippet_id": "test", "claims": [c]}, "test", CONFIG)
        row = self.row(c)
        self.assertEqual(row["broad_status"], "fringe")
        self.assertEqual(row["long_explanation_count"], 1)
        self.assertEqual(json.loads(row["claims_json"])[0]["reason"], c["reason"])

    def test_pooled_rates_use_counts_not_average_of_episode_percentages(self):
        episodes = [{"show": "jre", "windows": 100, "screen_positive_windows": 50, "fringe_windows": 10,
                     "uncertain_windows": 0, "flagged_pct_all_windows": 10, "definition": "test"},
                    {"show": "jre", "windows": 300, "screen_positive_windows": 100, "fringe_windows": 90,
                     "uncertain_windows": 10, "flagged_pct_all_windows": 30, "definition": "test"}]
        row = P["show_summary"](episodes)[0]
        self.assertEqual(row["pooled_flagged_pct_all_windows"], 25)
        self.assertAlmostEqual(row["pooled_flagged_pct_screen_positive_windows"], 100 * 100 / 150)
        self.assertEqual(row["mean_episode_flagged_pct"], 20)

    def test_category_counts_are_per_window_nonexclusive_and_exclude_unmatched(self):
        c = {"scientific_position": "emerging_non_mainstream", "exaggeration": "yes", "quote_match_method": "exact"}
        unmatched = {"scientific_position": "contradicts_consensus", "exaggeration": "no", "quote_match_method": "unmatched"}
        groups = {("jre", "synthetic"): [{"claims_json": json.dumps([c, c, unmatched])}, {"claims_json": "[]"}]}
        rows = {r["category"]: r for r in P["category_summary"](groups)}
        self.assertEqual(rows["emerging_non_mainstream"]["windows_with_category"], 1)
        self.assertEqual(rows["exaggerated"]["pct_all_windows"], 50)
        self.assertEqual(rows["contradicts_consensus"]["windows_with_category"], 0)


if __name__ == "__main__":
    unittest.main()
