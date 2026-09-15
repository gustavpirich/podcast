# Stage 05: window-level claim and fringe classification

## Intended output

The final file has one row for every standardized transcript window. Each row
contains the episode, timestamps, speakers, complete snippet text, Stage-04
health/science labels, extracted claims, and a provisional window-level fringe
status.

The units are unchanged from Stage 04:

- exactly 256 complete transcript words per window;
- a stride of 128 words, so adjacent windows overlap by 128 words;
- no partial final window;
- only episodes with at least 768 transcript words.

The researcher reports an intended final JRE corpus of 466,328 windows. That
full corpus is not currently in this repository. The local ten-episode JRE pilot
contains 2,320 windows, and the ten-episode Diary of a CEO pilot contains 1,804.

## Stage-05 selection

Stage 05 reads the collected Stage-04 CSVs and reconstructs the same windows
from the word-level transcripts. It sends a window to the model only when its
Stage-04 `health_related` or `science_related` label is positive. Stage-04
negative windows are not sent again, but they remain in the final CSV with
`stage05_requested=0` and `fringe_status=not_assessable`.

Stage 04's positive health/science label is retained as the window's topical
classification. Stage 05 does not recheck it. The model extracts every distinct,
checkable health- or science-related claim as an exact contiguous quotation from
that 256-word snippet. Questions, jokes, vague opinions, and personal experiences
are not claims unless they also assert a generalizable fact, cause, effect, risk,
or recommendation premise.

## Fringe classification

The researcher approved the following rule on 2026-09-12:

- `fringe`: a claim clearly conflicts with established scientific consensus or
  presents an extraordinary unsupported position as established knowledge.
- `not_fringe`: a claim is consistent with established scientific understanding
  or falls within legitimate scientific debate.
- `uncertain`: evidence is mixed, evolving, missing, specialized, or
  insufficient for a reliable determination.
- `not_assessable`: the window contains no sufficiently precise checkable
  health/science claim. This is derived locally rather than returned for a claim.

Each extracted claim also receives a domain, claim type, consensus relationship,
and a three-sentence plain-language reason. The reason explains what the claim
means, whether established scientific evidence supports, disputes, or does not
clearly resolve it, and why that assessment leads to the assigned fringe status.
It distinguishes absence of evidence from evidence against a claim and does not
infer the speaker's beliefs, intentions, or ideology. If the model's consensus
relationship and fringe status disagree, both raw values are retained, the final
status is conservatively set to `uncertain`, and the inconsistency is counted for
human review.

The collector also checks every claimed quotation against the source window. It
accepts an exact substring or deterministically recovers the original source
span when only capitalization or punctuation differs and the token sequence is
unique. `claims_json` records the model text, recovered exact text, and match
method. An ambiguous or missing quotation remains visible as model text, is
flagged as unmatched, and receives a conservative final status of `uncertain`.

## Window-level rule

The CSV retains the full claim list in `claims_json`, but its main
`fringe_status` column is one value per 256-word window:

1. `fringe` if the window contains at least one fringe claim;
2. otherwise `uncertain` if it contains at least one uncertain claim;
3. otherwise `not_fringe` if it contains at least one not-fringe claim;
4. otherwise `not_assessable`.

Separate count and text columns show which claims produced that value. Because
adjacent windows overlap, the same spoken claim may appear in two windows. Window
counts are valid for the stated window-level analysis, but summed claim counts
must not be described as counts of unique claims.

## Example

For this invented 256-word snippet excerpt:

> Cold showers triple testosterone for the entire day. They also make some
> people feel more alert.

the model might extract two claims. If the first is `fringe` and the second is
`uncertain`, the window-level `fringe_status` is `fringe` because the window
contains at least one fringe claim. Both exact claims and both individual labels
remain visible in `claims_json`; the fringe claim also appears in
`fringe_claim_texts`.

## Output columns

Important columns in `window_claim_classification.csv` include:

- identifiers: `show`, `episode_id`, `episode_title`, `snippet_id`, `window_id`;
- location: word indices, utterance IDs, timestamps, duration, and speakers;
- text: `snippet_text` and `speaker_segments_json`;
- Stage 04: screen labels, rationales, audit flag, response ID, and model;
- Stage 05: request flag and claim-level coding;
- claims: total and status-specific counts, claim text, quotation-match counts,
  domains, types, consensus relationships, and `claims_json`;
- outcome: `fringe_status` with values `fringe`, `not_fringe`, `uncertain`, or
  `not_assessable`;
- review: blank `evidence_sources` and `human_decision` fields plus
  `needs_human_review=1`.

Stage 05 is a provisional model-assisted screen based on the model's general
scientific knowledge. It does not search literature or create evidence
citations. Human evidence review is required before treating the fringe labels
as validated research measurements. Fringe is also distinct from factual
accuracy, misinformation, intent, and harm.

## Reproducible workflow

Run Stage 04 through `collect` for every episode in a frozen sample. Then:

```bash
python code/05_classify_passage_content_openai_batch.py prepare \
  --sample config/doac_starter_sample.json

export OPENAI_API_KEY='your-key-in-this-terminal-only'
python code/05_classify_passage_content_openai_batch.py submit \
  --sample config/doac_starter_sample.json --yes
python code/05_classify_passage_content_openai_batch.py status \
  --sample config/doac_starter_sample.json
python code/05_classify_passage_content_openai_batch.py collect \
  --sample config/doac_starter_sample.json
```

Use `--sample config/jre_starter_sample.json` for the JRE sample. `prepare` is
local and free. Only `submit --yes` sends selected windows to OpenAI and creates
a billable Batch job.
