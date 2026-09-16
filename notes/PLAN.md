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
  labels and do not measure fringe status, truth, or misinformation. The merged
  passage unit was superseded by the researcher's 2026-09-12 decision below.
- On 2026-09-12, after both original stage-05 jobs failed before model execution
  because of an unsupported response-schema keyword, the researcher clarified
  that the existing overlapping 256-word Stage-04 windows remain the units of
  analysis in Stage 05. Positive health/science windows are sent for exact claim
  extraction and provisional consensus/fringe coding; all Stage-04 windows are
  retained as one row each in the final CSV. A window is `fringe` when it
  contains at least one fringe claim; otherwise `uncertain` takes precedence
  over `not_fringe`, and a window with no assessable claim is `not_assessable`.
  A disagreement between a claim's model-returned consensus relationship and
  fringe status is retained, flagged, and conservatively coded `uncertain`.
  `fringe` means clearly conflicting with established scientific consensus or
  presenting an extraordinary unsupported position as established knowledge;
  `not_fringe` includes established understanding and legitimate scientific
  debate; `uncertain` is retained when the evidence or model knowledge is
  insufficient. All labels require human evidence review.
- On 2026-09-14, the researcher removed the redundant Stage-05 health/science
  recheck and passage rationale for future runs. Stage 04 remains the sole
  health/science classification step; Stage 05 extracts claims and provisionally
  assigns their consensus relationship and fringe status.
- On 2026-09-14, the researcher specified a three-sentence, plain-language
  explanation for each Stage-05 claim: what it means, whether established
  scientific evidence supports, disputes, or does not clearly resolve it, and
  why that assessment produces the consensus/fringe classification. The prompt
  distinguishes absence of evidence from evidence against a claim and excludes
  speaker-belief, ideological, and societal interpretations.
- The researcher reports that the intended final JRE corpus contains 466,328
  windows. That full corpus is not currently present in this repository; the
  current ten-episode JRE pilot contains 2,320 windows.
- On 2026-09-14, the researcher requested an interactive review of uncertain,
  fringe, and not-fringe classifications to improve the classifier. The local
  dashboard records a human claim decision as `fringe`, `uncertain`,
  `not_fringe`, or `not_claim`, with an optional note, and exports those
  decisions for error analysis. This review interface does not itself decide
  the evidence-search or adjudication standard.
- On 2026-09-14, the researcher requested a webpage to investigate the completed
  broad results. The local dashboard now defaults to frozen broad run
  `5a165612d6459da0`, with all-window and health/science-positive denominators,
  presence versus advancement, nonexclusive category rates, and claim review.
  Filters do not redefine model labels; human reviews are stored separately by
  source hash and do not change model prevalence. Older narrow reviews are kept.
- On 2026-09-14, the researcher specified that the additional statement
  classification should concern the product, intervention, or behavior being
  discussed rather than the proposition's logical form. The approved taxonomy
  distinguishes vaccines, pharmaceuticals, peptides/hormones, supplements,
  psychoactive substances, medical technologies, diet, exercise, sleep,
  mental/behavioral interventions, environmental exposures, healthcare,
  conditions, and non-health science. Claim focus and therapeutic-product
  maturity are separate fields. Existing broad-fringe labels are immutable.
- On 2026-09-15, health-object run `e5112711aca03600` was collected: all 8,504
  claim instances map to 7,182 unique statement units, and every existing claim
  and broad-fringe field is unchanged. The model outputs and category summaries
  remain provisional until the stratified human review is completed.
- On 2026-09-15, the researcher requested expansion toward the complete JRE
  archive using the existing inclusion rule: numbered JRE and JRE MMA Show
  releases are included; clips, excerpts, Fight Companion, and unnumbered
  specials remain excluded. Acquisition proceeds in frozen, resumable batches.
  The first older batch contains the ten eligible releases immediately before
  #2542; a companion current batch contains #2551 through #2553, the eligible
  releases published after the original pilot as of the access date.
  The current 129 kbps M4A format cannot fit the full archive on the available
  disk, motivating the storage decision recorded below.
- On 2026-09-15, the researcher chose metadata and transcripts rather than
  archive-wide local audio retention. The frozen official RSS snapshot contains
  2,660 eligible episodes after applying the documented Fight Companion
  exclusion, totaling 7,110.43 declared audio hours. Twenty-three existing raw
  episode records are reused and 2,637 metadata-only records were created.
  AssemblyAI will receive public RSS enclosures server-to-server in resumable
  batches of at most ten episodes by default. New transcript Markdown is stored
  with gzip-compressed provider and normalized JSON; no billable archive jobs
  were submitted while implementing this choice.
- On 2026-09-15, after reviewing the archive-wide cost estimate, the researcher
  restricted transcription to the 40 most recent eligible RSS releases. The
  frozen subset totals 110.80 hours; ten episodes already have transcripts, so
  30 episodes and 82.61 hours remain. The configured estimate for the remaining
  transcription is $27.26, processed in resumable batches of at most ten.
- On 2026-09-16, the researcher authorized completion of the latest-40 subset.
  All 40 episode transcripts are now present and readable, with 40 unique
  episode IDs and 40 unique AssemblyAI job IDs. The final 20 episodes comprised
  53.69 declared hours across two ten-episode batches, with a configured cost
  estimate of $17.72; this is an estimate rather than a measured invoice total.
  AssemblyAI's optional speaker-name identification failed for JRE MMA Show
  #182 after transcription and diarization succeeded. That transcript is
  retained with generic diarized labels and an explicit
  `skipped_after_provider_failure` status; its speaker identities require human
  review. The other 39 transcripts retain machine-inferred names that also
  require human verification.

## Decisions still required from the researcher

On 2026-09-16 the researcher requested classification of the remaining newly
transcribed JRE episodes. The exact new-episode complement is frozen as
`config/jre_latest_40_new_30_2026-09-16.json`: 30 episodes, 952,927 transcript
words and 7,399 overlapping 256-word Stage-04 windows. Thirty independently
resumable GPT-5.6 Luna Batch jobs were submitted for health/science screening;
the ten original JRE episodes were not resubmitted. Later stages use this
30-episode sample so the original claim, broad-fringe, health-object and veracity
runs remain immutable. Model outputs remain provisional and require human review.


On 2026-09-16, after receiving the pilot and full-run cost estimates, the
researcher instructed running the full classification. Frozen veracity run
`03b4d55da8851b87` was submitted as Batch
`batch_6aaa58a741a88190a222097da306cf70`: 7,182 statement units, 8,504 linked
instances and 3,114 requests. The smaller pilot was still processing at that
time; no pilot accuracy or cost result was represented as available. The full
run applies the disclosed provisional veracity and separate danger codebook.
Existing classification stages are not rerun. Evidence validation remains pending.

On 2026-09-16, after the full-run upload confirmation question, the researcher
requested cost information and instructed testing a smaller subset first. Only
a 20-statement technical pilot was initially submitted. The disclosed implementation selects
health/both statements by deterministic hash order, round-robin across shows
(ten per show), retaining all 24 linked instances. This is a technical smoke test,
not an approved representative validation sample or a change to the analytic
corpus. The full run was subsequently authorized as recorded above. Only the new veracity
and danger augmentation runs; existing classification stages are not rerun.

On 2026-09-16 the researcher requested OpenAI-based veracity augmentation of the
existing statements: supported, exaggerated, unsupported, contradicted and
dangerous. `notes/VERACITY_CLASSIFICATION.md` and
`config/veracity_classification.json` contain the proposed operational codebook.
It preserves the existing statement units, prior classifications and human notes;
danger is a separate proposed dimension, with uncertainty and non-assessable
statuses retained. This is a model-knowledge-only provisional pass. Operational
definitions, the separate danger field, assessment-time rather than historical
evidence, and an evidence-search/adjudication protocol still require researcher
adoption before use as reported research measures. The request authorizes adding
and applying a candidate API classifier; it does not validate its judgments.

The 2026-09-14 request broadens fringe to non-mainstream claims and exaggeration,
without equating either with misinformation. The operational codebook is
`notes/BROAD_FRINGE_CLASSIFICATION.md`: scientific position and exaggeration are
independent, uncertainty is retained, and claim presence is separated from
asserted/tentative advancement. Extent is reported per episode using all windows
and Stage-04-positive windows as separate denominators. This requires a fresh
classification of all 2,166 positive windows; the earlier narrow labels are a
historical baseline, not estimates of the broader construct.

The new batch was explicitly authorized and completed on 2026-09-14: all 2,166
requests succeeded. Frozen run `5a165612d6459da0` retains 4,124 windows and 8,504
overlapping claim instances. The model flagged 1,679 windows for broad claim
presence and 1,578 for assertion/tentative advancement. These remain provisional
model judgments, with exaggeration a particularly important calibration target.

1. What is the precise research question: prevalence, framing, diffusion, or a
   comparison across shows, speakers, or time?
2. What is the sampling frame, period, language scope, and inclusion/exclusion
   rule for podcasts and episodes?
3. Which evidence sources, search procedure, and human adjudication rule will
   convert the provisional claim-level fringe screen into a validated measure?
4. How will factual accuracy, misinformation, intent, and harm be
   operationalized if they are later added as separate outcomes?
5. Does the $27.26 estimated cost for the remaining 30 episodes fit the
   transcription budget? The first ten-episode batch is estimated at $9.55.
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
