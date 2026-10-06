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

- On 2026-10-01, the researcher set the descriptive headline "The supply and
  demand of fringe information on podcasts" (`notes/DESCRIPTIVES_PLAN.md`) and
  decided that emerging/non-mainstream, alternative/speculative and
  consensus-contradicting claims are all fringe, reported as three tiers. Only
  claims the speaker asserts or entertains count. The analysis starts on the
  20-episode broad-fringe pilot; demand is measured with YouTube views and
  engagement. Exaggeration alone stays a separate dimension (confirmed the same
  day). Guest thresholds remain open. The researcher approved a stratified human
  validation sample of 150 model-coded fringe claims before tables and figures,
  and a public YouTube metrics snapshot (taken 2026-10-01T20:53Z, 20/20 episodes).

- On 2026-10-02, the researcher defined a larger corpus of popular US podcasts.
  Popularity source: the Edison Research (now SSRS) "Top 50 Podcasts in the
  U.S." releases from Q4 2021 to Q2 2026 (17 releases; there is no separate
  Q1 2023 list). Releases up to Q3–Q4 2022 rank adults 18+ over a rolling
  period; later ones rank one quarter of listeners 13+, so ranks are not
  strictly comparable. Genres: shows whose own primary RSS category is Comedy,
  Health & Fitness, or Education > Self-Improvement. Episodes: all episodes
  published 2021-10-01 to 2026-09-30, excluding trailers. Speakers: hosts are
  named from the show configuration and other voices are labelled by role
  (guest) rather than by per-episode guest names. Using the primary rather
  than any listed category was confirmed the same day. The Edison lists are
  published as images and were transcribed by an AI model
  (`config/edison_top50_transcribed.csv`, `human_verified = 0`); spot checks
  against the archived images are required. Transcription spending requires
  separate approval after the free episode count and cost estimate.
  Later the same day the researcher asked for three transparent criteria for
  popular, health/comedy, long-form conversational ("Joe Rogan-like") shows.
  Adopted: (1) listed in an Edison release above; (2) primary RSS category
  Comedy, Health & Fitness, or Education > Self-Improvement; (3) median episode
  length in the window of at least 60 minutes. Of 111 listed shows, 106 had a
  public feed and 29 meet all three (10,957 episodes, 18,047 hours; frame
  `data/derived/popular_frame/20261002T193807Z/`). Hosts are taken only from
  names printed in each feed; maximum diarized speakers = hosts + 3 (4-10),
  with Kill Tony (10) and Full Send (6) as noted exceptions. The configured
  transcription estimate is about $5,900 for the untranscribed episodes and is
  not yet approved.
- On 2026-10-02 the researcher approved a 10-episode AssemblyAI pilot (Huberman
  Lab 3, Theo Von 2, Kill Tony 2, Distractible 3; 15.6 audio hours, configured
  estimate $5.13). All 10 completed with Universal-3.5 Pro. The pilot showed
  that AssemblyAI can split one host into "Name - 1"/"Name - 2" and can name a
  guest itself instead of using the "Guest" label. Rule implemented in
  `02_transcribe_assemblyai.py` (requires researcher confirmation): split host
  names merge back to the configured host; "Guest"/"Guest - N" and any other
  person named by the provider are role Guest (the latter flagged
  `named_by_provider_not_in_roster`); bare diarization letters stay
  Unidentified (in the pilot: ads and producers, 0-11% of words). The pilot
  outputs were rebuilt from the saved provider responses (no new
  transcription). AssemblyAI's pricing page, checked directly on 2026-10-02,
  confirms the recorded rates: Universal-3.5 Pro $0.21/hour, diarization
  $0.02/hour, speaker identification $0.02/hour at low effort and $0.10/hour at
  the medium effort used here ($0.33/hour in total). The full-run estimate is
  about $5,900 for the remaining ~17,900 hours and is not yet approved.
- On 2026-10-03 the researcher judged the full AssemblyAI run too expensive and
  narrowed the focus to about ten shows (including JRE, Theo Von and The Diary
  of a CEO; the final ten are not yet fixed). Free official transcripts with
  named speakers exist only for Lex Fridman (from June 2023) and Mel Robbins;
  third-party transcript sites restrict reuse. The researcher chose to
  implement free local transcription: Whisper large-v3-turbo (MLX) plus
  pyannote community-1 diarization, with GPT assigning host/guest roles
  afterwards (`code/02_transcribe_local.py`, output in
  `data/derived/transcripts_local/`). A first transcription-only test on a
  38-minute pilot episode ran at about 10x real time on the M2 Pro and agreed
  with the AssemblyAI text on 95.6% of words (jiwer word error rate 4.4%,
  AssemblyAI as reference; not ground truth). Diarization awaits a Hugging
  Face token.
- On 2026-10-03 the researcher focused on The Joe Rogan Experience and chose
  free local transcription. Parakeet TDT 0.6B v2 (MLX) replaced Whisper after
  a three-episode comparison (text difference from AssemblyAI 3.0/5.5/25.4%
  versus 4.4/7.0/29.2% for Whisper; Kill Tony differences are mostly
  dynamically inserted ads that differ between downloads). Pipeline: Parakeet
  + pyannote community-1 locally, then GPT-5.6 Luna names each diarized
  speaker (host/guest/producer/advertisement/other/unknown) from the title,
  description start and at most six 60-word excerpts per speaker
  (`config/speaker_labeling.json`). First run: a random sample of 10 JRE
  episodes 2019-2025 stratified by year, seed 20261003
  (`config/samples/jre_random_2019_2025_n10_seed20261003.json`); 26.8 audio
  hours took 107 minutes on the M2 Pro (about 15x real time); 10/10
  succeeded. Spot checks: host and guests correctly separated, including two
  two-guest episodes and host voices split across labels; one 3% speaker in
  #1885 labelled "Jamie (producer)" is probably a guest. Speaker labels are
  machine-inferred and not human-verified.
- On 2026-10-03/04 the local pipeline was revised after comparison with
  AssemblyAI. Speakers are now assigned per sentence (majority of the
  sentence's time; word-level only for 8+-word sentences where a second
  speaker covers at least 35%), which cut mid-sentence speaker switches from a
  median 39% to about 5% (AssemblyAI: 1%) with little change in word-level
  agreement. The researcher asked to use the RSS title to fix pyannote's
  speaker count when this helps: on #2520 and #2531, an exact count (hosts +
  guests named in the title) raised end-to-end agreement with AssemblyAI after
  GPT naming from 90.9/86.5% to 91.5/89.9%, by removing small mixed crosstalk
  clusters. It is now the default (`--speaker-count title`, falling back to
  2-4 when the title names no guests; the setting is stored per episode).
  Evidence is two episodes only; with an exact count, inserted ads and the
  producer are absorbed into host or guest speech. A further random sample of
  30 JRE episodes 2019-2025 (seed 20261004, excluding the first 10) was
  transcribed and labelled (81.1 audio hours, 30/30 succeeded) before this
  change, with sentence-level assignment and the 2-4 range.

- On 2026-10-03 the researcher asked for a guest database: for every episode
  of the popular long-form comedy / health / self-improvement shows, who is
  interviewed, from 2019 to now. Decisions the same day: (1) the frame window
  starts 2019-01-01 (was 2021-10-01; end unchanged, 2026-09-30), and the five
  Edison rankings before Q4 2021 are added to the popularity list (Q3/Q4 2019
  Top 10; Q3 2019-Q2 2020 Top 30; 2020 Top 50; Q3 2020-Q2 2021 and Q4 2020-Q3
  2021 Top 50; snapshot `data/raw/popularity/edison_top50/20261003T092011Z/`;
  no separate Q1 2021 list was found). The 2019-2020 rankings cover fewer than
  50 shows. (2) Guests are identified only from each episode's RSS title and
  description. A guest is a named person whom the text says takes part in the
  episode and who is not a regular host; roles `guest`, `guest_cohost`,
  `recurring_regular` (e.g. Kill Tony band and regulars) and `mentioned_only`;
  episodes without a named guest get one row with an empty name and a reason.
  (3) Superseded the same day: the researcher does not want to spend money,
  so no model is used. Guests are read with free local text rules
  (`config/guest_rules.json`, `code/18_build_guest_dataset.py`): per-show
  title slots (e.g. JRE "#2426 - Name", "w/ Name", "feat. Name", "Name x Nelk
  Boys"), and, where the title names nobody, description phrases ("my guest
  is", "joined by", "sits down with", "X joins Theo"). Title slots that also
  carry topics only count when the name appears in the description. Hosts and
  listed regulars are never guests. Names are as printed and unverified; a
  human-checked random sample is still needed before analysis. (4) Output:
  one row per episode with a `guests` column, plus one row per episode-guest
  pair with the rule and source text
  (`data/derived/guest_dataset/<frame>/`). First build on frame
  20261003T092332Z: 18,266 episodes, 9,444 with at least one guest, 11,465
  episode-guest rows (after the self-audit fixes below). Coverage is near complete where the title always names
  the guest (JRE 98%, WTF 97%, Good Hang 94%) and low where shows rarely name
  guests in the feed or have none (Small Town Murder, ShxtsNGigs, LOL
  Podcast, Basement Yard, Ear Biscuits, H3 at 0-10%). Self-audit by Claude
  the same day (not a substitute for human checking): 40 random rows match
  the raw RSS; Edison columns correct in 300 random rows; the transcribed top
  10 of four early releases matches the release-page text. On 100 random
  episodes, 83 were fully right, 6 partly right, 10 missed a guest and 1 named
  a place; five rule bugs found there were fixed. On a fresh 60-episode sample
  after the fixes, 52 were fully right, 3 missed a second guest, 4 missed the
  only guest, 1 was ambiguous, and no extracted name was wrong. Main
  weakness: guests named only in mid-description (Mel Robbins, Jay Shetty,
  second Carolla guests) are missed.
- On 2026-10-03 the researcher asked, for each guest row, whether the guest
  talks about science or health in that episode, again without spending
  money. Implemented as a free dictionary screen of the RSS text
  (`code/19_flag_guest_topics.py`, `config/rss_topic_terms.json`), reusing the
  `health_related` / `science_related` definitions of
  `config/content_classification.json`. Before matching, ad sentences and
  sentences repeated across a show's episodes (plugs, recurring ads) are
  removed. Guest-level flags use only the title segment naming the guest and
  the description sentences naming the guest plus the sentence after each;
  episode-level flags (`episode_*`) use the whole cleaned text. This measures
  what the feed says the episode covers, not what is said in the audio, and
  any mention counts (e.g. a comedian's sobriety). Result: 11,465 guest rows,
  1,803 health, 844 science, 2,257 either. Self-audit by Claude (not a
  substitute for human checking): on 60 random guest rows about 51 were
  right before the last fixes; on 30 random flagged rows 24 were clearly
  right, 3 borderline, 3 wrong (e.g. an album title "Khali Sober"). Episodes
  whose RSS text is empty or only a name (some JRE, Kill Tony) can never be
  flagged.
- On 2026-10-03 the researcher asked to add YouTube views, likes, comments
  and other engagement measures to the guest dataset, still at no cost.
  Per-episode audience numbers exist publicly only on YouTube; Apple and
  Spotify publish show-level ratings only. Steps: official channels chosen
  by Claude from YouTube channel search (`config/youtube_channels.csv`; none
  found for Small Town Murder and WTF); channel uploads listed with yt-dlp
  (`20_`, ~18,000 videos); RSS episodes matched to videos by episode number,
  guest name, title words, length and printed dates (`21_`, 12,034 of 18,266
  episodes, 66%); per-video metadata fetched with yt-dlp (`22_`, views,
  likes, comments (rounded by YouTube), upload date, duration, subscribers,
  category, "most replayed" curve); Apple Podcasts star rating and rating
  count per show (`23_`); merge with rates per day online and per 1,000 views
  (`24_`). Each match is checked against the YouTube upload date:
  `yt_match_check` = ok (within 7 days), reupload_likely (number or title
  agrees, e.g. Armchair's back catalogue uploaded 2024-09-01), or
  date_gap_check (possibly another visit by a recurring guest; verify).
  Counts are cumulative at the snapshot time, so older videos have had longer
  to accumulate views. Members-only and age-restricted videos have no
  metrics. Collecting public YouTube metadata at this scale with yt-dlp may
  conflict with YouTube's terms of service; the researcher should confirm
  this is acceptable for publication.
  Rebuilding the frame with the 2019 window (feed snapshot 20261003T092332Z,
  frame `data/derived/popular_frame/20261003T092332Z/`) gives 30 shows and
  18,266 episodes: Adam Carolla Show, Fake Doctors Real Friends and How Did
  This Get Made? enter via the early rankings; Distractible (median 59.9 min)
  and Dumb Blonde (58.0 min) fall below the 60-minute median over the longer
  window. Several feeds do not reach back to 2019 although the show is older
  (e.g. How Did This Get Made? starts 2022-12, Matt and Shane's Secret Podcast
  2019-07, You Should Know has 6 and 3 episodes in 2020-2021), so 2019-2022
  coverage is incomplete for those shows. Open: whether to keep the 60-minute
  rule over the new window, and how to treat truncated feeds.

## Decisions still required from the researcher

On 2026-09-16 the researcher requested classification of the remaining newly
transcribed JRE episodes. The exact new-episode complement is frozen as
`config/jre_latest_40_new_30_2026-09-16.json`: 30 episodes, 952,927 transcript
words and 7,399 overlapping 256-word Stage-04 windows. Thirty independently
resumable GPT-5.6 Luna Batch jobs were submitted for health/science screening;
the ten original JRE episodes were not resubmitted. Later stages use this
30-episode sample so the original claim, broad-fringe, health-object and veracity
runs remain immutable. Model outputs remain provisional and require human review.

On 2026-09-17 all 30 Stage-04 jobs were collected with 7,399 successful and no
failed provider requests. A data-level audit found that the local collector used
only `youtube_video_id` when writing CSV rows, leaving `episode_id` blank for the
17 RSS-only episodes and making episode/window merge keys non-unique. The
collector now uses the canonical transcript ID with an RSS-ID regression test;
all Stage-04 analytic outputs were rebuilt from the unchanged downloaded Batch
responses. The corrected aggregate has 7,399 unique episode/window keys, 2,462
health-positive windows, 1,958 science-positive windows, 1,024 positive for both,
and 3,396 positive for either. Its measured configured Batch cost is $1.199892.
Audited Stage-05 run `32b86e7a88f5` sends exactly those 3,396 positive windows;
it was submitted as Batch `batch_6aabb3a0931881908a91161d76192628`.
The Batch completed with 3,396 successful and no failed provider requests. Six
responses for JRE #2532 copied a mistyped episode-ID component while retaining
the authoritative Batch `custom_id` and correct six-digit window number. The
collector now recovers only that fail-closed pattern, preserves the returned ID
and an audit flag, and continues to reject any window-number mismatch.
Collection produced 7,399 unique episode/window rows across all 30 episodes,
including 3,396 requested Stage-05 windows and 16,136 overlapping claim
instances. Window outcomes are 1,070 fringe, 1,993 uncertain, 250 not-fringe,
and 4,086 not-assessable. The collector flags 325 unmatched claim quotations
and 121 consensus/fringe inconsistencies; all results remain provisional and
require human evidence review.

On 2026-09-21 the researcher requested combined descriptives for the frozen
latest-40 JRE subset. The reproducible report keeps all 9,719 Stage-04 windows,
uses all windows as the primary denominator and 4,583 screen-positive windows
as a secondary denominator, and keeps uncertain, not-fringe, positive windows
without an assessable claim, and screen-negative windows separate. The two
cohorts share the same windowing, selection rule, and narrow fringe definition
but used different prompt versions, which is disclosed as an instrumentation
limitation. These descriptives are not validated misinformation prevalence.


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
