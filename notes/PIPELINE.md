# Pipeline map

How an episode moves from a podcast feed to a row in the statement dataset,
which script does each step, where its files land, and what has been run.
Written 2026-10-02. For current counts, run:

```bash
python code/00_pipeline_status.py
```

It reads files only (no API calls, no changes to `data/raw/`) and writes
`output/pipeline_status/status_report.md` plus one row per episode in
`data/derived/pipeline_status/episode_status.csv`, including the next step
each episode needs.

## The path of one episode

```text
 podcast RSS feed
      │  01  freeze episode list + metadata                       free
      ▼
 data/raw/transcripts/<show>/<episode_id>/rss_metadata.json
      │  02  AssemblyAI: transcript + speaker labels + names        ~$0.33 / audio hour
      ▼
 data/derived/transcripts/<show>/<episode_id>/transcript.{md,json.gz}
      │  04  GPT: is each 256-word window about health/science?     ~$0.04 / episode
      ▼
 data/derived/classifications/openai_batch/<show>/<episode_id>/<run>/window_classification.csv
      │  05  GPT: narrow claim screen (older definition)            needed as 08's input today
      │  08  GPT: extract claims; position / exaggeration / stance  ~$0.05 / episode
      ▼
 data/derived/classifications/broad_fringe/<run>/broad_window_classification.csv
      │  10  GPT: object of each claim; merge repeats from overlapping windows
      ▼
 data/derived/classifications/health_objects/<run>/statement_units.csv
      │  14  no model: attach each claim to the speaker who said it
      ▼
 data/derived/descriptives/<name>/statements.csv  +  speakers.csv
```

`statements.csv` is the analysis file: one row per unique claim with the exact
quote, speaker, host/guest role, timestamps, topic/object, scientific position,
stance, exaggeration and fringe tier.

## Steps in detail

| Step | Script | Unit | Writes | Cost | Codebook |
| --- | --- | --- | --- | --- | --- |
| 01 Freeze episodes | `01_download.py` (YouTube audio, early pilots); `01_build_jre_rss_archive.py` (whole JRE feed); `01_build_doac_rss_archive.py` (DOAC full-length interviews) | episode | `data/raw/transcripts/…/rss_metadata.json`; sample list in `config/*.json` | free | `config/podcasts.json` |
| 02 Transcribe | `02_transcribe_assemblyai_batch.py` → runs `02_transcribe_assemblyai.py` per episode | episode | `transcript.md`, `transcript.json(.gz)`, `assemblyai_response.json(.gz)`, `assemblyai_job.json` | ~$0.33/hour | — |
| 04 Screen | `04_classify_content_openai_batch_sample.py` (per sample) → `04_classify_content_openai_batch.py` (per episode) | 256-word window, 128-word step | per-episode `window_classification.csv`; combined CSV in `openai_batch_samples/<sample>/` | ~$0.04/episode | `OPENAI_BATCH_CLASSIFICATION.md` |
| 05 Narrow claims | `05_classify_passage_content_openai_batch.py` | screen-positive window | `openai_passage_content/<sample>/<run>/window_claim_classification.csv` | similar to 08 | `PASSAGE_CONTENT_CLASSIFICATION.md` |
| 08 Broad claims | `08_classify_broad_fringe.py` | screen-positive window | `broad_fringe/<run>/broad_window_classification.csv` | ~$0.05/episode | `BROAD_FRINGE_CLASSIFICATION.md` |
| 10 Objects + merging | `10_classify_health_objects.py` | claim | `health_objects/<run>/statement_units.csv`, `statement_instances.csv` | small | `HEALTH_OBJECT_CLASSIFICATION.md` |
| 12 Veracity (optional) | `12_classify_veracity.py` | unique claim | `veracity/<run>/…` | small | `VERACITY_CLASSIFICATION.md` |
| 14 Speaker dataset | `14_build_fringe_supply_dataset.py` | unique claim | `descriptives/<name>/statements.csv`, `speakers.csv` | free | `DESCRIPTIVES_PLAN.md` |

Every paid OpenAI step has the same four commands, so nothing is uploaded or
charged by accident:

```text
prepare          free, local: builds and freezes the exact requests
submit --yes     uploads and starts the Batch job (the only step that costs money)
status           checks the job
collect          downloads results, validates them, writes the CSVs
```

The `02` transcription runner is similar: without `--yes` it only prints the
plan and a cost estimate.

### Other scripts

| Script | Role |
| --- | --- |
| `00_pipeline_status.py` | Progress inventory (this document's companion). |
| `03_classify_content.py` | Historical keyword baseline for one episode; not used downstream. |
| `06_combine_window_claim_classifications.py` | Combines Stage-05 outputs from several samples into one CSV. |
| `07_prepare_classification_dashboard_data.py` | Data for the local `dashboard/` review app. |
| `09_plot_fringe_extent.py`, `11_summarize_fringe_prevalence.py`, `13_describe_jre_latest_40.py` | Earlier reports and figures. |
| `15_snapshot_youtube_metrics.py` | Public YouTube views/likes/comments snapshot (demand side). |
| `16_draw_fringe_validation_sample.py` | Blind 150-claim human validation sample. |
| `17_mockup_descriptives.py` | Draft figures (figure 4 is simulated). |

## Names and identifiers

- **Show:** a short ID (`jre`, `doac`) and a folder name (`the_joe_rogan_experience`),
  both set in `config/podcasts.json`.
- **Episode ID:** the YouTube video ID for early episodes (`BAhcDwMGKYU`), otherwise
  `jre-<number>-<hash>` derived from the RSS entry. The pair (show, episode_id)
  is the merge key everywhere.
- **Sample:** a frozen list of episodes in `config/*.json` with a `sample_id`.
  Scripts take `--sample` so a sample never changes under you.
- **Run ID:** a hash of a stage's exact inputs, prompt and settings. The same
  inputs always give the same run folder; a changed prompt gives a new folder, so
  older results are never overwritten. `latest_prepared_run.json` points to the
  most recent one.
- **Window:** 256 consecutive transcript words starting every 128 words, so each
  word is in two windows. Stage 10 merges claims found twice into one statement.

## Where things stand (2026-10-02)

From `output/pipeline_status/status_report.md`:

| | Episodes | Hours |
| --- | ---: | ---: |
| JRE episodes in the frozen RSS list | 2,660 | 7,110 |
| Transcribed (JRE 40 + DOAC 10) | 50 | 131 (1.48 million words) |
| Screened for health/science (04) | 50 | |
| Narrow claims (05) | 50 | |
| Broad claims (08), statements (10), speaker dataset (14) | 20 (pilot: 10 JRE + 10 DOAC) | |
| Veracity (12) | 0 collected | |

## Known gaps (found while building the status check)

1. **30 JRE episodes stop after Stage 05.** The newest 30 of the latest-40 JRE
   episodes have narrow claims only. Running 08 → 10 → 14 for them would give
   one definition for all 50 episodes (estimated $1.55–$1.91 for 08; see
   `DESCRIPTIVES_PLAN.md`).
2. **Veracity run was never collected.** Run `03b4d55da8851b87` was submitted;
   its second retry (`retry_002`) has no downloaded output and no final CSV.
3. **Multi-guest episodes lose speaker names.** Sample files hold one
   `guest_name` per episode, so additional guests stay "Unidentified". Share of
   words spoken by unnamed voices: JRE #2536 (two guests) 65%, Protect Our Parks
   47%, #2552 (two guests) 34%, JRE MMA #182 100% (name identification failed).
   In most other episodes an unnamed voice speaks 1–6% of words (producer, ads).
   Claims from unnamed voices cannot be assigned to host or guest.
4. **Stage 08 reads Stage-05 output, not Stage-04 output.** New episodes would
   need the older narrow run first, or 08 needs to accept the Stage-04 CSV.
5. **Several scripts are fixed to JRE/DOAC or to one run.** `08` defaults to
   the two pilot samples, `10` and `12` default to the pilot runs, `14` has the
   pilot run ID built in, and `09`/`11` list the two shows by name.
6. **Speaker range is fixed at 2–4** in `02_transcribe_assemblyai.py`; panel
   shows need a per-show range.

## Adding a new podcast or a new batch

| Step | Ready now? |
| --- | --- |
| Add the show (RSS URL, hosts, folder) to `config/podcasts.json` | Yes |
| Freeze its episode list and write `rss_metadata.json` per episode | JRE (`01_build_jre_rss_archive.py`) and DOAC (`01_build_doac_rss_archive.py`); other shows need a general version |
| Transcribe with `02_transcribe_assemblyai_batch.py --delivery rss-direct` | Yes, given a sample file with guest names |
| Screen with `04_…_sample.py --sample …` | Yes |
| Claims with `08` → `10` → `14` | Works per sample, but see gaps 4 and 5 |
| Check progress with `00_pipeline_status.py` | Yes |

Researcher decisions still needed before scaling up are listed in
`DESCRIPTIVES_PLAN.md` (sample frame) and `PLAN.md`.

## Popular-podcast frame (added 2026-10-02)

Builds the list of popular, long-form health / self-help / comedy shows and
prepares every episode from 2021-10-01 to 2026-09-30 for transcription. All
steps are free; only the final `02` command with `--yes` costs money.

| Step | Script | Writes | Check |
| --- | --- | --- | --- |
| a. Archive Edison Top-50 lists (Q4 2021 - Q2 2026) | `01_snapshot_edison_top50.py --yes` | `data/raw/popularity/edison_top50/<ts>/` | 17 releases, one ranking image each |
| b. Type up the 850 list rows | (AI image reading) | `config/edison_top50_transcribed.csv`, `config/edison_show_aliases.csv` | `human_verified = 0`: spot-check against the images |
| c. Find each show in Apple's directory | `01_lookup_apple_podcasts.py --yes` | `data/raw/popularity/apple_search/<ts>/` | 111 shows |
| d. Pick the matching feed | `01_match_apple_podcasts.py`, then review | `config/popular_show_feeds.csv` | non-exact matches reviewed by hand |
| e. Download every feed | `01_snapshot_show_feeds.py --yes` | `data/raw/rss/<show_id>/`, `data/raw/rss/snapshots/<ts>.json` | 106 feeds |
| f. Apply the three criteria | `01_build_popular_episode_frame.py` | `data/derived/popular_frame/<ts>/shows.csv`, `episodes.csv`, `summary.md` | 29 shows, 10,957 episodes |
| g. Write raw records + samples | `01_create_popular_episode_records.py --yes` | `data/raw/transcripts/<show>/<episode>/rss_metadata.json`, `config/popular_frame/<show_id>.json` | existing JRE folders reused by GUID |
| h. Transcribe | `02_transcribe_assemblyai_batch.py --sample config/popular_frame/<show_id>.json --delivery rss-direct --max-episodes 100 [--yes]` | `data/derived/transcripts/<show>/<episode>/` | dry run first; `00_pipeline_status.py` after each batch |

The three criteria: (1) listed in an Edison US Top-50 release; (2) primary RSS
category Comedy, Health & Fitness, or Education > Self-Improvement; (3) median
episode length at least 60 minutes. Hosts are named from `config/podcasts.json`
(names printed in each feed); every other voice is labelled `Guest`.

Speaker roles in new transcripts: configured hosts (including AssemblyAI's
split "Name - N" voices, merged back) are Host; "Guest", "Guest - N" and other
people AssemblyAI names itself are Guest (`name_source` records which); bare
letters are Unidentified. To re-apply this to a finished transcript without
paying again: `python code/02_transcribe_assemblyai.py --show-directory <show>
--episode-id <id> --rebuild` (needs the API key for a free metadata request).
