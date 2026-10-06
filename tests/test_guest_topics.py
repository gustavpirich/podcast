"""Tests for the RSS health/science flags of guest rows."""

from __future__ import annotations

import json
import re
import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOPICS = runpy.run_path(str(ROOT / "code/19_flag_guest_topics.py"))
CONFIG = json.loads((ROOT / "config/rss_topic_terms.json").read_text(encoding="utf-8"))
HEALTH = TOPICS["compile_terms"](CONFIG["health_terms"], CONFIG["health_prefixes"])
SCIENCE = TOPICS["compile_terms"](CONFIG["science_terms"], CONFIG["science_prefixes"])
EXCLUDE = re.compile("|".join(re.escape(p) for p in CONFIG["exclude_phrases"]), re.IGNORECASE)
ADS = re.compile(CONFIG["ad_sentence_pattern"], re.IGNORECASE)


class TermTest(unittest.TestCase):
    def test_whole_words_and_prefixes(self) -> None:
        matches = TOPICS["matches"]
        self.assertEqual(matches(HEALTH, "They talk about his sobriety and therapy.", set()), ["sobriety", "therapy"])
        self.assertEqual(matches(HEALTH, "A healthcare startup", set()), [])
        self.assertEqual(matches(SCIENCE, "a professor of neurobiology", set()), ["neurobiology"])

    def test_exclusions(self) -> None:
        matches = TOPICS["matches"]
        self.assertEqual(matches(SCIENCE, "the 1992 science fiction film Freejack", set(), EXCLUDE), [])
        self.assertEqual(matches(HEALTH, "JD becomes a doctor", {"doctor"}), [])


class TextTest(unittest.TestCase):
    def test_ads_and_repeated_sentences_removed(self) -> None:
        texts = ["Guest talks about sleep. Order Paul's book: Recollections of Trauma",
                 "Guest talks about films. Order Paul's book: Recollections of Trauma",
                 "Guest talks about food. Order Paul's book: Recollections of Trauma"]
        repeated = TOPICS["boilerplate"](texts, 3, 0.02)
        kept = TOPICS["content_sentences"](texts[0] + " Go to betterhelp.com/x for therapy.", ADS, repeated)
        self.assertEqual(kept, ["Guest talks about sleep."])

    def test_guest_text_keeps_only_guest_segments(self) -> None:
        title = "Brent Pella on Hippies + Rex Chapman on Addiction"
        self.assertEqual(TOPICS["guest_text"]("Brent Pella", title, []), "Brent Pella on Hippies")
        pieces = ["Intro.", "Rex Chapman joins the show.", "They discuss his addiction.", "Then news."]
        self.assertEqual(TOPICS["guest_text"]("Rex Chapman", "Show", pieces),
                         "Rex Chapman joins the show. They discuss his addiction.")


if __name__ == "__main__":
    unittest.main()
