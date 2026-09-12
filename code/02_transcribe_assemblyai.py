#!/usr/bin/env python3
"""Transcribe one raw podcast episode with AssemblyAI.

INPUTS (read only)
    data/raw/transcripts/<show-directory>/<video-id>/<video-id>.m4a
    data/raw/transcripts/<show-directory>/<video-id>/rss_metadata.json

OUTPUTS (reproducible derived data)
    data/derived/transcripts/<show-directory>/<video-id>/transcript.md
    data/derived/transcripts/<show-directory>/<video-id>/transcript.json
    data/derived/transcripts/<show-directory>/<video-id>/assemblyai_response.json

The script first uses the official AssemblyAI SDK for transcription and speaker
diarization. It then calls AssemblyAI's Speech Understanding endpoint to map
the generic speaker labels to the known names. The separate identification call
lets us request medium effort, which version 1.3.0 of the SDK does not expose.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_TRANSCRIPTS = PROJECT_ROOT / "data" / "raw" / "transcripts"
DERIVED_TRANSCRIPTS = PROJECT_ROOT / "data" / "derived" / "transcripts"
ASSEMBLYAI_API_BASE_URL = "https://api.assemblyai.com"
ASSEMBLYAI_UNDERSTANDING_URL = (
    "https://llm-gateway.assemblyai.com/v1/understanding"
)
SPEECH_MODELS = ["universal-3-5-pro", "universal-2"]


class TranscriptionError(RuntimeError):
    """An expected input, configuration, or provider failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    """Write a complete JSON document without leaving a partial final file."""

    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_timestamp(milliseconds: int | float) -> str:
    """Convert AssemblyAI milliseconds to a stable HH:MM:SS timestamp."""

    total_seconds = max(0, int(milliseconds) // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def yaml_string(value: Any) -> str:
    """JSON strings are valid YAML strings and need no extra dependency."""

    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def load_inputs(show_directory: str, video_id: str) -> tuple[Path, Path, dict[str, Any]]:
    episode_dir = RAW_TRANSCRIPTS / show_directory / video_id
    audio_path = episode_dir / f"{video_id}.m4a"
    metadata_path = episode_dir / "rss_metadata.json"

    if not audio_path.is_file():
        raise TranscriptionError(f"Input audio does not exist: {audio_path}")
    if not metadata_path.is_file():
        raise TranscriptionError(f"Input metadata does not exist: {metadata_path}")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TranscriptionError(f"Input metadata is not valid JSON: {metadata_path}") from exc

    recorded_path = metadata.get("media", {}).get("relative_path")
    if recorded_path and (PROJECT_ROOT / recorded_path).resolve() != audio_path.resolve():
        raise TranscriptionError("Metadata points to a different audio file")

    expected_hash = metadata.get("media", {}).get("sha256")
    if expected_hash and sha256_file(audio_path) != expected_hash:
        raise TranscriptionError(
            "The raw audio SHA-256 no longer matches rss_metadata.json; "
            "the immutable input may have changed"
        )
    return audio_path, metadata_path, metadata


def known_speakers(
    metadata: dict[str, Any], guest_name: str | None = None
) -> list[dict[str, str]]:
    """Build the requested name roster without modifying immutable raw metadata."""

    podcast = metadata.get("podcast", {})
    hosts = podcast.get("hosts") or []
    guest = guest_name or podcast.get("guest_label_candidate")
    speakers: list[dict[str, str]] = []

    for host in hosts:
        speakers.append(
            {
                "name": str(host),
                "role": "Host",
                "description": "Podcast host and interviewer; usually asks the questions.",
            }
        )
    if guest:
        speakers.append(
            {
                "name": str(guest),
                "role": "Guest",
                "description": "Podcast guest; usually answers the host's questions.",
            }
        )
    if len(speakers) < 2:
        raise TranscriptionError(
            "Metadata must contain at least one host and a guest_label_candidate"
        )
    return speakers


def request_summary(
    audio_path: Path,
    metadata_path: Path,
    output_dir: Path,
    speakers: list[dict[str, str]],
    delivery: str,
) -> str:
    names = ", ".join(f"{item['name']} ({item['role']})" for item in speakers)
    return "\n".join(
        [
            "AssemblyAI transcription plan",
            f"  Audio input:    {audio_path.relative_to(PROJECT_ROOT)}",
            f"  Metadata input: {metadata_path.relative_to(PROJECT_ROOT)}",
            f"  Output folder:  {output_dir.relative_to(PROJECT_ROOT)}",
            f"  Known speakers: {names}",
            f"  Media delivery: {delivery}",
            f"  Models:         {', '.join(SPEECH_MODELS)}",
            "  Language:       English",
            "  Diarization:    2 to 4 speakers",
            "  Identification: name-based, medium effort (not human-verified)",
            "  Region:         US",
        ]
    )


def resolve_youtube_audio_url(metadata: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Resolve a temporary URL for the same YouTube M4A format used at ingestion."""

    try:
        import yt_dlp
    except ModuleNotFoundError as exc:
        raise TranscriptionError(
            "yt-dlp is not installed. Run: conda env update --file environment.yml"
        ) from exc

    youtube = metadata.get("youtube", {})
    webpage_url = youtube.get("webpage_url")
    expected_video_id = youtube.get("video_id")
    if not webpage_url or not expected_video_id:
        raise TranscriptionError("RSS metadata contains no usable YouTube source URL")

    options = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(webpage_url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise TranscriptionError(
            f"Could not resolve the temporary YouTube audio URL: {exc}"
        ) from exc

    if info.get("id") != expected_video_id:
        raise TranscriptionError("YouTube returned a different video ID")
    direct_url = info.get("url")
    if not direct_url:
        raise TranscriptionError("yt-dlp returned no direct audio URL")
    details = {
        "method": "youtube_direct_url",
        "webpage_url": webpage_url,
        "video_id": info.get("id"),
        "format_selector": "bestaudio[ext=m4a]/bestaudio",
        "format_id": info.get("format_id"),
        "extension": info.get("ext"),
        "duration_seconds": info.get("duration"),
        "filesize_bytes": info.get("filesize") or info.get("filesize_approx"),
        "resolved_at": utc_now(),
        "temporary_url_recorded": False,
    }
    return str(direct_url), details


def identify_speakers(
    transcript_id: str,
    speakers: list[dict[str, str]],
    api_key: str,
) -> dict[str, Any]:
    """Apply contextual name identification to an existing diarized transcript."""

    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise TranscriptionError(
            "The AssemblyAI dependencies are missing. Run: "
            "conda env update --file environment.yml"
        ) from exc

    request_speakers = [
        {"name": item["name"], "description": item["description"]}
        for item in speakers
    ]
    body = {
        "transcript_id": transcript_id,
        "speech_understanding": {
            "request": {
                "speaker_identification": {
                    "speaker_type": "name",
                    "speakers": request_speakers,
                    "effort": "medium",
                }
            }
        },
    }
    timeout = httpx.Timeout(1800.0, connect=30.0)
    try:
        response = httpx.post(
            ASSEMBLYAI_UNDERSTANDING_URL,
            headers={"authorization": api_key, "content-type": "application/json"},
            json=body,
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise TranscriptionError(f"Speaker identification request failed: {exc}") from exc

    identification = (
        result.get("speech_understanding", {})
        .get("response", {})
        .get("speaker_identification", {})
    )
    if identification.get("status") != "success":
        raise TranscriptionError(
            "AssemblyAI did not return successful speaker identification: "
            f"{identification or result.get('error', 'unknown response')}"
        )
    if not result.get("utterances"):
        raise TranscriptionError("AssemblyAI returned no diarized utterances")
    return result


def sanitized_provider_error(error: Exception) -> str:
    """Remove temporary URLs and their signed query strings from an error."""

    message = str(error)
    message = re.sub(
        r"\[https?://[^\]]+\]",
        "[temporary media URL omitted]",
        message,
    )
    message = re.sub(r"https?://\S+", "[URL omitted]", message)
    return message[:1000]


def validate_api_key(api_key: str) -> None:
    """Check authentication with a non-billable one-item transcript listing."""

    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise TranscriptionError(
            "The AssemblyAI dependencies are missing. Run: "
            "conda env update --file environment.yml"
        ) from exc

    try:
        response = httpx.get(
            f"{ASSEMBLYAI_API_BASE_URL}/v2/transcript",
            headers={"authorization": api_key},
            params={"limit": 1},
            timeout=30.0,
        )
    except httpx.TransportError as exc:
        raise TranscriptionError(
            f"Could not reach AssemblyAI for the API-key check: {exc}"
        ) from exc
    if response.status_code == 401:
        raise TranscriptionError(
            "AssemblyAI rejected ASSEMBLYAI_API_KEY. Copy the active API key "
            "from the AssemblyAI dashboard, paste it without quotes, and export it again."
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise TranscriptionError(
            "AssemblyAI API-key check failed with HTTP "
            f"{response.status_code}: {response.text[:500]}"
        ) from exc


def parse_upload_response(response_text: str) -> str:
    """Validate the small JSON document returned by AssemblyAI's upload API."""

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise TranscriptionError("AssemblyAI upload returned invalid JSON") from exc
    upload_url = result.get("upload_url")
    if not upload_url:
        raise TranscriptionError(
            "AssemblyAI upload response contained no upload_url: "
            f"{str(result.get('error') or result)[:500]}"
        )
    return str(upload_url)


def curl_config_string(api_key: str) -> str:
    """Pass the secret header to curl over stdin, not as a visible argument."""

    escaped_key = api_key.replace("\\", "\\\\").replace('"', '\\"')
    return f'header = "authorization: {escaped_key}"\n'


def upload_file_with_curl(audio_path: Path, api_key: str) -> str:
    """Upload raw binary with curl, as documented by AssemblyAI."""

    curl = shutil.which("curl")
    if curl is None:
        raise TranscriptionError("curl is required for reliable large-file upload")

    command = [
        curl,
        "--config",
        "-",
        "--fail-with-body",
        "--show-error",
        "--progress-bar",
        "--ipv4",
        # This machine's HTTP/2 connection to /v2/upload is closed with
        # INTERNAL_ERROR before the body is sent. HTTP/1.1 is supported by the
        # same endpoint and avoids that transport-specific failure.
        "--http1.1",
        "--request",
        "POST",
        "--header",
        "content-type: application/octet-stream",
        # Avoid intermediary problems with the optional 100-continue handshake.
        "--header",
        "Expect:",
        "--data-binary",
        f"@{audio_path}",
        "--connect-timeout",
        "30",
        "--max-time",
        "1800",
        "--retry",
        "3",
        "--retry-all-errors",
        f"{ASSEMBLYAI_API_BASE_URL}/v2/upload",
    ]
    result = subprocess.run(
        command,
        input=curl_config_string(api_key),
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stdout.strip()[:500]
        suffix = f" Response: {detail}" if detail else ""
        raise TranscriptionError(
            f"curl could not upload the audio (exit {result.returncode}).{suffix}"
        )
    return parse_upload_response(result.stdout)


def speaker_mapping(response: dict[str, Any]) -> dict[str, str]:
    return (
        response.get("speech_understanding", {})
        .get("response", {})
        .get("speaker_identification", {})
        .get("mapping", {})
    )


def normalized_document(
    response: dict[str, Any],
    metadata: dict[str, Any],
    speakers: list[dict[str, str]],
    audio_path: Path,
) -> dict[str, Any]:
    role_by_name = {item["name"]: item["role"] for item in speakers}
    mapping = speaker_mapping(response)
    utterances = response.get("utterances") or []
    return {
        "schema_version": "0.1",
        "generated_at": utc_now(),
        "episode": {
            "title": metadata.get("episode", {}).get("title"),
            "podcast": metadata.get("podcast", {}).get("name"),
            "published_at": metadata.get("episode", {}).get("published_at"),
            "youtube_video_id": metadata.get("youtube", {}).get("video_id"),
            "source_url": metadata.get("youtube", {}).get("webpage_url"),
            "audio_relative_path": str(audio_path.relative_to(PROJECT_ROOT)),
            "audio_sha256": metadata.get("media", {}).get("sha256"),
        },
        "transcription": {
            "provider": "AssemblyAI",
            "region": "US",
            "transcript_id": response.get("id"),
            "status": response.get("status"),
            "language_code": response.get("language_code"),
            "audio_duration_seconds": response.get("audio_duration"),
            "confidence": response.get("confidence"),
            "speech_models_requested": SPEECH_MODELS,
            "speech_model_used": response.get("speech_model_used")
            or response.get("speech_model"),
            "speaker_identification_effort": "medium",
            "speaker_identities_human_verified": False,
        },
        "speakers": [
            {
                "id": original_label,
                "name": name,
                "role": role_by_name.get(name, "Unidentified"),
            }
            for original_label, name in mapping.items()
        ],
        "utterances": utterances,
    }


def markdown_transcript(document: dict[str, Any]) -> str:
    episode = document["episode"]
    transcription = document["transcription"]
    role_by_name = {item["name"]: item["role"] for item in document["speakers"]}
    published = (episode.get("published_at") or "")[:10]
    duration = format_timestamp((transcription.get("audio_duration_seconds") or 0) * 1000)

    lines = [
        "---",
        f"title: {yaml_string(episode.get('title'))}",
        f"podcast: {yaml_string(episode.get('podcast'))}",
        f"date: {yaml_string(published)}",
        f"duration: {yaml_string(duration)}",
        f"source_url: {yaml_string(episode.get('source_url'))}",
        "transcription:",
        '  provider: "AssemblyAI"',
        '  region: "US"',
        f"  transcript_id: {yaml_string(transcription.get('transcript_id'))}",
        f"  speech_model_used: {yaml_string(transcription.get('speech_model_used'))}",
        '  speaker_identification_effort: "medium"',
        "  speaker_identities_human_verified: false",
        "speakers:",
    ]
    for speaker in document["speakers"]:
        lines.extend(
            [
                f"  - id: {yaml_string(speaker['id'])}",
                f"    name: {yaml_string(speaker['name'])}",
                f"    role: {yaml_string(speaker['role'])}",
            ]
        )
    lines.extend(["---", "", f"# {episode.get('title') or 'Podcast transcript'}", "", "## Transcript", ""])

    for utterance in document["utterances"]:
        name = str(utterance.get("speaker") or "Unknown speaker")
        role = role_by_name.get(name, "Unidentified")
        stamp = format_timestamp(utterance.get("start") or 0)
        text = str(utterance.get("text") or "").strip()
        lines.append(f"**[{stamp}] {name} ({role}):** {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-directory",
        default="the_joe_rogan_experience",
        help="Folder name below data/raw/transcripts",
    )
    parser.add_argument(
        "--video-id",
        default="BAhcDwMGKYU",
        help="YouTube video ID used as the episode identifier",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Submit the billable API request after displaying the plan",
    )
    parser.add_argument(
        "--delivery",
        choices=("youtube-direct", "local-upload"),
        default="local-upload",
        help=(
            "How AssemblyAI receives the media. youtube-direct avoids uploading "
            "the large file from this Mac; local-upload uses /v2/upload."
        ),
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Submit a new job after preserving an existing failed job record",
    )
    parser.add_argument(
        "--guest-name",
        help="Curated guest name when immutable raw metadata has no guest label",
    )
    parser.add_argument(
        "--submit-only",
        action="store_true",
        help="Upload/submit or resume the job, record its ID, and do not wait",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = DERIVED_TRANSCRIPTS / args.show_directory / args.video_id
    try:
        audio_path, metadata_path, metadata = load_inputs(
            args.show_directory, args.video_id
        )
        speakers = known_speakers(metadata, args.guest_name)
        print(
            request_summary(
                audio_path,
                metadata_path,
                output_dir,
                speakers,
                args.delivery,
            )
        )
        if not args.yes:
            print("\nDry run only. Add --yes to submit the billable AssemblyAI request.")
            return 0

        api_key = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
        if not api_key:
            raise TranscriptionError(
                "ASSEMBLYAI_API_KEY is not set. Export it in this terminal; "
                "do not put it in the repository."
            )

        final_paths = [
            output_dir / "transcript.md",
            output_dir / "transcript.json",
            output_dir / "assemblyai_response.json",
        ]
        existing = [path for path in final_paths if path.exists()]
        if existing:
            names = ", ".join(str(path.relative_to(PROJECT_ROOT)) for path in existing)
            raise TranscriptionError(f"Refusing to overwrite existing output: {names}")
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            import assemblyai as aai
            import httpx
        except ModuleNotFoundError as exc:
            raise TranscriptionError(
                "assemblyai is not installed. Run: "
                "conda env update --file environment.yml"
            ) from exc

        aai.settings.base_url = ASSEMBLYAI_API_BASE_URL
        aai.settings.api_key = api_key
        aai.settings.http_timeout = 1800.0
        print("Checking the AssemblyAI API key...")
        validate_api_key(api_key)
        print("API key accepted.")
        job_path = output_dir / "assemblyai_job.json"
        transcript = None
        previous_failed_jobs: list[dict[str, Any]] = []
        if job_path.exists():
            job = json.loads(job_path.read_text(encoding="utf-8"))
            transcript_id = job.get("transcript_id")
            if not transcript_id:
                raise TranscriptionError(f"Invalid resume file: {job_path}")
            print(f"Resuming AssemblyAI transcript {transcript_id}")
            try:
                transcript = aai.Transcript.get_by_id(transcript_id)
            except (aai.TranscriptError, httpx.TransportError) as exc:
                raise TranscriptionError(
                    f"Could not retrieve AssemblyAI transcript {transcript_id}: {exc}"
                ) from exc
            if transcript.status == aai.TranscriptStatus.error:
                failure = sanitized_provider_error(
                    RuntimeError(transcript.error or "unknown provider error")
                )
                if not args.retry_failed:
                    raise TranscriptionError(
                        f"Existing transcript {transcript_id} failed: {failure}. "
                        "Add --retry-failed to preserve this record and submit a new job."
                    )
                previous_failed_jobs = list(job.get("previous_failed_jobs") or [])
                previous_failed_jobs.append(
                    {
                        "transcript_id": transcript_id,
                        "submitted_at": job.get("submitted_at"),
                        "media_delivery": job.get("media_delivery"),
                        "status": "error",
                        "error": failure,
                        "recorded_at": utc_now(),
                    }
                )
                print(f"Preserving failed transcript record {transcript_id}")
                transcript = None

        if transcript is None:
            config = aai.TranscriptionConfig(
                speech_models=SPEECH_MODELS,
                language_code="en",
                punctuate=True,
                format_text=True,
                speaker_labels=True,
                speaker_options=aai.SpeakerOptions(
                    min_speakers_expected=2,
                    max_speakers_expected=4,
                ),
            )
            transcriber = aai.Transcriber(api_key=api_key)
            try:
                if args.delivery == "youtube-direct":
                    print("Resolving the temporary direct YouTube M4A URL...")
                    media_url, delivery_record = resolve_youtube_audio_url(metadata)
                    print("Submitting the server-to-server transcription job...")
                else:
                    print("Uploading the local audio with curl...")
                    media_url = upload_file_with_curl(audio_path, api_key)
                    print("Upload completed; submitting the transcription job...")
                    delivery_record = {
                        "method": "assemblyai_local_upload",
                        "input_audio": str(audio_path.relative_to(PROJECT_ROOT)),
                        "upload_url_recorded": False,
                    }
                transcript = transcriber.submit(media_url, config=config)
            except aai.TranscriptError as exc:
                detail = sanitized_provider_error(exc)
                raise TranscriptionError(
                    f"AssemblyAI rejected the transcription request: {detail}"
                ) from exc
            job = {
                "schema_version": "0.2",
                "submitted_at": utc_now(),
                "provider": "AssemblyAI",
                "region": "US",
                "transcript_id": transcript.id,
                "input_audio": str(audio_path.relative_to(PROJECT_ROOT)),
                "input_audio_sha256": metadata.get("media", {}).get("sha256"),
                "media_delivery": delivery_record,
                "request": {
                    "speech_models": SPEECH_MODELS,
                    "language_code": "en",
                    "punctuate": True,
                    "format_text": True,
                    "speaker_labels": True,
                    "min_speakers_expected": 2,
                    "max_speakers_expected": 4,
                },
                "assemblyai_sdk_version": importlib.metadata.version("assemblyai"),
            }
            if previous_failed_jobs:
                job["previous_failed_jobs"] = previous_failed_jobs
            atomic_write_json(job_path, job)
            print(f"Transcript ID: {transcript.id}")

        if args.submit_only:
            print(
                "Submission recorded. Run again without --submit-only to wait "
                "and write the transcript outputs."
            )
            return 0

        print("Waiting for transcription and diarization to complete...")
        try:
            transcript.wait_for_completion()
        except (aai.TranscriptError, httpx.TransportError) as exc:
            raise TranscriptionError(
                "Polling was interrupted. Run the same command again to resume "
                f"transcript {transcript.id}: {exc}"
            ) from exc
        if transcript.status == aai.TranscriptStatus.error:
            failure = sanitized_provider_error(
                RuntimeError(transcript.error or "unknown provider error")
            )
            job["last_status"] = "error"
            job["last_error"] = failure
            job["last_checked_at"] = utc_now()
            atomic_write_json(job_path, job)
            raise TranscriptionError(f"Transcription failed: {failure}")
        if not transcript.utterances:
            raise TranscriptionError("Transcription completed without diarized utterances")

        print("Identifying the known speakers with medium effort...")
        identified_response = identify_speakers(transcript.id, speakers, api_key)
        document = normalized_document(
            identified_response, metadata, speakers, audio_path
        )
        atomic_write_json(output_dir / "assemblyai_response.json", identified_response)
        atomic_write_json(output_dir / "transcript.json", document)
        atomic_write_text(output_dir / "transcript.md", markdown_transcript(document))

        print(f"Completed transcript {transcript.id}")
        for path in final_paths:
            print(f"  Wrote: {path.relative_to(PROJECT_ROOT)}")
        print("Speaker identities are machine-inferred and require human verification.")
        return 0
    except (TranscriptionError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
