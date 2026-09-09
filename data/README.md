# Data layout and provenance

`data/raw/` holds original inputs: downloaded transcripts, episode metadata,
source exports, and any restricted material. It is ignored by Git. Preserve the
original filename and record the source URL, access date, transcript provider or
method, language, and known limitations in a source log.

`data/derived/` holds files created by code: cleaned segments, episode-level
measures, coding tables, and analysis-ready datasets. It is also ignored by Git
because it should be rebuildable. Each derived file should identify the script
and input version that created it.

Suggested raw layout:

```text
data/raw/
├── source_log.csv
├── episodes.csv
└── transcripts/
    └── <show_name>/
        └── <youtube_video_id>/
            ├── <youtube_video_id>.m4a
            └── rss_metadata.json
```

Despite the directory name `transcripts`, each episode directory initially
contains its source audio and RSS metadata. Transcript files will be added there
only when they are source artifacts; cleaned or diarized transcripts belong in
`data/derived/` because they can be reproduced from the audio.

Suggested minimum fields:

- Episode metadata: `episode_id`, `podcast_name`, `episode_title`,
  `published_at`, `source_url`, `accessed_at`, `transcript_method`, `language`.
- Transcript segment: `episode_id`, `segment_id`, `start_seconds`,
  `end_seconds`, `speaker`, `text`.
- Human coding: `episode_id`, `segment_id`, `coder_id`, `codebook_version`,
  `label`, `evidence_url`, `coded_at`.

These are starting conventions, not a settled codebook. Define and version the
actual coding rules in `notes/` before coding at scale. If your data-use agreement
requires it, make `data/raw/` read-only in the operating system after ingestion.
