# Stage 05: health/science passage content classification

## Purpose

Stage 04 is intentionally broad: it asks whether each overlapping 256-word
window contains health-related or science-related discussion. Stage 05 asks what
kind of content appears inside those candidates. It still does **not** decide
whether a statement is true, fringe, misleading, harmful, or misinformation.

This separation matters methodologically. Finding candidate material is a
recall-oriented screening task; characterizing the material is a separate
measurement task. Accuracy and fringe-status coding require a later claim-level
protocol with external scientific evidence and human adjudication.

## Unit construction

1. Read the collected stage-04 window classifications for every episode in a
   frozen sample.
2. Keep a window when `health_related = 1` or `science_related = 1`.
3. Merge consecutive positive windows when they overlap. Do not merge across a
   negative window.
4. Reconstruct the merged passage exactly from the word-level transcript.
5. Send one request per merged passage to OpenAI Batch.

The merge removes duplicated words created by the 256-word/128-word screen. A
run of one positive window contains 256 unique words; two consecutive positive
windows contain 384 unique words; three contain 512. Separate passages never
share a word. This makes unique-word and passage-time totals interpretable,
although the screen's window boundaries still include some surrounding speech.

## Health-topic codebook

Health topics are multi-label because one passage can discuss, for example, a
condition and its treatment. One topic is also selected as the primary topic so
that mutually exclusive descriptive totals can be produced.

| Code | Meaning |
| --- | --- |
| `conditions_symptoms_diagnosis` | Physical diseases, injuries, symptoms, risks, diagnosis, prognosis, or testing. |
| `mental_health_cognition` | Mental health, psychiatric conditions, cognition, memory, neurodevelopment, or psychological treatment. |
| `lifestyle_fitness_prevention` | Exercise, fitness, sleep, nutrition, weight, recovery, prevention, or health behavior. |
| `treatments_health_products` | Medicines, procedures, therapies, supplements, devices, products, or purported remedies. |
| `substance_use_addiction` | Alcohol, nicotine, drugs, dependence, addiction, withdrawal, or harm reduction. |
| `healthcare_public_health` | Healthcare systems, clinicians, access, population health, outbreaks, vaccination programs, or policy. |
| `other_unclear_health` | Substantive health content not fitting the other categories. |

## Other coded dimensions

- `content_type`: the dominant function—personal experience, factual/causal
  claim, advice/recommendation, research/expert/institution discussion, or
  general conversation.
- `support_type`: no explicit support, personal anecdote, expert authority,
  study/data, or mixed support.
- `health_action_recommended`: whether a health action, treatment, product, or
  behavior is advised, endorsed, prescribed, or discouraged.
- `claim_present`: whether at least one checkable health/science assertion is
  present. This is not an accuracy judgment.
- `science_content_type`: research/data, causal or biological mechanism,
  scientific expert/institution, general science, or other science.

Stage 05 rechecks the two broad labels as `confirmed_health_related` and
`confirmed_science_related`. This allows false-positive screen passages to be
recorded rather than forced into a topic.

## Quantities produced

The summary reports passage counts, unique word counts, and elapsed passage
time. Health and science totals may overlap because the labels are independent.
Primary health-topic totals are mutually exclusive among confirmed health
passages; multi-label topic lists are retained in the CSV for other analyses.

The amount of health content for an episode is provisionally:

`confirmed health passage words / all transcript words`

The analogous measure is produced for science content. These are model-assisted
passage-level estimates, not exact claim spans. Validate a stratified sample
against independent human coding before treating them as research results.

## Reproducible workflow

Run stage 04 through `collect` for every episode in a frozen sample. Then:

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

`prepare` is local and free. Only `submit --yes` sends selected transcript text
to OpenAI and creates a billable Batch job. Configuration, prompt definitions,
source hashes, exact passages, requests, provider response IDs, and token usage
are retained under `data/derived/classifications/openai_passage_content/`.
