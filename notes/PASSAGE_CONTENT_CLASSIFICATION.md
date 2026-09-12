# Stage 05: claim extraction and provisional fringe classification

## Purpose

Stage 04 is a broad, recall-oriented screen: it asks whether overlapping
256-word windows contain health-related or science-related discussion. Stage 05
turns the positive windows into inspectable transcript snippets, rechecks their
health/science relevance, extracts exact checkable claims, and provisionally
classifies each claim's relationship to scientific consensus.

The final analytic file has one row per extracted claim and repeats the source
snippet, episode, speaker, word range, and timestamps. If a snippet contains no
sufficiently precise checkable claim, it receives one row with
`fringe_status=not_assessable`. This keeps every screened snippet visible.

Stage 05 is a model-assisted screen based on the model's general scientific
knowledge. It does not search literature or supply evidence citations. Every row
is marked for human review, and the evidence and human-decision columns remain
empty until that review occurs.

## Snippet construction

1. Read the collected Stage 04 classifications for every episode in a frozen
   sample.
2. Keep a window when `health_related = 1` or `science_related = 1`.
3. Merge consecutive positive windows when they overlap. Do not merge across a
   negative window.
4. Split a merged region longer than the proposed 512-word maximum at an
   utterance boundary when possible. The researcher must confirm this proposed
   maximum before submission.
5. Reconstruct each snippet exactly from the word-level transcript.
6. Send one request per snippet to OpenAI Batch.

The merge removes duplicated words created by the 256-word/128-word screen.
Separate snippets never share a word. Snippet boundaries can still contain
surrounding speech because Stage 04 classifies complete windows.

## Passage-level fields

- `confirmed_health_related`: substantive content about physical or mental
  health, illness, diagnosis, prevention, treatment, healthcare, or health
  behavior.
- `confirmed_science_related`: substantive content about scientific research,
  evidence, methods, mechanisms, experts, institutions, or another scientific
  subject.
- `passage_rationale`: a short explanation of the reassessment.

Stage 04 labels remain in the CSV beside the confirmed Stage 05 labels so that
screening false positives can be inspected.

## Claim extraction

A claim must be a checkable health- or science-related assertion. The model must
copy it as an exact contiguous quotation from the snippet. It must not turn a
question, joke, vague opinion, or personal experience into a claim unless the
speaker also asserts a generalizable fact, cause, effect, risk, or recommendation
premise. One snippet may contain zero, one, or multiple claims.

Each claim receives:

- `claim_domain`: `health`, `science`, or `both`;
- `claim_type`: descriptive/empirical, causal/mechanistic, intervention effect,
  safety/risk, recommendation, prediction, or other checkable claim;
- `consensus_relation`: its provisional relationship to established scientific
  understanding;
- `fringe_status`: `fringe`, `not_fringe`, or `uncertain`;
- `fringe_reason`: a short explanation without invented sources.

## Fringe classification

The researcher approved the following rule on 2026-09-12:

- `fringe`: the claim clearly conflicts with established scientific consensus,
  or it presents an extraordinary unsupported position as established
  knowledge.
- `not_fringe`: the claim is consistent with established scientific
  understanding or falls within legitimate scientific debate.
- `uncertain`: evidence is mixed, evolving, missing, specialized, or
  insufficient for a reliable determination.
- `not_assessable`: no sufficiently precise, checkable health/science claim was
  extracted from the snippet. This value is added locally rather than returned
  by the model.

The model must use `uncertain` conservatively instead of forcing a binary answer.
The code also checks that consensus and fringe labels agree:

| Consensus relation | Required fringe status |
| --- | --- |
| `consistent_with_consensus` | `not_fringe` |
| `within_legitimate_debate` | `not_fringe` |
| `conflicts_with_consensus` | `fringe` |
| `extraordinary_unsupported` | `fringe` |
| `insufficient_information` | `uncertain` |

Fringe is not synonymous with factual inaccuracy. A minor factual error is not
automatically fringe, and Stage 05 does not classify misinformation, intent, or
harm.

## Illustrative example

For this invented snippet:

> Cold showers triple testosterone for the entire day. They also make some
> people feel more alert.

Stage 05 should produce two claim rows. The first might be `fringe` if the model
judges the specific extraordinary effect to conflict with established evidence.
The second should be `uncertain` if the subjective and context-dependent wording
does not support a reliable consensus classification. Both rows repeat the same
snippet and timestamps while preserving different exact claim text.

## Output

Successful collection creates:

- `batch_output.jsonl`: raw provider responses;
- `claim_classification.csv`: one row per extracted claim, plus one
  `not_assessable` row for every snippet without a claim;
- `classification_summary.json`: episode and sample totals for confirmed
  health/science snippets, extracted claims, consensus relations, and fringe
  statuses.

The CSV reserves `evidence_sources` and `human_decision` columns for review and
sets `needs_human_review=1` on every row.

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
local and free. Only `submit --yes` sends transcript snippets to OpenAI and
creates a billable Batch job.
