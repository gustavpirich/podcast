# OpenAI Batch classification workflow

## What this stage does

This is a model-assisted second implementation of the health/science codebook.
It does not replace the dictionary baseline or human validation. It sends one
standardized transcript window per OpenAI request and asks for two independent
binary labels plus short rationales.

The configuration in `config/openai_content_classification.json` is part of the
measurement protocol. Changing a definition, rule, model, window size, or stride
creates a different deterministic run ID when `prepare` is run again.

## Model decision

On 2026-09-10, the researcher selected `gpt-5.6-luna` with `low` reasoning
effort for the pilot. OpenAI describes Luna as a cost-sensitive, high-volume
model and documents support for both Batch and Structured Outputs. This makes it
a practical screening model, but not a source of ground truth. Its classifications
must be compared with a human-coded evaluation sample before substantive use.

The model catalog currently exposes `gpt-5.6-luna` without a separate dated
snapshot identifier. The pipeline therefore records the requested model, the
model reported in every response, the full prompt configuration, and file hashes.
Because the alias may change over time, exact behavioral reproduction cannot be
guaranteed unless OpenAI later provides a dated snapshot.

## Windowing decision

On 2026-09-10, the researcher selected a method reported in a paper: divide each
eligible episode into complete 256-word windows with a stride of 128 words and
retain only episodes containing at least 768 words. Five complete windows begin
at word indices 0, 128, 256, 384, and 512 in a 768-word transcript. The paper's
full bibliographic citation still needs to be added to the project.

For this implementation, a word is one timestamped word object in the AssemblyAI
transcript. Punctuation attached to a word does not count separately. The first
window covers zero-based word indices `[0, 256)`, the second `[128, 384)`, and so
on. Partial trailing windows are excluded. Each request contains exactly one
window; within it, consecutive words are grouped by diarized speaker so speaker
information remains visible without changing the word boundaries.

The overlap reduces sensitivity to an arbitrary boundary, but it means adjacent
observations are statistically dependent and much of their text is duplicated.
Therefore, the reported share is a share of classified windows—not a direct
share of unique words, minutes, claims, or a particular speaker's speech.

## Four-stage workflow

Run from the repository root after activating `podcast_observational`:

```bash
python code/04_classify_content_openai_batch.py prepare
python code/04_classify_content_openai_batch.py submit --yes
python code/04_classify_content_openai_batch.py status
python code/04_classify_content_openai_batch.py collect
```

1. `prepare` creates and validates a local JSONL request file. It is free and
   sends nothing outside the computer.
2. `submit --yes` uploads the transcript excerpts and creates a billable batch.
   It refuses to submit the same run twice.
3. `status` checks whether the asynchronous job is still validating, running,
   finalizing, or complete.
4. `collect` downloads results, joins them using `custom_id`, verifies complete
   coverage of every window, and writes the analytic CSV and summary JSON.

The API key must be available as `OPENAI_API_KEY` in the terminal. It is never
placed in the JSONL, manifest, output, or repository.

For the frozen ten-episode *Diary of a CEO* starter sample, the same four stages
are orchestrated without changing the single-episode measurement code:

```bash
python code/04_classify_content_openai_batch_sample.py prepare
python code/04_classify_content_openai_batch_sample.py submit --yes
python code/04_classify_content_openai_batch_sample.py status
python code/04_classify_content_openai_batch_sample.py collect
```

There is one separately resumable Batch job per episode. After all ten results
are collected and validated, the runner combines them under
`data/derived/classifications/openai_batch_samples/<sample-id>/<run-id>/` while
retaining `episode_id` and `window_id` as merge keys.

For a key that should exist only in the current terminal session:

```bash
read -s -p "OpenAI API key: " OPENAI_API_KEY
echo
export OPENAI_API_KEY
```

The OpenAI API is billed separately from a ChatGPT subscription. Confirm that
the API project has billing and model access before `submit --yes`.

## Outputs and provenance

Each run lives under:

```text
data/derived/classifications/openai_batch/<show>/<episode>/<run-id>/
```

The directory preserves the exact request JSONL, input hashes, prompt/model
configuration, remote batch identifiers, raw returned JSONL, token usage, and
the final window-level CSV. These generated files remain excluded from Git.

## Interpretation

The final status is `provisional_model_assisted_not_human_validated`. All model
positives and a deterministic 10% sample of model negatives are marked for
review. Before reporting prevalence, create a human-coded evaluation sample and
report false-positive/false-negative performance or inter-coder agreement.
