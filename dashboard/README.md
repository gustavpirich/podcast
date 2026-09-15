# Classification Inspector

Local dashboard for inspecting the completed broad-fringe pilot and its health
product, intervention, and behavior classification: 20 episodes, 4,124 windows,
8,504 claim instances, and 7,182 deduplicated statement units.
The generated browser dataset contains transcript text and is intentionally
excluded from Git.

From the repository root, generate the dashboard data from frozen broad-fringe
run `5a165612d6459da0` and health-object run `e5112711aca03600`:

```bash
python3 code/07_prepare_classification_dashboard_data.py
```

Then run the dashboard locally:

```bash
cd dashboard
npm run dev -- --host 127.0.0.1
```

The interface supports full-text search, show and episode filtering,
health/science and fringe-status filtering, review flags, episode comparisons,
filtered CSV export, and claim-level inspection. **Products & behaviors** uses
deduplicated statements as its denominator. It shows category counts and filters
for primary/secondary object, claim focus, product maturity, and extraction
quality. Selecting a statement opens its exact quotation, 256-word context,
existing scientific assessment, and new descriptive labels. **Overview** compares broad
presence with assertion/tentative advancement, displays nonexclusive category
rates, and ranks episodes. Change the denominator between all selected windows
and selected health/science-positive windows. All charts follow the current
filters. For a single episode, Overview also shows clickable transcript tiles.
Scientific position, exaggeration, and stance filters must match the same claim;
the window view retains its entire context and the review view shows only
matching claims. Screen-negative windows remain separate from not-fringe ones.

The **Review** view rotates
through uncertain, fringe, and non-fringe claims. Human decisions and notes are
stored in the browser only and can be exported as a CSV. The available human
codes are `fringe`, `uncertain`, `not_fringe`, and `not_claim`.
These decisions do not alter model totals. Broad review storage is namespaced by
the source CSV hash; earlier narrow-run reviews remain untouched in their old
browser storage key. Exports retain source hashes for traceability.

The site runs at http://localhost:3000 on this computer. It has not been uploaded
to a hosting provider. No new model requests are made by this dashboard.
