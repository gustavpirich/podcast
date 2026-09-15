# Health product, intervention, and behavior classification

## Purpose

This classification describes what each previously extracted statement is about.
It was requested on 2026-09-14 to distinguish products and interventions such as
vaccines, new drugs, peptides, supplements, psychoactive substances, and health
behaviors. It does not replace or modify the existing health/science, scientific
position, exaggeration, stance, or broad-fringe labels.

The input is frozen broad-fringe run `5a165612d6459da0`: 8,504 claim instances
from 4,124 overlapping 256-word windows in 20 episodes. Because adjacent windows
overlap by 128 words, exact repetitions are linked to one statement unit before
classification. The primary descriptive denominator is unique statement units;
claim-instance totals remain an audit view.

## Classification dimensions

Each statement unit receives one primary object and up to two secondary objects:

- vaccines and immunization;
- pharmaceuticals and biologics;
- peptides and hormones;
- supplements and nutraceuticals;
- psychoactive substances;
- medical procedures and devices;
- diet and nutrition;
- exercise and physical activity;
- sleep and recovery;
- mental and behavioral interventions;
- environmental and lifestyle exposures;
- healthcare and public health;
- disease or condition without a central intervention;
- non-health science;
- other health; or
- unclear.

The most specific product category is primary. For example, a vaccine is not
primarily coded as a generic pharmaceutical, and a peptide product is primarily
peptides/hormones. A claim connecting sunlight to testosterone can use an
environmental exposure as its primary object and hormones as a secondary object.

`claim_focus` records the main aspect of the object: efficacy/benefit,
risk/safety, mechanism, use/dose/access, recommendation, regulation/policy,
prevalence/adoption, diagnosis/detection, general description, other, or unclear.

For therapeutic products and medical technologies, `product_maturity` records
established/marketed, new/emerging, investigational/experimental, off-label or
repurposed, unregulated/nonmedical, or uncertain. It is `not_applicable` for
ordinary behaviors, endogenous physiology, diseases, and general science. This
is a provisional contextual label, not a verified regulatory determination.

`extraction_quality` is retained as a quality-control field: atomic checkable,
compound checkable, not checkable, or unclear fragment. Nonclaims and unclear
fragments receive the conservative object and focus `unclear` and cannot be used
as substantive product-category observations without human correction.

## Deduplication

For source-aligned quotations, the script recovers the quotation's global word
span from its 256-word window. Records with the same episode, word span, and
normalized text form one statement unit. It selects the window with the greatest
minimum left/right context; ties use the earlier window. Unmatched quotations or
quotes occurring more than once in a window remain singleton unresolved units.
All original claim records retain a mapping to exactly one statement unit.

In the pilot, this deterministic rule maps 8,504 claim instances to 7,182 units:
1,322 are linked repetitions, 6,799 units have recovered spans, and 383 units
remain unresolved singletons (373 unmatched quotations and ten ambiguous local
locations).

## Reproducible workflow

The machine-readable definitions are in
`config/health_object_classification.json`. `code/10_classify_health_objects.py`
freezes the input CSV, statement units, instance mapping, prompt, response schema,
and Batch request file in a content-addressed run.

```bash
conda run -n podcast_observational python code/10_classify_health_objects.py prepare
conda run -n podcast_observational python code/10_classify_health_objects.py submit --yes
conda run -n podcast_observational python code/10_classify_health_objects.py status
conda run -n podcast_observational python code/10_classify_health_objects.py collect
```

Collection creates one row per unique statement, one row per original claim
instance, an explicit unit-instance mapping, and summaries for primary object,
claim focus, product maturity, extraction quality, and show. Every output retains
the source CSV hash and remains provisional pending stratified human review.
Both statement CSVs include blank human-correction columns for the primary and
secondary objects, claim focus, product maturity, extraction quality, and a
review note. Human entries remain separate from the model fields.

## Completed pilot run

Run `e5112711aca03600` completed on 2026-09-15. Its primary Batch
`batch_6aa8496244d08190b6dd22a6bb25223d` classified 2,068 snippets. Thirteen
truncated responses were retried in Batch
`batch_6aa8579acf5c8190b48d6abd597f911c`; the remaining truncated seven-statement
response was retried as seven individual requests in Batch
`batch_6aa8603f7de48190877cd3fd56657136`.

The collected files are under
`data/derived/classifications/health_objects/e5112711aca03600/`. They contain
7,182 unique statements and 8,504 original claim instances. All 8,504 source
claim identifiers are present exactly once, every instance maps to one unit,
every unit has one representative and one primary object, and all prior claim
labels and source text are byte-for-byte unchanged.

The largest primary categories are non-health science (2,813 units), disease or
condition (793), unclear (605), mental or behavioral interventions (563), and
exercise or physical activity (477). Vaccines and immunization account for 39
units; pharmaceuticals and biologics 198; peptides and hormones 192; supplements
and nutraceuticals 126; and psychoactive substances 189. These frequencies are
model-assisted descriptive results. They have not yet been validated as research
estimates. In particular, the 605 unclear units and 388 unclear fragments should
be reviewed before substantive aggregation.

The collector repaired 36 malformed statement identifiers and six malformed
snippet identifiers using unique near-match recovery, removed a duplicated
primary label from two secondary-object lists, and retained 47 prompt-rule
deviations with explicit flags. It did not infer or alter substantive category
labels during those repairs.
