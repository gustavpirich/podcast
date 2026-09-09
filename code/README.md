# Analysis code

Put reproducible scripts and notebooks here. A numbered workflow is easy to
inspect, for example:

1. `01_ingest_transcripts.py` reads raw source files and writes normalized data.
2. `02_validate_data.py` checks identifiers, timestamps, and coverage.
3. `03_build_measures.py` creates documented measures.
4. `04_analysis.py` creates tables and figures.

Acquisition scripts may create new, uniquely identified files in `data/raw/`
but must never overwrite them. Transformation and analysis scripts read
`data/raw/` and write only to `data/derived/` or `output/`. Keep substantive
choices in configuration or notes rather than hidden in code.

## Current acquisition pilot

`01_download.py` starts from one YouTube URL, checks its channel, matches it to
the publisher's official RSS feed, and downloads the best available YouTube M4A.
The RSS feed—not the YouTube description—is the authoritative episode metadata
source. Audio and an immutable metadata record are stored under
`data/raw/transcripts/<show>/<youtube_video_id>/` and ignored by Git.

From the repository root:

```bash
python code/01_download.py \
  "https://www.youtube.com/watch?v=BAhcDwMGKYU" \
  --show jre
```

The stable YouTube video ID is used for the directory and filename because an
episode title can change. Existing raw audio and metadata are never overwritten.
