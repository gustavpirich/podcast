# Analysis code

The step-by-step map of the pipeline (which script, which folder, what has run)
is [`notes/PIPELINE.md`](../notes/PIPELINE.md).

## Diary of a CEO archive and local transcription

`01_build_doac_rss_archive.py` reads a frozen DOAC RSS snapshot, keeps
full-length interviews (type `full`, at least 60 minutes, no clip titles) and
writes metadata-only raw records plus `config/doac_full_rss_archive_<snapshot>.json`.
A sample from that manifest then runs through the same free local pipeline as JRE:

```bash
python code/01_build_doac_rss_archive.py --snapshot data/raw/rss/doac/doac_rss_20261003T092332Z.xml --yes
python code/01_draw_random_sample.py --source config/doac_full_rss_archive_20261003T092332Z.json \
  --start 2021-01-01 --end 2025-12-31 --n 10 --seed 20261014 --min-minutes 60
python code/02_transcribe_local_batch.py --sample config/samples/doac_random_2021_2025_n10_seed20261014.json --yes
python code/03_label_speakers_gpt.py --sample config/samples/doac_random_2021_2025_n10_seed20261014.json --yes
```

## Guest dataset (popular frame, RSS only)

`18_build_guest_dataset.py` lists the guests of every episode in the latest
popular frame (`01_build_popular_episode_frame.py`, 2019-01-01 onward) using
only the frozen RSS titles and descriptions and the rules in
`config/guest_rules.json`. No network, no model, no cost.

```bash
python code/18_build_guest_dataset.py
```

Output in `data/derived/guest_dataset/<frame>/`: `episodes.csv` (one row per
episode, `guests` separated by "; ", with the rule used and the Edison rank of
the show in that year), `episode_guests.csv` (one row per episode-guest pair
with the source text), `shows.csv` and `summary.md`. To fix a show, edit its
rules or `extra_hosts` in the config and rerun.

`19_flag_guest_topics.py` then adds `health_related` / `science_related`
flags to every guest row (`episode_guests_topics.csv`) and episode
(`episode_topics.csv`) by matching `config/rss_topic_terms.json` against the
title and description, after removing ads and sentences repeated across a
show's episodes. Guest-level flags use only the text naming the guest; the
`episode_*` columns use the whole episode text. Free; not validated.

Engagement (free, public data):

```bash
python code/20_snapshot_youtube_channels.py --yes        # list channel uploads
python code/21_match_youtube_videos.py                   # RSS episode -> video
python code/22_snapshot_youtube_video_metrics.py --yes   # views/likes/comments (hours; resumable, --shard K/N)
python code/23_snapshot_apple_ratings.py --yes           # show-level Apple rating
python code/24_build_engagement_dataset.py               # episodes_engagement.csv, episode_guests_engagement.csv
```

Use `yt_match_check` to filter matches (ok / reupload_likely / date_gap_check).

## Pipeline status

`00_pipeline_status.py` scans raw records, transcripts and collected
classification runs and reports how far each episode has progressed and its next
step. It is read-only and makes no API calls. Outputs are overwritten on each run:
`data/derived/pipeline_status/episode_status.csv` and
`output/pipeline_status/status_report.md`.

```bash
python code/00_pipeline_status.py
```

## Fringe supply dataset

`14_build_fringe_supply_dataset.py` applies the 2026-10-01 fringe tier
definition (emerging, speculative, contradicts consensus; exaggeration alone
excluded) to the frozen pilot statements and attributes each verified claim to
its diarized speaker by word index. It writes `statements.csv`, `speakers.csv`
and `summary.json` to `data/derived/descriptives/`. No model calls are made.
The analysis plan is in [`notes/DESCRIPTIVES_PLAN.md`](../notes/DESCRIPTIVES_PLAN.md).

`15_snapshot_youtube_metrics.py` records public YouTube view, like and comment
counts for frozen samples (dry run by default; `--yes` fetches) and writes a new
timestamped snapshot under `data/raw/audience_metrics/youtube/`. Run it in the
`podcast_observational` Conda environment, which provides yt-dlp.

`16_draw_fringe_validation_sample.py` draws the blind, stratified 150-claim
human validation sample. The coding guide is
[`notes/FRINGE_VALIDATION_CODING.md`](../notes/FRINGE_VALIDATION_CODING.md).

`17_mockup_descriptives.py` draws five draft figures to `output/descriptives_mockup/`.
Figure 4 (host treatment) uses **simulated** data until host responses are coded.

## Health-claim veracity and danger

`12_classify_veracity.py` augments existing Stage-10 statements using OpenAI Batch
with supported, exaggerated, unsupported, contradicted and uncertain veracity,
plus a separate dangerousness field. Original labels and human notes are retained.
The proposal, evidence limitations, commands and validation requirements are in
[`notes/VERACITY_CLASSIFICATION.md`](../notes/VERACITY_CLASSIFICATION.md).

## Health product and behavior classification

`10_classify_health_objects.py` classifies the existing broad-run statements by
their substantive object: vaccines, pharmaceuticals, peptides/hormones,
supplements, psychoactive substances, medical technologies, diet, exercise,
sleep, mental/behavioral interventions, environmental exposures, healthcare,
disease, or non-health science. It also records claim focus, product maturity,
and extraction quality. Exact repetitions created by overlapping windows are
linked before classification; all 8,504 original instances remain traceable.
The complete codebook and workflow are in
`notes/HEALTH_OBJECT_CLASSIFICATION.md`.

## Broad fringe and episode graphs

`08_classify_broad_fringe.py` implements the broader 2026-09-14 definition in a
separate run: scientific position, exaggeration, and conversational stance.
It uses the existing `podcast_observational` Conda environment with the OpenAI
SDK. `prepare` freezes all inputs locally; `submit --yes`, `status`, and `collect`
use the environment's `OPENAI_API_KEY`. The full codebook and commands are in
`notes/BROAD_FRINGE_CLASSIFICATION.md`.

`09_plot_fringe_extent.py` makes episode/show summaries and PNG/SVG graphs from
either the legacy CSV (default) or a new `--input` broad classification CSV.
It labels the definition explicitly and does not convert uncertain labels into
fringe. Install the plotting dependency in the project-local environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r config/fringe_plot_requirements.txt
.venv/bin/python code/09_plot_fringe_extent.py
```

Outputs are under `output/fringe_science/`, keyed by the input hash. Pooled show
rates and unweighted episode means are distinct. All windows, including
screen-negatives, remain in the full-episode denominator.

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

## Conditional window-level claim and fringe classifier

`05_classify_passage_content_openai_batch.py` is the next, distinct measurement
stage. It reads collected stage-04 results for a frozen sample and preserves the
same 256-word windows with a 128-word stride. Positive health/science windows are
sent for exact claim extraction and provisional `fringe`, `not_fringe`, or
`uncertain` coding. The final CSV retains every Stage-04 window as one row;
windows without an assessable claim are `not_assessable`. The codebook is in
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
`submit --yes` uploads selected transcript windows and incurs API charges.
Successful collection writes `window_claim_classification.csv`; every row is marked for
human evidence review because the model does not search or cite literature.

After collecting multiple compatible samples, combine them into one inspected
CSV with `06_combine_window_claim_classifications.py`. The combiner records the
source hashes and Batch IDs and verifies unique window keys, 256-word windows,
and the 128-word within-episode stride.

`07_prepare_classification_dashboard_data.py` now defaults to the completed
broad-fringe CSV from run `5a165612d6459da0` and prepares the JSON consumed by
the local `dashboard/` app. The inspector shows all 4,124 windows, the separate
scientific-position/exaggeration/stance dimensions, chart denominators,
and human review exports. The generator also accepts historical inputs via
`--input`; the current webpage requires the broad schema to avoid confusing
measurement definitions. Generated transcript JSON is excluded from Git.
