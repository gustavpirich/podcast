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

## Decisions still required from the researcher

1. What is the precise research question: prevalence, framing, diffusion, or a
   comparison across shows, speakers, or time?
2. What is the sampling frame, period, language scope, and inclusion/exclusion
   rule for podcasts and episodes?
3. Should later claim-level or speaker-level analyses use a different unit from
   the selected overlapping-window screen?
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
