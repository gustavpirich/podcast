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
- On 2026-09-12, after both original stage-05 jobs failed before model execution
  because of an unsupported response-schema keyword, the researcher clarified
  the second-round outcome. Stage 05 now rechecks passage-level health/science
  relevance, extracts each exact checkable claim, and assigns a provisional
  claim-level relationship to scientific consensus. `fringe` means clearly
  conflicting with established scientific consensus or presenting an
  extraordinary unsupported position as established knowledge; `not_fringe`
  includes established understanding and legitimate scientific debate;
  `uncertain` is retained when the evidence or model knowledge is insufficient.
  A passage with no assessable claim receives a derived `not_assessable` row.
  All labels require human evidence review and do not by themselves measure
  truth, misinformation, intent, or harm.
- The local Stage-05 implementation draft caps claim-extraction snippets at 512
  words, splitting long positive regions at an utterance boundary when possible.
  This proposed unit prevents episode-length requests but requires researcher
  confirmation before submission.

## Decisions still required from the researcher

1. What is the precise research question: prevalence, framing, diffusion, or a
   comparison across shows, speakers, or time?
2. What is the sampling frame, period, language scope, and inclusion/exclusion
   rule for podcasts and episodes?
3. Should the proposed 512-word maximum for non-overlapping Stage-05 snippets be
   accepted before submitting the replacement batches?
4. Which evidence sources, search procedure, and human adjudication rule will
   convert the provisional claim-level fringe screen into a validated measure?
5. How will factual accuracy, misinformation, intent, and harm be
   operationalized if they are later added as separate outcomes?
6. Is the aim descriptive or causal? A causal claim needs an explicit
   identification strategy and assumptions beyond this repository structure.
7. What transcript rights, privacy/IRB, platform terms, and data-security rules
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
