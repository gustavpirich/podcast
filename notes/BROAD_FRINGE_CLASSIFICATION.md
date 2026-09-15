# Broad fringe science: operational classification

## Researcher request and scope

On 2026-09-14 the researcher broadened the target from clearly conflicting or
extraordinary unsupported claims to claims outside the scientific mainstream,
including emerging ideas and exaggeration. These claims may be true, false, or
unresolved. The broad measure is not a misinformation measure.

The following operationalization implements that request. It is provisional and
requires researcher review before use as a validated research measure. The pilot
contains the existing ten JRE and ten Diary of a CEO episodes. Keep the previously
approved 256-word windows, 128-word stride, and 768-word episode minimum.
Include health claims as well as other science claims, matching the original
research scope. Stage 04 remains the topical screen.

## Independent dimensions

| Dimension | Codes | Interpretation |
| --- | --- | --- |
| Scientific position | `mainstream`, `emerging_non_mainstream`, `alternative_speculative`, `contradicts_consensus`, `uncertain` | How the exact proposition relates to scientific understanding at the episode date. |
| Exaggeration | `yes`, `no`, `uncertain` | Whether the actual wording materially exceeds what the evidence supports. |
| Stance | `asserted`, `tentative`, `reported`, `rejected`, `unclear` | Whether the proposition is advanced, entertained, reported, or criticized locally. |

An emerging minority interpretation with credible support can be non-mainstream
without being misinformation. An alternative hypothesis with little support can
be speculative without being disproven. A claim can also use an accepted mechanism
to exaggerate a benefit. These are separate, potentially overlapping phenomena.

Normal disagreement within mainstream research, novelty alone, unfamiliarity to
the model, absence of an on-air citation, enthusiasm, and a cautiously described
single study do not automatically qualify. Exaggeration needs an identifiable
mismatch between the wording and the evidence. Missing information stays uncertain.

## Derived outcomes

The claim-level broad flag is positive if scientific position is emerging,
alternative/speculative, or contradicts consensus, OR exaggeration is yes.
If neither dimension is positive but either is uncertain, retain uncertain.
Otherwise the claim is not fringe under this definition.

Report two window measures:

1. **Broad claim present:** at least one broad claim appears in the window,
   including a quotation used for criticism. This measures discussion, not belief.
2. **Broad claim advanced:** at least one broad claim is asserted or tentatively
   advanced. Reported/rejected claims are excluded; unclear stance stays uncertain
   if there is no definite positive. This prevents debunking from counting as
   endorsement. Tentative discussion is not described as firm endorsement.

For each measure, positive takes precedence over uncertain, then not-fringe.
Empty claim arrays are `not_assessable`; screen-negative windows are
`not_screened`. Neither implies every statement in that window is scientifically
valid. Preserve all individual claims and all dimensions for inspection.

Quotation alignment uses the existing exact/case-insensitive/unique-token method.
An unmatchable quotation has an uncertain final flag, while retaining the model's
raw codes and text. Do not silently discard it or use it as a verified quote.

An explanation longer than the requested 80 words is preserved in full and
flagged with `reason_over_word_limit`; this formatting issue does not change
the substantive codes. Empty explanations and invalid coding fields still fail
collection. The first broad batch returned seven explanations of 81–98 words;
retaining them prevents a formatting deviation from discarding valid results.

## Measuring extent

Primary denominator: **all standardized windows in that episode**. The statistic
is the percentage of windows containing at least one qualifying claim, not the
percentage of statements that are false, the fraction of speaking time, or a
unique-claim count. The Stage-04 conditional screen can miss relevant windows.

Secondary denominator: **Stage-04 health/science-positive windows**, to distinguish
how often an episode discusses science from how often that discussion includes
qualifying claims. Show both denominators and the counts. Include uncertainty
separately. Category percentages can overlap and must not be added.

Adjacent windows share 128 words; their observations are dependent and a spoken
claim can recur. Do not sum window durations as airtime or use independent-window
binomial confidence intervals. Show-level pooled percentages weight longer
episodes more heavily; also retain the unweighted mean of episode percentages.
These 20 selected recent episodes do not establish show-wide population rates.

## What can be measured before the new run

The old pilot's `fringe` labels reflect the narrower definition. Its
`within_legitimate_debate` code does not identify which positions are mainstream
and which are emerging minorities; `uncertain` is not a proxy for broad fringe.
The old results also lack an exaggeration and stance dimension. Consequently,
there is no defensible numeric conversion to the new broad definition and no
known lower/upper bound from simply adding old categories.

Graphs made before new results are available must say **legacy narrow screen**.
They describe existing provisional model classifications, not a new broad-fringe
measurement. Re-extract and classify claims from all Stage-04-positive windows
using the new prompt; do not select only the previously flagged windows.

## Implementation and provenance

`config/broad_fringe_classification.json` contains the complete definitions and
reason format. `code/08_classify_broad_fringe.py` freezes the input CSV, config,
prompt, request schema, and publication metadata into a content-addressed run.
It prepares one request per positive window and retains all windows on collection.
Existing Stage-05 files and dashboard results remain historical outputs.

```bash
conda run -n podcast_observational python code/08_classify_broad_fringe.py prepare
conda run -n podcast_observational python code/08_classify_broad_fringe.py submit --yes
conda run -n podcast_observational python code/08_classify_broad_fringe.py status
conda run -n podcast_observational python code/08_classify_broad_fringe.py collect
```

Only submit uploads text to the already authorized OpenAI service and incurs
API charges. Credentials must be provided by the environment. Requests retain
GPT-5.6 Luna with low reasoning effort. Batch mechanics follow the
[official Batch API documentation](https://developers.openai.com/api/docs/guides/batch),
accessed 2026-09-14. The definitions above are this project's operational choices,
not definitions endorsed by that documentation.

Inspect quotes and evidence rationales across categories, both shows, and uncertain
cases. The model's scientific judgments need human evidence review. Corrected labels,
supporting sources, publication dates, and adjudication decisions should be retained;
the coding and evidence-review standard must be settled before manuscript inference.
