# Provisional health-claim veracity classification

## Request and status

On 2026-09-16 the researcher requested an additional OpenAI-based statement
classification distinguishing supported, exaggerated, unsupported, contradicted
and dangerous health claims, using the existing pipeline. The requested
dimensions are researcher-selected. The operational definitions below are an
agent-proposed codebook for review, not a validated measurement instrument.
Researcher adoption, evidence-search standards and adjudication remain pending.

The proposed implementation separates veracity from danger because harm can
coexist with any evidence category. The researcher was asked about that choice;
the separate-field implementation is a disclosed proposal unless confirmed.
No single hierarchy converts dangerousness into a truth judgment.

## Coding definitions

| Veracity | Operational rule |
| --- | --- |
| `supported` | Established reliable evidence supports the specific proposition with its stated population, magnitude, outcome and certainty. Plausibility is insufficient. |
| `exaggerated` | A supported core is overstated in magnitude, certainty, causality, generalizability or clinical relevance. Identify both the core and the overreach. |
| `unsupported` | Adequate scientific support is confidently identified as lacking. This is not disproof; inability to recall evidence and an uncited transcript are insufficient grounds. |
| `contradicted` | Reliable evidence directly conflicts with the central proposition. Controversy or absence of evidence is insufficient. |
| `uncertain` | Model knowledge, evidence or context cannot resolve the claim, including compound claims with materially different statuses. |
| `not_assessable` | No recoverable checkable proposition, or the extracted quotation cannot be matched to its source. |
| `not_applicable` | No substantive health claim. |

The separate `danger_label` is `dangerous`, `no_clear_danger`, `uncertain`,
`not_assessable` or `not_applicable`. Dangerous requires a concrete credible
pathway to serious harm from acting on the health message, with the action,
affected context and harm stated. Merely discussing a hazardous exposure,
describing side effects, or rebutting dangerous advice does not qualify.
`no_clear_danger` is not a safety guarantee. Scientific accuracy and dangerousness
do not identify the speaker's intent or establish misinformation prevalence.

If strong evidence refutes the central proposition, contradicted takes priority;
if there is a supported core that is materially overstated, use exaggerated;
otherwise use unsupported only for an identifiable evidence gap, supported
when warranted, and uncertain when unresolved. Modality, negation, dose and
qualifications must remain part of the proposition being judged.

## Evidence and scope

This follows the existing pipeline's **model-knowledge-only provisional pass**.
It does not search, retrieve or verify scientific literature. The model must not
invent citations or evidence access dates. Each output includes a three-sentence
veracity explanation, a separate danger explanation, and `evidence_review_needed`.
Human evidence URLs, access dates, decisions and notes remain separate blank
fields. A supported label is an unverified model judgment until reviewed.

The assessment frame is evidence known to the model at the recorded assessment
date, not evidence reconstructed at the episode publication date. The date is
not a claimed knowledge cutoff or a literature access date. Historical validity,
source hierarchies, retrieval procedures, acceptable uncertainty and adjudication
require researcher decisions before substantive reporting.

All 7,182 existing Stage-10 statement units enter the pilot augmentation;
all 8,504 original instances remain. No new episode or statement sampling is
introduced. The model assesses health applicability for each statement without
seeing previous fringe, exaggeration, object or truth labels. Non-health material
receives not_applicable; uncertain applicability is retained. This field applies
to individual statements and does not revise the Stage-04 topical window labels.
An unmatched quotation cannot receive a substantive veracity or danger label.

## Pipeline and artifacts

`code/12_classify_veracity.py` reuses the existing OpenAI SDK client, Batch
response parser, atomic writer and CSV serializer. It reads Stage-10 statement
units and instances, preserving all prior columns including human notes.
It uses the existing `gpt-5.6-luna` model with low reasoning effort and strict
structured outputs. At most three statements sharing a representative 256-word
window are included per request to limit response truncation. Exact existing
unit identifiers propagate one assessment to all linked claim instances.

```bash
conda run -n podcast_observational python code/12_classify_veracity.py prepare
conda run -n podcast_observational python code/12_classify_veracity.py submit --yes
conda run -n podcast_observational python code/12_classify_veracity.py status
conda run -n podcast_observational python code/12_classify_veracity.py collect
# If completed provider requests are missing, invalid or truncated:
conda run -n podcast_observational python code/12_classify_veracity.py repair --yes
conda run -n podcast_observational python code/12_classify_veracity.py collect
```

Use `--run-id` to address a frozen run explicitly and `--input` to select another
compatible Stage-10 output directory inside `data/derived/`. `prepare` freezes
byte-exact input CSVs, configuration, prompt, response schema and request JSONL
under `data/derived/classifications/veracity/<run_id>/`. The run identity covers
those inputs; the manifest also records source hashes, script hashes and the
assessment date. No raw data or existing classification output is edited.

Submission uploads transcript excerpts to OpenAI and incurs API charges as
requested by the researcher. Credentials come from the existing Conda environment
and are never stored in the run artifacts. Stored Batch IDs are reused.
The provider processes Batch jobs asynchronously; completion is not immediate.

Collection retains original provider output and diagnostics, validates strict
IDs, enumerations, scope combinations and complete coverage, and writes:

- `statement_units.csv`: original columns plus veracity/danger and provenance;
- `statement_instances.csv`: the same additional fields mapped to every instance;
- `veracity_summary.csv`: distinct unique-statement and overlapping-instance counts;
- `collection_summary.json`: counts, usage, hashes and provisional status.

Health percentages use all units classified as health, including uncertain and
not-assessable units; non-health and uncertain-scope totals are retained separately.
The primary descriptive denominator is unique statements. Counts of overlapping
instances are an audit view, not independent observations. No window-level truth
aggregation or episode prevalence estimand is introduced by this augmentation.

Missing, duplicate or invalid responses cannot silently become negative labels.
Collection with unresolved requests saves diagnostics but produces no final CSV.
Retries select unresolved requests, retain failed attempts, and record additional
token usage. Collected files containing human edits cannot be overwritten.

API implementation reference accessed 2026-09-16:
[OpenAI Batch guide](https://developers.openai.com/api/docs/guides/batch).

## Prepared pilot and submission status

Run `03b4d55da8851b87`, prepared on 2026-09-16, contains 7,182 statement units,
8,504 claim instances and 3,114 requests. Repeated preparation produced the same
run identifier and unchanged frozen inputs. All 99 local tests passed.

Initially, no Batch was submitted and no veracity results were generated. The initial
network attempt failed at connection establishment. Automatic approval review
then rejected the network escalation because it requires explicit researcher
confirmation that this transcript-derived payload may be uploaded to OpenAI.
The prepared excerpts and codebook can be inspected locally before that decision.
Submission would disclose the quotations and representative transcript windows
to OpenAI and incur API charges; no credentials are included in the payload.

## Validation before research use

### Smaller pilot requested on 2026-09-16

The researcher requested testing a smaller subset before the full run. Run
`663faa29292cfe62` contains 20 health/both statement units (ten per show), all
24 linked claim instances and 20 requests. `--pilot-size 20` selects units by
SHA-256 order with seed prefix `veracity-pilot-v1:`, round-robin across shows.
The frozen `pilot_selection.json` records exact IDs and full-source hashes.
This is a technical smoke test, not a representative validation sample.

Batch `batch_6aaa572422a8819081b31515a530b921` was submitted under that smaller-pilot
instruction. The full run was subsequently authorized and submitted as recorded below. Existing transcription,
health/science, fringe and object classification stages are not executed.

The official short-context GPT-5.6 Luna Batch rates accessed on 2026-09-16 are
$0.10 per million input tokens and $0.60 per million output tokens, frozen in
`config/openai_veracity_pricing_2026-09-16.json`. Run `estimate --run-id ...`
to reproduce `cost_estimate.json`. Before observed usage, scenarios assume
serialized input bytes divided by four and 1,000–3,000 output tokens per request:
pilot $0.016–$0.040; full run $2.56–$6.30. A conservative planning calculation
uses one input token per serialized byte and every configured output token:
pilot $0.101; full run $15.845. These are not billing guarantees; they exclude
retries, taxes and regional uplifts. Actual output includes reasoning tokens.

### Full-run authorization and submission

After reviewing these cost estimates, the researcher instructed running the
full classification on 2026-09-16. Run `03b4d55da8851b87` was submitted as Batch
`batch_6aaa58a741a88190a222097da306cf70` with 3,114 requests covering all 7,182
statements and 8,504 linked instances. Its initial status was `validating`.
All frozen input hashes were verified immediately after submission. The pilot
was still processing, so no pilot-based validity conclusion or measured cost
was available before the full submission. Both runs remain provisional and
require collection and human evidence review.

The tests check statement-instance integrity, scope/danger consistency, abstention
for unmatched quotes, complete and order-independent provider output, preservation
of prior labels and human notes, and repeatable collection. This checks software
behavior; it does not establish classification validity. A researcher-designed
evidence review and validation sample remain necessary before reporting findings.
