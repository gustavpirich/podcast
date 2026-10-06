# Descriptive analysis plan: the supply and demand of fringe information on podcasts

Status: **draft, 2026-10-01.** Drafted with an AI agent from the researcher's
requests on 2026-10-01. Items marked *Decision* are not adopted until the
researcher confirms them and they are recorded in `PLAN.md`.

## Headline

**The supply and demand of fringe information on podcasts.**

- **Supply:** how much fringe scientific information the most popular podcasts
  air, and who supplies it (guests versus hosts).
- **Demand:** how audiences respond to episodes that carry more or less fringe
  information.

All results are descriptive. They do not estimate whether podcasts cause belief
change or raise the credibility of guests.

## Working definition of a fringe claim (proposed)

A fringe claim is a substantive empirical claim about health or the natural
world that departs from the position held by the relevant scientific community
at the time of broadcast, and that the speaker presents as true or plausible.

All four conditions must hold:

1. **Empirical:** testable in principle; excludes opinions, values, political
   positions, jokes and pure hypotheticals.
2. **Generalizing:** extends beyond the speaker's own experience.
3. **Departs from consensus:** judged against major scientific bodies, clinical
   guidelines and systematic reviews as of the episode date.
4. **Advanced:** asserted or entertained as plausible; merely reported or
   rejected claims are excluded.

| Tier | Meaning | Existing broad code |
| --- | --- | --- |
| A. Emerging / minority | Some credible evidence; not accepted by the field | `emerging_non_mainstream` |
| B. Speculative / alternative | Little or no credible evidence, or outside established frameworks | `alternative_speculative` |
| C. Contradicts consensus | Conflicts with well-established evidence | `contradicts_consensus` |

Not fringe: mainstream claims; legitimate open debate without a consensus;
exaggeration of a mainstream claim on its own (reported as a separate dimension).
Condition 4 maps to broad `stance` in {`asserted`, `tentative`}.

Literature anchoring: *[researcher to add citations]*.

- Decided 2026-10-01: all three tiers are fringe, each reported separately.
- Decided 2026-10-01: exaggeration-only claims are excluded from the definition
  and reported as a separate dimension.
- Limitation: the existing broad labels did not explicitly apply conditions 1–2
  (empirical, generalizing), so offhand remarks can be coded fringe. Human
  validation must estimate how often.

## Evidence 1 — Supply: how much fringe information is aired?

- Share of transcript time and words inside advanced fringe claims (overlapping
  windows counted once), against all content and against health/science content.
- Share of unique statements that are fringe, by tier.
- By show and by episode; topics/objects of fringe claims (supplements,
  peptides, psychoactives, vaccines, ...).
- Uncertain labels kept separate; bounds with uncertain counted as fringe and
  as not fringe.

## Evidence 2 — Supply: who supplies it?

- Attribute each claim to its speaker (deterministic word-index join with the
  diarized transcript; no new model calls). Host versus guest share of fringe
  claims.
- Guest-level count: guests who advanced none, incidental (1–2), or recurrent
  (3+ or a set share) fringe claims; tier-A-only reported separately.
- Headline sentence: "X of N guests advanced at least one fringe claim; Y did so
  recurrently."
- *Decision:* guest thresholds (report sensitivity across cutoffs).

## Evidence 3 — Demand: how do audiences respond?

- Episode-level audience metrics: YouTube views, likes and comments at a single
  recorded access date; possibly chart ranks.
- Compare demand across episodes by fringe intensity within each show (rank
  comparison and scatter plots; no causal interpretation).
- Known problems:
  - Views are cumulative, so episode age at the access date must be recorded
    and normalized (for example, views relative to same-age episodes of the
    same show).
  - Guest fame confounds any association between fringe content and views.
  - 17 RSS-only JRE episodes have no matched YouTube ID yet.
  - Small number of episodes; descriptive only.
- *Decision:* demand metric and source; whether comment content (reception) is
  in scope, given platform terms and privacy.

## Sample

| Option | Episodes | Labels | Cost |
| --- | --- | --- | --- |
| Pilot | 20 (10 JRE, 10 DOAC) | Broad (fits the definition) | None |
| Latest 40 JRE + 10 DOAC | 50 | Narrow only (no tiers) | None |
| Extend broad run to remaining 30 JRE | 50 | Broad | API cost; estimate first |

- *Decision:* sample. For demand analysis, more episodes matter; extending the
  broad run to 50 episodes is the likely best option.
- *Decision:* does "most popular podcasts" stay JRE + DOAC, or follow a defined
  chart frame (source, country, date, top N)? A frame requires new transcription.

## Decisions recorded 2026-10-01

- Fringe = tiers A + B + C, each reported separately.
- Exaggeration alone excluded (confirmed).
- Start with the 20-episode pilot.
- Demand = YouTube views and engagement.
- Human validation: stratified sample of 150 model-coded fringe claims before
  tables and figures (`code/16_draw_fringe_validation_sample.py`,
  `notes/FRINGE_VALIDATION_CODING.md`).

## Audience snapshot

`code/15_snapshot_youtube_metrics.py` wrote
`data/raw/audience_metrics/youtube/20261001T205301Z/metrics.json` (20/20
episodes, yt-dlp 2026.08.19). Notes for the demand analysis:

- Views and likes are exact; comment counts above 1,000 are rounded by YouTube
  (for example, 2,100 or 28,000).
- Episode age should use the YouTube `upload_date`. Ray Dalio (DOAC) was
  uploaded on 2026-07-30, three weeks before its RSS date of 2026-08-20.
- The snapshot was taken 21–63 days after YouTube upload (Ray Dalio: 63 days
  by YouTube date, 42 by RSS date), so age normalization is required.

## Cost

Measured cost of the pilot broad run `5a165612d6459da0` (2,166 requests), from
recorded usage and `config/openai_veracity_pricing_2026-09-16.json` rates:
934,512 uncached input tokens ($0.093), 2,550,370 cached input tokens ($0.026)
and 1,448,111 output tokens ($0.869): **about $0.99**.

Extending the broad run to the remaining 30 latest-40 JRE episodes (3,396
screen-positive windows, 1.57 times as many) is estimated at **$1.55–$1.91**
(with and without the same cache rate). Rates must be rechecked before any
submission.

## Steps

| Step | Output | Check | New cost |
| --- | --- | --- | --- |
| 0. Researcher confirms decisions | Entry in `PLAN.md` | — | — |
| 1. Build statement-level dataset | `data/derived/descriptives/statements.csv` | Unique statement IDs; each maps to one episode | No |
| 2. Speaker attribution | Speaker and host/guest columns | Match rate; manual check of ~30 claims; flag JRE MMA #182 | No |
| 3. Evidence 1 and 2 tables and figures | `output/descriptives/` | Totals reconcile with existing reports | No |
| 4. Acquire audience metrics | New raw metadata snapshot with access date | One row per episode; IDs match | No (public metadata) |
| 5. Evidence 3 tables and figures | `output/descriptives/` | Age normalization documented | No |
| 6. Human validation sample | Review CSV | Agreement by tier and show | No |
| 7. Combined report | `output/descriptives/report.md` | Every number traces to a script | No |
