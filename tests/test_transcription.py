"""Tests for transcript formatting that do not call AssemblyAI."""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "code" / "02_transcribe_assemblyai.py")
)
BATCH_MODULE = runpy.run_path(
    str(
        Path(__file__).resolve().parents[1]
        / "code"
        / "02_transcribe_assemblyai_batch.py"
    )
)
format_timestamp = MODULE["format_timestamp"]
known_speakers = MODULE["known_speakers"]
markdown_transcript = MODULE["markdown_transcript"]
parse_upload_response = MODULE["parse_upload_response"]
sanitized_provider_error = MODULE["sanitized_provider_error"]
BatchEpisode = BATCH_MODULE["BatchEpisode"]
episode_command = BATCH_MODULE["episode_command"]
load_batch = BATCH_MODULE["load_batch"]


class TimestampTests(unittest.TestCase):
    def test_milliseconds_become_hours_minutes_seconds(self) -> None:
        self.assertEqual(format_timestamp(3_723_999), "01:02:03")


class SpeakerMetadataTests(unittest.TestCase):
    def test_host_and_guest_are_derived_from_metadata(self) -> None:
        metadata = {
            "podcast": {
                "hosts": ["Joe Rogan"],
                "guest_label_candidate": "Rick Springfield",
            }
        }
        self.assertEqual(
            [(item["name"], item["role"]) for item in known_speakers(metadata)],
            [("Joe Rogan", "Host"), ("Rick Springfield", "Guest")],
        )

    def test_curated_guest_can_supplement_immutable_metadata(self) -> None:
        metadata = {"podcast": {"hosts": ["Steven Bartlett"]}}
        self.assertEqual(
            [(item["name"], item["role"]) for item in known_speakers(metadata, "Guest")],
            [("Steven Bartlett", "Host"), ("Guest", "Guest")],
        )


class BatchCommandTests(unittest.TestCase):
    def test_batch_child_command_contains_no_api_key(self) -> None:
        episode = BatchEpisode(
            video_id="MGxcosNuC8k",
            rss_guid="example-guid",
            guest_name="Andrew Huberman",
            title="Example",
            duration_seconds=60.0,
            state="ready",
        )
        command = episode_command(
            "the_diary_of_a_ceo",
            episode,
            submit_only=True,
            retry_failed=False,
        )
        self.assertIn("--guest-name", command)
        self.assertIn("Andrew Huberman", command)
        self.assertIn("--submit-only", command)
        self.assertNotIn("ASSEMBLYAI_API_KEY", " ".join(command))

    def test_jre_batch_uses_the_configured_host(self) -> None:
        show_id, _, hosts, episodes = load_batch(
            Path(__file__).resolve().parents[1]
            / "config"
            / "jre_starter_sample.json"
        )
        self.assertEqual(show_id, "jre")
        self.assertEqual(hosts, ("Joe Rogan",))
        self.assertEqual(len(episodes), 10)


class MarkdownTests(unittest.TestCase):
    def test_transcript_contains_timestamp_name_role_and_text(self) -> None:
        document = {
            "episode": {
                "title": "#2550 - Rick Springfield",
                "podcast": "The Joe Rogan Experience",
                "published_at": "2026-09-08T15:00:00+00:00",
                "source_url": "https://www.youtube.com/watch?v=BAhcDwMGKYU",
            },
            "transcription": {
                "transcript_id": "example-id",
                "speech_model_used": "universal-3-5-pro",
                "audio_duration_seconds": 3723.9,
            },
            "speakers": [
                {"id": "A", "name": "Joe Rogan", "role": "Host"},
            ],
            "utterances": [
                {"start": 3723999, "speaker": "Joe Rogan", "text": "Hello."}
            ],
        }
        result = markdown_transcript(document)
        self.assertIn('duration: "01:02:03"', result)
        self.assertIn("**[01:02:03] Joe Rogan (Host):** Hello.", result)
        self.assertIn("speaker_identities_human_verified: false", result)


class UploadResponseTests(unittest.TestCase):
    def test_upload_url_is_read_from_provider_json(self) -> None:
        result = parse_upload_response(
            '{"upload_url":"https://cdn.assemblyai.com/upload/example"}'
        )
        self.assertEqual(result, "https://cdn.assemblyai.com/upload/example")


class SafeErrorTests(unittest.TestCase):
    def test_temporary_signed_url_is_not_printed(self) -> None:
        error = RuntimeError(
            "failed [https://googlevideo.example/file?ip=private&sig=secret]: invalid"
        )
        result = sanitized_provider_error(error)
        self.assertEqual(result, "failed [temporary media URL omitted]: invalid")
        self.assertNotIn("private", result)
        self.assertNotIn("secret", result)


if __name__ == "__main__":
    unittest.main()
