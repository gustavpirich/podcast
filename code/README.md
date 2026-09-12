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

For the frozen ten-episode *Diary of a CEO* starter sample, first inspect the
plan and then explicitly confirm the downloads:

```bash
python code/01_download.py --sample config/doac_starter_sample.json
python code/01_download.py --sample config/doac_starter_sample.json --yes
```

The tracked sample file records the exact RSS GUID and YouTube ID for each
episode. This avoids changing the sample whenever the feed publishes something
new and allows RSS and YouTube titles to differ without fuzzy matching. The
audio remains local under `data/raw/` and is never sent to SharePoint or GitHub.

The frozen ten-episode JRE starter sample contains the existing #2550 pilot and
its nine immediately preceding full RSS releases. It uses the same acquisition
workflow:

```bash
python code/01_download.py --sample config/jre_starter_sample.json
python code/01_download.py --sample config/jre_starter_sample.json --yes
```

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

The frozen ten-episode *Diary of a CEO* sample has a batch orchestrator. Its dry
run validates every local audio checksum and displays the complete plan without
contacting AssemblyAI:

```bash
python code/02_transcribe_assemblyai_batch.py
```

After checking the displayed duration, current pricing, and account balance,
submit and collect the sample with:

```bash
export ASSEMBLYAI_API_KEY='paste-your-key-here'
python code/02_transcribe_assemblyai_batch.py --yes
```

The first phase submits every unfinished episode before the second phase waits
and writes outputs. This lets AssemblyAI process jobs concurrently while keeping
one resumable `assemblyai_job.json` per episode. A rerun skips completed outputs
and resumes recorded jobs. Guest names are curated in the tracked sample config;
the inferred mapping from diarized voices to those names still requires human
verification.

The same transcription runner accepts the JRE sample explicitly:

```bash
python code/02_transcribe_assemblyai_batch.py \
  --sample config/jre_starter_sample.json
python code/02_transcribe_assemblyai_batch.py \
  --sample config/jre_starter_sample.json --yes
```

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

For the frozen ten-episode *Diary of a CEO* sample, use the sample runner. It
validates all ten transcripts, runs the same single-episode classifier for each
one, skips work already completed, and creates a combined sample-level CSV and
summary after collection:

```bash
python code/04_classify_content_openai_batch_sample.py prepare
python code/04_classify_content_openai_batch_sample.py submit --yes
python code/04_classify_content_openai_batch_sample.py status
python code/04_classify_content_openai_batch_sample.py collect
```

The sample runner creates one independently resumable OpenAI Batch job per
episode. Only the second command uploads transcript excerpts and incurs API
charges. The API key must be exported in the same terminal session first.

For the JRE sample, pass its sample configuration through the same Batch API
runner:

```bash
python code/04_classify_content_openai_batch_sample.py prepare \
  --sample config/jre_starter_sample.json
python code/04_classify_content_openai_batch_sample.py submit \
  --sample config/jre_starter_sample.json --yes
python code/04_classify_content_openai_batch_sample.py status \
  --sample config/jre_starter_sample.json
python code/04_classify_content_openai_batch_sample.py collect \
  --sample config/jre_starter_sample.json
```

## Conditional claim and fringe classifier

`05_classify_passage_content_openai_batch.py` is the next, distinct measurement
stage. It reads collected stage-04 results for a frozen sample, keeps windows
screened as health-related or science-related, and merges consecutive overlaps
into non-overlapping snippets. It rechecks health/science relevance, extracts
each exact checkable claim, and provisionally classifies the claim as `fringe`,
`not_fringe`, or `uncertain`. Snippets without an assessable claim are retained
as `not_assessable`. The current local draft proposes a 512-word maximum per
snippet and requires researcher confirmation before submission. The codebook is in
`notes/PASSAGE_CONTENT_CLASSIFICATION.md`; the machine-readable choices are in
`config/openai_passage_content_classification.json`.

After stage 04 has been collected for every sample episode:

```bash
python code/05_classify_passage_content_openai_batch.py prepare \
  --sample config/doac_starter_sample.json
python code/05_classify_passage_content_openai_batch.py submit \
  --sample config/doac_starter_sample.json --yes
python code/05_classify_passage_content_openai_batch.py status \
  --sample config/doac_starter_sample.json
python code/05_classify_passage_content_openai_batch.py collect \
  --sample config/doac_starter_sample.json
```

Use `--sample config/jre_starter_sample.json` for the JRE sample. This stage uses
one resumable Batch job per frozen sample. `prepare` is local and free; only
`submit --yes` uploads selected transcript passages and incurs API charges.
Successful collection writes `claim_classification.csv`; every row is marked for
human evidence review because the model does not search or cite literature.
