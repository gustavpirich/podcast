"""Tests for transcript formatting that do not call AssemblyAI."""

from __future__ import annotations

import gzip
import json
import runpy
import tempfile
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
WINDOW_MODULE = runpy.run_path(
    str(
        Path(__file__).resolve().parents[1]
        / "code"
        / "04_classify_content_openai_batch.py"
    )
)
format_timestamp = MODULE["format_timestamp"]
known_speakers = MODULE["known_speakers"]
markdown_transcript = MODULE["markdown_transcript"]
normalized_document = MODULE["normalized_document"]
parse_upload_response = MODULE["parse_upload_response"]
sanitized_provider_error = MODULE["sanitized_provider_error"]
atomic_write_json_gzip = MODULE["atomic_write_json_gzip"]
resolve_rss_audio_url = MODULE["resolve_rss_audio_url"]
load_window_transcript = WINDOW_MODULE["load_transcript"]
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

    def test_rss_direct_batch_command_uses_episode_id(self) -> None:
        episode = BatchEpisode(
            video_id="jre-2553",
            rss_guid="example-guid",
            guest_name="Guest",
            title="#2553 - Guest",
            duration_seconds=60.0,
            state="ready",
        )
        command = episode_command(
            "the_joe_rogan_experience",
            episode,
            submit_only=True,
            retry_failed=False,
            delivery="rss-direct",
        )
        self.assertIn("--episode-id", command)
        self.assertIn("jre-2553", command)
        self.assertIn("rss-direct", command)

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

    def test_failed_name_identification_keeps_generic_diarized_speakers(self) -> None:
        response = {
            "id": "example-id",
            "status": "completed",
            "speech_understanding": None,
            "utterances": [
                {"start": 0, "speaker": "A", "text": "Hello."},
                {"start": 1000, "speaker": "B", "text": "Hi."},
            ],
        }
        metadata = {
            "episode_id": "episode-1",
            "episode": {"title": "Example"},
            "podcast": {"name": "Example show"},
        }
        speakers = [
            {"name": "Host", "role": "Host"},
            {"name": "Guest", "role": "Guest"},
        ]

        document = normalized_document(
            response,
            metadata,
            speakers,
            None,
            speaker_identification_status="failure",
            speaker_identification_error="provider failure",
        )

        self.assertEqual(
            document["speakers"],
            [
                {"id": "A", "name": "A", "role": "Unidentified"},
                {"id": "B", "name": "B", "role": "Unidentified"},
            ],
        )
        self.assertEqual(
            document["transcription"]["speaker_identification_status"],
            "failure",
        )
        self.assertIn("A (Unidentified)", markdown_transcript(document))


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


class SparseStorageTests(unittest.TestCase):
    def test_compressed_json_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.json.gz"
            expected = {"utterances": [{"text": "hello"}]}
            atomic_write_json_gzip(path, expected)
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), expected)
            self.assertEqual(load_window_transcript(path), expected)

    def test_rss_delivery_uses_recorded_enclosure(self) -> None:
        metadata = {
            "episode": {
                "guid": "episode-guid",
                "enclosure_url": "https://example.org/episode.mp3",
                "enclosure_type": "audio/mpeg",
            }
        }
        url, details = resolve_rss_audio_url(metadata)
        self.assertEqual(url, "https://example.org/episode.mp3")
        self.assertEqual(details["method"], "rss_enclosure_url")
        self.assertNotIn("enclosure_url", details)


if __name__ == "__main__":
    unittest.main()
