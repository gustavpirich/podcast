# Podcast configuration

`jre_latest_40_new_30_2026-09-16.json` freezes the exact complement of
`jre_latest_40_2026-09-15.json` after excluding the ten episodes in
`jre_starter_sample.json`. It is the downstream classification sample for the
30 newly transcribed episodes and does not alter either parent sample.

`podcasts.json` contains facts that apply to a whole show: its official RSS
feed, accepted YouTube author name, and regular host. Keeping these facts out of
the acquisition code lets the same script work for another podcast.

Adding a show here does not guarantee that its episode titles can be matched
automatically. Numbered shows such as the Joe Rogan Experience are the easiest
case. Unnumbered or inconsistent titles need a conservative show-specific rule
and manual validation before bulk acquisition.
