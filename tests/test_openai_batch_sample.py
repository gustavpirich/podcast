"""Tests for the frozen-sample OpenAI Batch runner."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(
    str(PROJECT_ROOT / "code" / "04_classify_content_openai_batch_sample.py")
)
child_command = MODULE["child_command"]
Episode = MODULE["Episode"]


class SampleRunnerTests(unittest.TestCase):
    def test_child_command_preserves_episode_and_run_identifiers(self) -> None:
        episode = Episode("abcdefghijk", "Title", 768, 5, "run123", "prepared")
        command = child_command("submit", "show_folder", episode, True)
        self.assertIn("--show-directory", command)
        self.assertIn("show_folder", command)
        self.assertIn("--video-id", command)
        self.assertIn("abcdefghijk", command)
        self.assertIn("--run-id", command)
        self.assertIn("run123", command)
        self.assertEqual(command[-1], "--yes")

    def test_prepare_does_not_reuse_a_stale_run_id(self) -> None:
        episode = Episode("abcdefghijk", "Title", 768, 5, "oldrun", "collected")
        command = child_command("prepare", "show_folder", episode, False)
        self.assertNotIn("--run-id", command)


if __name__ == "__main__":
    unittest.main()
