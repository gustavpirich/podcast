# Analysis code

Put reproducible scripts and notebooks here. A numbered workflow is easy to
inspect, for example:

1. `01_ingest_transcripts.py` reads raw source files and writes normalized data.
2. `02_validate_data.py` checks identifiers, timestamps, and coverage.
3. `03_build_measures.py` creates documented measures.
4. `04_analysis.py` creates tables and figures.

Acquisition scripts may create new, uniquely identified files in `data/raw/`
but must never overwrite them. Transformation and analysis scripts read
`data/raw/` and write only to `data/derived/` or `output/`. Keep substantive
choices in configuration or notes rather than hidden in code.

## Current acquisition pilot

`01_download.py` starts from one YouTube URL, checks its channel, matches it to
the publisher's official RSS feed, and downloads the best available YouTube M4A.
The RSS feed—not the YouTube description—is the authoritative episode metadata
source. Audio and an immutable metadata record are stored under
`data/raw/transcripts/<show>/<youtube_video_id>/` and ignored by Git.

From the repository root:

```bash
python code/01_download.py \
  "https://www.youtube.com/watch?v=BAhcDwMGKYU" \
  --show jre
```

The stable YouTube video ID is used for the directory and filename because an
episode title can change. Existing raw audio and metadata are never overwritten.

## Current transcription pilot

`02_transcribe_assemblyai.py` reads the raw M4A and its RSS metadata, submits the
audio to AssemblyAI's US service, enables speaker diarization, and contextually
maps the resulting speaker labels to the host and guest names recorded in the
metadata. It writes a readable Markdown transcript, structured JSON with
word-level timestamps, and the provider response under `data/derived/`.

The API key must be in the terminal environment, never in a tracked project
file. After activating the Conda environment:

```bash
export ASSEMBLYAI_API_KEY='paste-your-key-here'

# Inspect inputs, outputs, and settings without making a paid API request.
python code/02_transcribe_assemblyai.py

# Submit or resume the paid transcription job.
python code/02_transcribe_assemblyai.py --yes
```

The default arguments select the current pilot. For another downloaded episode,
pass `--show-directory` and `--video-id`. The script verifies the raw audio hash,
refuses to overwrite completed outputs, and records the transcript ID so an
interrupted run can resume without submitting the audio again.

By default, the script uploads the hash-checked local M4A as raw binary with
`curl --data-binary`, following AssemblyAI's documented HTTP fallback. The API
key is supplied to curl through standard input rather than placed in its
command-line arguments. The official Python SDK handles transcription submission,
polling, and transcript objects.

`--delivery youtube-direct` is retained as a documented diagnostic option, but
YouTube's temporary media URLs can be bound to the requesting computer's IP and
therefore inaccessible from AssemblyAI. After a failed provider job,
`--retry-failed` preserves its provenance inside `assemblyai_job.json` before
submitting a new job.

## Provisional content classification

`03_classify_content.py` gives every diarized speaker turn two independent binary
labels: `health_related` and `science_related`. The transparent screening rules
live in `config/content_classification.json`, while the substantive definitions
and limitations are documented in `notes/CONTENT_CLASSIFICATION_CODEBOOK.md`.

Run the current pilot from the repository root:

```bash
python code/03_classify_content.py
```

The script writes a reviewable turn-level CSV and a JSON summary under
`data/derived/classifications/<show>/<episode>/`. All positive rows and a stable
10% sample of negatives are marked for manual review. Results are provisional
until that validation is completed.

## OpenAI Batch classifier

`04_classify_content_openai_batch.py` applies the same two-label research task
with OpenAI's asynchronous Batch API and strict structured JSON outputs. The
model unit is one complete 256-word window, with a 128-word stride; episodes
shorter than 768 words are excluded. The prompt, model, and windowing choices
live in `config/openai_content_classification.json`. The complete explanation
is in `notes/OPENAI_BATCH_CLASSIFICATION.md`.

The four commands are deliberately separate so upload and cost are explicit:

```bash
python code/04_classify_content_openai_batch.py prepare
python code/04_classify_content_openai_batch.py submit --yes
python code/04_classify_content_openai_batch.py status
python code/04_classify_content_openai_batch.py collect
```

Only `submit --yes` sends transcript text to OpenAI or incurs API charges.
