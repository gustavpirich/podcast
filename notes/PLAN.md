# Research plan and decision log

## Objective

Build a transparent observational corpus of podcast transcripts and use it to
describe health-related claims under a pre-specified, evidence-backed coding
protocol.

## What this setup decides

- The project uses a raw -> derived -> output workflow.
- Raw inputs and generated artifacts are excluded from Git; the code and
  documentation that recreate them are version-controlled.
- The initial project is intentionally simple and inspectable.
- No automated system is treated as a misinformation classifier by default.
- For the model-assisted screen, the researcher selected complete 256-word
  windows with a 128-word stride and a 768-word episode minimum on 2026-09-10.
- The initial *Diary of a CEO* acquisition sample is the ten most recent
  full-length RSS episodes as of 2026-09-10 that were matched to the official
  YouTube channel. "Most Replayed Moment" entries are excluded. Audio is stored
  locally, not on SharePoint, and remains untracked by Git.
- These ten episodes will be transcribed from their checksum-verified local M4A
  files with AssemblyAI's US pre-recorded endpoint, Universal-3.5 Pro with
  Universal-2 fallback, speaker diarization constrained to 2–4 speakers, and
  medium-effort name identification using the curated host/guest roster. All
  speaker-name mappings remain machine-inferred until manually verified.
- On 2026-09-10, the researcher chose to screen those ten transcripts for two
  independent binary outcomes, `health_related` and `science_related`, using
  GPT-5.6 Luna through the OpenAI Batch API. The previously selected complete
  256-word windows, 128-word stride, and 768-word episode minimum apply. These
  are provisional topical labels, not misinformation or accuracy judgments;
  positives and a deterministic sample of negatives require human validation.
- The initial JRE sample is the existing #2550 pilot plus the nine immediately
  preceding full-length releases in the official RSS chronology as frozen on
  2026-09-10. Numbered JRE and JRE MMA Show episodes are included; clips and
  excerpts are excluded. The nine additions will follow the same local YouTube
  M4A acquisition, AssemblyAI transcription/diarization, and OpenAI Batch
  health/science classification pipeline as the pilot.
- On 2026-09-10, the researcher chose a conditional second-stage content coding
  pipeline. Consecutive overlapping stage-04 windows with either positive label
  are merged into non-overlapping passages. Stage 05 rechecks health/science,
  assigns one primary and any applicable secondary health topics from a
  seven-category taxonomy, and codes dominant content type, explicit support
  type, claim presence, health recommendations, and science-content type. The
  descriptive amount is measured with unique passage words and passage time,
  not counts of overlapping windows. These remain provisional model-assisted
  labels and do not measure fringe status, truth, or misinformation.

## Decisions still required from the researcher

1. What is the precise research question: prevalence, framing, diffusion, or a
   comparison across shows, speakers, or time?
2. What is the sampling frame, period, language scope, and inclusion/exclusion
   rule for podcasts and episodes?
3. Should the later accuracy/fringe assessment extract exact claim spans, and
   should it use claim-level or speaker-level units rather than stage-05
   passages?
4. How will a health claim, accuracy, uncertainty, and misinformation be
   operationalized? Which evidence sources and adjudication rule apply?
5. Is the aim descriptive or causal? A causal claim needs an explicit
   identification strategy and assumptions beyond this repository structure.
6. What transcript rights, privacy/IRB, platform terms, and data-security rules
   apply?

## Phased workflow and checkpoints

| Phase | Deliverable | Check before continuing |
| --- | --- | --- |
| Protocol | Sampling and coding protocol in `notes/` | Definitions can be applied to an unseen example. |
| Corpus | Source log and immutable raw transcript archive | IDs, dates, source URLs, and coverage are complete. |
| Processing | Scripted normalized segments in `data/derived/` | Counts reconcile to the source archive; raw files are unchanged. |
| Measurement | Versioned codebook and coded sample | Blind double-coding and disagreement review are documented. |
| Analysis | Tables/figures in `output/` | Results reproduce from code; sensitivity checks match the plan. |
| Reporting | Manuscript and appendix in `paper/` | Claims distinguish observed patterns from causal interpretation. |

## Candidate measurement approaches

- Human coding first: most defensible for factual accuracy; slower and requires a
  codebook and reliability checks.
- Dictionary or keyword screening: useful to find candidate segments; not a
  valid truth label without validation.
- Model-assisted coding: scalable after a human-coded evaluation set and a
  documented error analysis; still needs human oversight.

Record the chosen approach, its trade-offs, and any departure from this plan here
before moving to a large-scale corpus.
