"""Tests for the rule-based guest extraction from RSS titles and descriptions."""

from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUESTS = runpy.run_path(str(ROOT / "code/18_build_guest_dataset.py"))
RULES = json.loads((ROOT / "config/guest_rules.json").read_text(encoding="utf-8"))


def show(show_id: str, name: str, hosts: list[str]):
    return GUESTS["Show"](show_id, name, hosts, RULES["shows"][show_id], RULES["all"])


class TidyTest(unittest.TestCase):
    def test_capitals_and_decoration(self) -> None:
        tidy = GUESTS["tidy"]
        self.assertEqual(tidy("HARLAND WILLIAMS"), "Harland Williams")
        self.assertEqual(tidy("Mark Ronson Returns"), "Mark Ronson")
        self.assertEqual(tidy("Darby Saxbe (on Dad Brain)"), "Darby Saxbe")
        self.assertEqual(tidy("Jeff Ross on The End of Roasting"), "Jeff Ross")
        self.assertEqual(tidy("Robbie Robertson Talks Martin Scorsese"), "Robbie Robertson")

    def test_name_rule(self) -> None:
        is_name = GUESTS["is_name"]
        self.assertTrue(is_name("Dr. Karen Parker", allow_single=False))
        self.assertFalse(is_name("Godfrey", allow_single=False))
        self.assertTrue(is_name("Godfrey", allow_single=True))
        self.assertFalse(is_name("The Best Of Season 9", allow_single=True))
        self.assertFalse(is_name("Storming Area 51", allow_single=True))


class TitleTest(unittest.TestCase):
    def test_jre_number_slot(self) -> None:
        jre = show("jre", "The Joe Rogan Experience", ["Joe Rogan"])
        self.assertEqual(GUESTS["title_guests"](jre, "#2426 - Cameron Hanes & Adam Greentree", ""),
                         (["Cameron Hanes", "Adam Greentree"], "jre_number"))

    def test_hosts_are_not_guests(self) -> None:
        bears = show("2_bears_1_cave_with_tom_segura_bert_kreischer", "2 Bears 1 Cave", ["Tom Segura", "Bert Kreischer"])
        names, _ = GUESTS["title_guests"](bears, "Ep. 96 | 2 Bears 1 Cave w/ Tom Segura & Roy Wood Jr.", "")
        self.assertEqual(names, ["Roy Wood Jr"])
        names, _ = GUESTS["title_guests"](bears, "Ep. 72 | 2 Bears 1 Cave w/ Tom Segura & Bert Kreischer", "")
        self.assertEqual(names, [])

    def test_loose_rule_needs_description(self) -> None:
        theo = show("this_past_weekend_w_theo_von", "This Past Weekend", ["Theo Von"])
        title = GUESTS["title_guests"]
        self.assertEqual(title(theo, "E504 Matt McCusker", "Matt McCusker is a stand-up comedian")[0], ["Matt McCusker"])
        self.assertEqual(title(theo, "E413 Cold Beach", "Theo is back with another solo episode.")[0], [])

    def test_kill_tony_drops_cities(self) -> None:
        kt = show("kill_tony", "KILL TONY", ["Tony Hinchcliffe", "Brian Redban"])
        names, _ = GUESTS["title_guests"](kt, "#495 - MIAMI - BENJI AFLALO",
                                          "Benji Aflalo, William Montgomery, Tony Hinchcliffe, Brian Redban")
        self.assertEqual(names, ["Benji Aflalo"])


class DescriptionTest(unittest.TestCase):
    def test_description_phrases(self) -> None:
        burr = show("monday_morning_podcast", "Bill Burr's Monday Morning Podcast", ["Bill Burr"])
        names, rule, _ = GUESTS["description_guests"](burr, "Bill rambles with Nimesh Patel about his new special.")
        self.assertEqual((names, rule), (["Nimesh Patel"], "desc_talks_with"))
        names, _, _ = GUESTS["description_guests"](burr, "Bill rambles about Easter, fruit, and the Book of Job.")
        self.assertEqual(names, [])


if __name__ == "__main__":
    unittest.main()
