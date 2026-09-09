# Podcast configuration

`podcasts.json` contains facts that apply to a whole show: its official RSS
feed, accepted YouTube author name, and regular host. Keeping these facts out of
the acquisition code lets the same script work for another podcast.

Adding a show here does not guarantee that its episode titles can be matched
automatically. Numbered shows such as the Joe Rogan Experience are the easiest
case. Unnumbered or inconsistent titles need a conservative show-specific rule
and manual validation before bulk acquisition.
