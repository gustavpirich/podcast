"""Tests for the popular-podcast frame: show matching, categories and episode rules."""

from __future__ import annotations

import runpy
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAME = runpy.run_path(str(ROOT / "code/01_build_popular_episode_frame.py"))
MATCH = runpy.run_path(str(ROOT / "code/01_match_apple_podcasts.py"))
EDISON = runpy.run_path(str(ROOT / "code/01_snapshot_edison_top50.py"))

FEED = b"""<?xml version="1.0"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
  <itunes:category text="Health &amp; Fitness"><itunes:category text="Mental Health"/></itunes:category>
  <itunes:category text="Comedy"/>
  <item><title>In window</title><guid>a</guid><pubDate>Wed, 02 Jan 2019 10:00:00 GMT</pubDate>
    <itunes:duration>01:30:00</itunes:duration><enclosure url="https://x/a.mp3" type="audio/mpeg"/></item>
  <item><title>Trailer</title><guid>b</guid><pubDate>Thu, 03 Jan 2019 10:00:00 GMT</pubDate>
    <itunes:episodeType>trailer</itunes:episodeType><enclosure url="https://x/b.mp3"/></item>
  <item><title>Too early</title><guid>c</guid><pubDate>Mon, 31 Dec 2018 23:00:00 GMT</pubDate>
    <itunes:duration>600</itunes:duration><enclosure url="https://x/c.mp3"/></item>
</channel></rss>"""


class CategoryTest(unittest.TestCase):
    def test_primary_category_is_the_first_one(self) -> None:
        channel = ET.fromstring(FEED).find("channel")
        pairs = FRAME["categories"](channel)
        self.assertEqual(pairs[0], ("Health & Fitness", "Mental Health"))
        self.assertTrue(FRAME["genre_included"](pairs[0]))

    def test_frame_rule(self) -> None:
        included = FRAME["genre_included"]
        self.assertTrue(included(("Comedy", "Comedy Interviews")))
        self.assertTrue(included(("Education", "Self-Improvement")))
        self.assertFalse(included(("Education", "How To")))
        self.assertFalse(included(("Society & Culture", None)))
        self.assertFalse(included(None))


class EpisodeTest(unittest.TestCase):
    def test_items_window_and_types(self) -> None:
        channel = ET.fromstring(FEED).find("channel")
        items = FRAME["parse_items"](channel, "demo")
        by_title = {item["title"]: item for item in items}
        self.assertEqual(by_title["In window"]["duration_seconds"], 5400)
        self.assertEqual(by_title["Trailer"]["episode_type"], "trailer")
        self.assertTrue(FRAME["in_window"](by_title["In window"]))
        self.assertFalse(FRAME["in_window"](by_title["Too early"]))
        self.assertTrue(by_title["In window"]["episode_id"].startswith("demo-"))

    def test_median_for_long_form_rule(self) -> None:
        median = FRAME["median"]
        self.assertEqual(median([30, 90, 120]), 90)
        self.assertEqual(median([40, 80]), 60)
        self.assertIsNone(median([]))

    def test_duration_formats(self) -> None:
        parse = FRAME["parse_duration"]
        self.assertEqual(parse("3600"), 3600)
        self.assertEqual(parse("45:30"), 2730)
        self.assertEqual(parse("1:02:03"), 3723)
        self.assertIsNone(parse(""))
        self.assertIsNone(parse("about an hour"))


class MatchTest(unittest.TestCase):
    def test_exact_match_ignores_punctuation_and_leading_the(self) -> None:
        ranked = MATCH["rank_candidates"](
            ["The Joe Rogan Experience"],
            [{"collectionName": "Joe Rogan Experience Fan Clips", "trackCount": 900},
             {"collectionName": "The Joe Rogan Experience", "trackCount": 2600}],
        )
        self.assertEqual(ranked[0]["collectionName"], "The Joe Rogan Experience")
        self.assertEqual(ranked[0]["match"], "exact")
        self.assertEqual(ranked[1]["match"], "review")

    def test_ampersand_and_with(self) -> None:
        normalize = MATCH["normalize"]
        self.assertEqual(normalize("New Heights with Jason & Travis Kelce"),
                         normalize("New Heights with Jason and Travis Kelce"))
        self.assertEqual(normalize("This Past Weekend w/ Theo Von"), normalize("This Past Weekend with Theo Von"))


class EdisonImageTest(unittest.TestCase):
    def test_only_top_50_images_are_selected(self) -> None:
        html = ('<img src="/wp-content/uploads/logo.png"><img class="x" src="/wp-content/uploads/top-50-q1-24.png">'
                '<img data-src="/wp-content/uploads/Top-50-lazy.png">')
        found = EDISON["ranking_images"](html, "https://ssrs.com/news/page/")
        self.assertEqual(found, ["https://ssrs.com/wp-content/uploads/top-50-q1-24.png"])


if __name__ == "__main__":
    unittest.main()
