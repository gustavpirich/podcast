# Fringe-claim validation: human coding guide (v1)

Status: draft for researcher review, 2026-10-01. It applies the fringe
definition in `notes/DESCRIPTIVES_PLAN.md`.

## Purpose

Estimate how often model-coded fringe claims in the 20-episode pilot are real
fringe claims (precision), overall and by show × speaker role × tier. Only
model-positive claims are sampled, so this measures false positives, not missed
fringe claims.

## Sample

`code/16_draw_fringe_validation_sample.py` draws 150 claims from the 1,130
model-coded advanced fringe claims. There are 12 strata: show × host/guest ×
tier A/B/C. Each stratum gets an equal share (12–14 claims), capped at its size.
Nine claims by unidentified speakers are excluded. `answer_key.csv` holds the
stratum weights for population estimates.

The coding sheet is **blind**: it shows the claim, speaker and transcript
context, but not the model's labels or reasons. Do not open `answer_key.csv`
until coding is complete.

## Workflow

1. Copy `data/derived/descriptives/fringe_supply_pilot_20_e5112711aca03600/validation_v1/coding_sheet.csv`
   to `data/raw/human_coding/fringe_validation_v1_coded.csv` and code that copy.
   (The derived sheet can be regenerated; the coded copy is an original input.)
2. Read the context; listen to the audio at `timestamp` if the transcript is unclear.
3. Fill the five coding columns. Record any sources consulted in `h_note`.

## Coding columns

| Column | Values | Rule |
| --- | --- | --- |
| `coder` | initials | Who coded the row. |
| `h_empirical_general` | `yes`, `no` | `yes` if the claim is testable in principle **and** generalizes beyond the speaker's own experience. `no` for opinions, values, politics, jokes, hypotheticals, personal anecdotes and offhand hyperbole. |
| `h_fringe_tier` | `A`, `B`, `C`, `not_fringe`, `uncertain` | Position relative to the relevant scientific consensus at the episode date. A = emerging/minority with some credible evidence; B = speculative/alternative with little or no credible evidence; C = contradicts well-established evidence; `not_fringe` = mainstream or a legitimately open question. Use `uncertain` only when you cannot judge after a brief check. Exaggeration of a mainstream claim on its own is `not_fringe`. |
| `h_advanced` | `yes`, `no` | `yes` if the speaker asserts the claim or entertains it as plausible. `no` if it is only reported, rejected, mocked or posed as a neutral question. |
| `h_own_view` | `own`, `restating`, `question` | `own` = the speaker's own position; `restating` = summarizing or paraphrasing the other speaker; `question` = asking whether it is true. |
| `h_note` | free text | Reasoning for hard cases and any sources consulted. |

## Derived outcomes (computed later, by script)

- **Confirmed fringe claim:** `h_empirical_general = yes`, `h_fringe_tier` in
  {A, B, C} and `h_advanced = yes`.
- **Precision:** the weighted share of sampled claims that are confirmed, by
  stratum and overall.
- **Tier agreement:** human tier versus model tier among confirmed claims.
- **Host restating rate:** the share of host claims coded `restating`, which
  corrects the host/guest supply split.

## Open researcher choices

- Single coder or double coding of a subset (for example, 30 items) to report
  inter-coder reliability.
- Which consensus sources count as authoritative for each domain.
