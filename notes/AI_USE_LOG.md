# AI-use log

Record material use of AI that affects research design, code, analysis, or prose.
This is a short accountability log, not a substitute for reviewing the work.

| Date | Task | Tool/model | Inputs or access granted | Output used | Human review / decision |
| --- | --- | --- | --- | --- | --- |
| YYYY-MM-DD |  |  |  |  |  |
| 2026-09-09 | Build and test the one-episode acquisition pilot | OpenAI Codex | Researcher-selected YouTube URL; public YouTube oEmbed metadata; official podcast RSS feed; local repository | Acquisition script, podcast configuration, protocol note, tests, staged manifest and audio | Episode match and code review pending researcher confirmation |
| 2026-09-09 | Revise the pilot to acquire YouTube M4A and use RSS for documentation | OpenAI Codex | Researcher-provided `yt_dlp` example; selected YouTube URL; official podcast RSS feed; local repository | Restored downloader, raw M4A, RSS metadata record, environment specification, tests, and documentation; the separate acquisition note was removed as requested | Researcher requested the media-source and storage changes; speaker diarization strategy remains to be reviewed |
| 2026-09-10 | Build pilot health/science content screen | OpenAI Codex | Researcher-approved two-label scope; local diarized transcript | Dictionary baseline, visible configuration, codebook, derived turn labels, and tests | Definitions, matches, and validation design require researcher review before analysis |
| 2026-09-10 | Prepare OpenAI Batch model-assisted classifier | OpenAI Codex | Researcher-approved use of OpenAI Batch API; local diarized transcript used only to prepare an unsubmitted JSONL file | Four-stage Batch workflow, structured-output prompt, provenance manifest, tests, and documentation | Researcher selected GPT-5.6 Luna with low reasoning effort and the paper's 256-word windows, 128-word stride, and 768-word episode minimum; no transcript uploaded or API cost incurred |
| 2026-09-10 | Build conditional health/science passage-content classifier | OpenAI Codex | Researcher-approved topic/content dimensions; collected stage-04 outputs and local word-timestamped transcripts | Stage-05 passage merger, OpenAI Batch workflow, seven-topic codebook, validation tests, and documentation | Researcher must review category definitions and validate model labels before analysis; no transcript uploaded and no API cost incurred during implementation |
