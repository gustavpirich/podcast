# Project instructions

## Purpose

This is a reproducible observational research project on podcast transcripts.
The researcher, not an agent, is responsible for the research question, claims,
citations, coding decisions, and reported results.

## Scope boundary

All project work must stay inside this `podcast_observational` repository. Do
not inspect, create, edit, move, delete, or run project commands against its
parent directory or any sibling project unless the researcher explicitly asks.
When a requested input is outside this repository, ask before copying or linking
it here. Temporary files created for this project must also remain inside this
repository or the system temporary directory.

## Project structure

- `data/raw/`: original inputs. Acquisition scripts may create new, uniquely
  identified files here; after creation they are read only and untracked by Git.
- `data/derived/`: reproducibly generated analytic datasets. Untracked by Git.
- `code/`: the authoritative scripts and notebooks. Number scripts when an
  execution order is needed, for example `01_build_dataset.py`.
- `output/`: generated tables, figures, and reports. Untracked by Git.
- `paper/`: manuscript sources and bibliography.
- `notes/`: the protocol, research decisions, and an AI-use log.

No raw data, generated output, or ad hoc analysis files belong in the repository
root.

## Working rules

1. Inspect `README.md`, `notes/PLAN.md`, and `git status` before making changes.
2. Treat accepted files in `data/raw/` as immutable. A numbered acquisition
   script may create a new episode directory and new raw files, but it must
   refuse to overwrite existing raw files. All transformation and analysis
   scripts may only read from `data/raw/`.
3. Make every derived file traceable to a script, its inputs, and relevant choices.
4. Do not silently make substantive choices: sampling, inclusion rules, units,
   measurement definitions, model specifications, and interpretation require a
   documented researcher decision.
5. Keep source URLs, access dates, transcript method, and coding evidence with
   the project. Do not invent citations or evidence.
6. Do not expose credentials, restricted transcripts, or participant-sensitive
   data to external services without explicit approval.
7. Work in small, verifiable increments. State the expected artifact and checks
   before running a substantial task.
8. Inspect `git diff` after changes. Commit only when the researcher understands
   the result and explicitly requests a commit.
9. Before writing or changing AssemblyAI code, fetch
   `https://www.assemblyai.com/docs/agent-instructions.md` and
   `https://www.assemblyai.com/docs/llms.txt`; parameter names and model behavior
   may have changed.

## Verification checklist

For each pipeline step, check:

- inputs and outputs are in the correct folders;
- row/episode/segment counts are plausible and recorded;
- identifiers remain unique and merge keys are valid;
- a small sample of transcript text and coded labels is inspected manually;
- the script can run again without editing raw inputs.
