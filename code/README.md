# Analysis code

Put reproducible scripts and notebooks here. A numbered workflow is easy to
inspect, for example:

1. `01_ingest_transcripts.py` reads raw source files and writes normalized data.
2. `02_validate_data.py` checks identifiers, timestamps, and coverage.
3. `03_build_measures.py` creates documented measures.
4. `04_analysis.py` creates tables and figures.

Scripts must read `data/raw/` and write only to `data/derived/` or `output/`.
Keep substantive choices in configuration or notes rather than hidden in code.
