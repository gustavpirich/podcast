# Health and science content classification — pilot codebook

## Purpose

This first-stage screen describes how much of a podcast transcript discusses
health and how much discusses science. It does **not** classify truth, scientific
consensus, fringe status, misinformation, intent, or harm.

The researcher approved this simplified scope on 2026-09-10. The transparent
dictionary baseline uses AssemblyAI speaker turns. The model-assisted pipeline
uses overlapping 256-word windows with a stride of 128 words and excludes
episodes shorter than 768 words.

## Labels

### `health_related`

Code `1` when a turn discusses physical or mental health, illness, symptoms,
diagnosis, treatment, prevention, sleep, exercise, nutrition, substance use,
healthcare, or a personal health experience. Otherwise code `0`.

Personal experiences count. Metaphorical uses should not count: for example,
"a concert feels like a drug" is not health discussion merely because it contains
the word "drug."

### `science_related`

Code `1` when a turn discusses scientific research, evidence, studies,
experiments, scientific theories or explanations, scientific methods, or
scientific institutions. Otherwise code `0`.

The labels are independent. A medical-study discussion can receive `(1, 1)`, a
personal illness story `(1, 0)`, a physics discussion `(0, 1)`, and music history
`(0, 0)`.

## Automated pilot screen

`code/03_classify_content.py` applies the visible terms and prefixes in
`config/content_classification.json`. A short response of at most 12 words can
inherit a directly matched label from the immediately previous or next turn when
the gap is no more than 15 seconds. Propagation occurs once, preventing labels
from spreading indefinitely through short replies.

The output records every matched rule. All positive turns and a deterministic
10% sample of negative turns receive `needs_review = 1`. This supports checking
both false positives and missed content.

## Interpretation

Automated outputs have status `provisional_not_human_validated`. Keyword matches
are a transparent screening baseline, not final research measurements. Before
reporting results, manually review the flagged rows, record corrections in a
separate adjudicated dataset, and estimate agreement on an independently coded
sample.

The model-assisted implementation in `code/04_classify_content_openai_batch.py`
uses the same two independent concepts at the standardized window level and
applies the more explicit prompt in `config/openai_content_classification.json`.
Its output remains provisional and must be evaluated against human coding; it is
not ground truth merely because a language model generated it.
