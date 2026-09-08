# Podcast observational analysis

This repository is the reproducible home for an observational analysis of podcast
transcripts, initially focused on systematically documenting health-related claims
and misinformation. It is a research workspace, not evidence that any particular
podcast or claim is inaccurate.

## Start here

1. Read [notes/PLAN.md](notes/PLAN.md). It separates the current setup from
   decisions that need your substantive judgment.
2. Read [data/README.md](data/README.md) before adding transcripts.
3. Put original, restricted, or re-downloadable inputs in `data/raw/`. They are
   ignored by Git and should be treated as read-only after ingestion.
4. Put every transformation in `code/`; write its results only to
   `data/derived/` or `output/`.
5. Check `git status` and inspect `git diff` before each commit.

## Project map

```text
podcast_observational/
├── AGENTS.md       # standing conventions for people and coding agents
├── README.md       # project entry point
├── .gitignore      # keeps raw data, secrets, and generated artifacts out of Git
├── data/
│   ├── raw/        # immutable source transcripts and source metadata (not tracked)
│   └── derived/    # reproducibly generated analytic data (not tracked)
├── code/           # scripts/notebooks that turn inputs into outputs
├── output/         # generated tables, figures, and reports (not tracked)
├── paper/          # manuscript, bibliography, and submission materials
└── notes/          # protocol, decisions, plans, and research log
```

The separation matters: raw data preserve provenance; code records transformations;
derived data and output can always be rebuilt. Do not place files such as
`analysis_final2.py`, downloaded transcripts, or generated figures in the
repository root.

## A safe first workflow

```bash
# See the repository state before and after a bounded change.
git status
git diff

# When a script exists, run it from the project root.
python code/01_build_dataset.py
```

Before the first real analysis, define in the plan: the sampling frame, unit of
analysis, inclusion/exclusion rules, transcript provenance, coding protocol,
handling of missingness, and the descriptive or causal estimand. An automated
label is not a substitute for validating claims against evidence.

## Reproducibility and security

- Never commit raw transcripts, credentials, API keys, or restricted data.
- Do not edit files in `data/raw/`; produce a new file in `data/derived/` instead.
- Record data sources, access dates, and any manual coding decisions in `notes/`.
- Use small, inspectable changes and commit only after reviewing the diff.
- Keep a short record of material AI use when analysis or writing begins.

The detailed operating conventions are in [AGENTS.md](AGENTS.md).
