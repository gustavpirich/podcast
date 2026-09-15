#!/usr/bin/env python3
"""Summarize and plot legacy or broad-fringe results without conflating definitions.

Outputs PNG/SVG figures, episode/show CSVs and a source-hashed Markdown report.
Run with the project .venv, which contains Matplotlib. Classification uses the
podcast_observational Conda environment independently of plotting dependencies.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/derived/classifications/openai_passage_content/pilot_20_2026-09-12/pilot_20_window_claim_classification.csv"
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp/matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "tmp/plot_cache"))

SHOWS = {"jre": "Joe Rogan Experience", "doac": "The Diary of a CEO"}
ORDER = ["fringe", "uncertain", "not_fringe", "not_assessable", "not_screened"]
COLORS = {"fringe": "#B64B3A", "uncertain": "#D9A441", "not_fringe": "#307E80",
          "not_assessable": "#9BA8B0", "not_screened": "#E5E9EC"}
INK, MUTED, BG = "#172D3B", "#526572", "#FCFBF8"
CATEGORY_SPECS = [("emerging_non_mainstream", "Emerging / minority"),
                  ("alternative_speculative", "Alternative / speculative"),
                  ("contradicts_consensus", "Contradicts consensus"), ("exaggerated", "Exaggerated")]


def read_input(path):
    if not path.resolve().is_relative_to(ROOT / "data/derived"):
        raise ValueError("Input must be in this project's data/derived")
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("Empty classification file")
    broad = "broad_status" in rows[0]
    metadata = {}
    for show in SHOWS:
        sample = json.loads((ROOT / f"config/{show}_starter_sample.json").read_text())
        for e in sample["episodes"]:
            metadata[(show, e["youtube_id"])] = e
    seen, episode_rows = set(), defaultdict(list)
    for row in rows:
        key = (row["show"], row["episode_id"])
        sid = row["snippet_id"]
        if sid in seen:
            raise ValueError("Duplicate snippet ID")
        seen.add(sid)
        w = dict(row)
        w["window_id"] = int(row["window_id"])
        w["screen_positive"] = bool(int(row["health_related"] if broad else row["screen_health_related"]) or
                                     int(row["science_related"] if broad else row["screen_science_related"]))
        w["status"] = row["broad_status"] if broad else row["fringe_status"]
        if not w["screen_positive"]:
            if w["status"] not in {"not_screened", "not_assessable"}:
                raise ValueError("Screen-negative window contains a classified outcome")
            w["status"] = "not_screened"
        if w["status"] not in ORDER:
            raise ValueError("Invalid outcome")
        if int(row["word_end_index_exclusive"]) - int(row["word_start_index"]) != 256:
            raise ValueError("Incorrect window size")
        if int(row["word_start_index"]) != w["window_id"] * 128:
            raise ValueError("Incorrect window stride")
        episode_rows[key].append(w)
    if set(episode_rows) != set(metadata):
        raise ValueError("Input does not cover every episode in the two frozen pilot samples")
    summaries = []
    for key, group in episode_rows.items():
        group.sort(key=lambda w: w["window_id"])
        if [w["window_id"] for w in group] != list(range(len(group))):
            raise ValueError("Incomplete episode window sequence")
        counts = Counter(w["status"] for w in group)
        n, screened = len(group), sum(w["screen_positive"] for w in group)
        flagged, uncertain = counts["fringe"], counts["uncertain"]
        advanced = sum(w.get("advanced_status") == "fringe" for w in group) if broad else ""
        e = metadata[key]
        summaries.append({"show": key[0], "episode_id": key[1], "guest": e["guest_name"],
            "published_date": e["published_date"], "episode_title": group[0]["episode_title"],
            "definition": "broad_fringe_v1" if broad else "legacy_narrow_fringe",
            "windows": n, "screen_positive_windows": screened,
            **{s + "_windows": counts[s] for s in ORDER},
            "flagged_pct_all_windows": 100 * flagged / n,
            "flagged_pct_screen_positive_windows": 100 * flagged / screened if screened else "",
            "uncertain_pct_all_windows": 100 * uncertain / n,
            "advanced_windows": advanced, "advanced_pct_all_windows": 100 * advanced / n if broad else "",
            "claim_instances_with_overlap": sum(int(w["claim_count"]) for w in group)})
        if sum(counts.values()) != n or counts["not_screened"] + screened != n:
            raise ValueError("Denominators do not reconcile")
    summaries.sort(key=lambda r: (r["show"], -r["flagged_pct_all_windows"]))
    return broad, summaries, episode_rows


def show_summary(episodes):
    output = []
    for show in SHOWS:
        es = [e for e in episodes if e["show"] == show]
        if not es:
            continue
        n = sum(e["windows"] for e in es)
        selected = sum(e["screen_positive_windows"] for e in es)
        flagged = sum(e["fringe_windows"] for e in es)
        output.append({"show": show, "episodes": len(es), "windows": n,
            "screen_positive_windows": selected, "fringe_windows": flagged,
            "uncertain_windows": sum(e["uncertain_windows"] for e in es),
            "pooled_flagged_pct_all_windows": 100 * flagged / n,
            "pooled_flagged_pct_screen_positive_windows": 100 * flagged / selected if selected else "",
            "mean_episode_flagged_pct": sum(e["flagged_pct_all_windows"] for e in es) / len(es),
            "definition": es[0]["definition"]})
        if isinstance(es[0].get("advanced_windows"), int):
            advanced = sum(e["advanced_windows"] for e in es)
            output[-1].update({"advanced_windows": advanced,
                               "pooled_advanced_pct_all_windows": 100 * advanced / n,
                               "pooled_advanced_pct_screen_positive_windows": 100 * advanced / selected if selected else ""})
    return output


def category_summary(groups):
    rows = []
    for show in SHOWS:
        windows = [w for (s, _), group in groups.items() if s == show for w in group]
        if not windows:
            continue
        for code, label in CATEGORY_SPECS:
            count = sum(any(c["quote_match_method"] != "unmatched" and
                            (c["exaggeration"] == "yes" if code == "exaggerated" else c["scientific_position"] == code)
                            for c in json.loads(w["claims_json"])) for w in windows)
            rows.append({"show": show, "category": code, "label": label,
                         "windows_with_category": count, "all_windows": len(windows),
                         "pct_all_windows": 100 * count / len(windows)})
    return rows


def write_csv(path, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def graphics(output, broad, episodes, shows, groups, categories):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.ticker import PercentFormatter

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
        "figure.facecolor": BG, "axes.facecolor": BG, "text.color": INK,
        "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": INK,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.spines.bottom": False,
        "svg.fonttype": "none"})
    tag = "BROAD DEFINITION · PROVISIONAL MODEL SCREEN" if broad else "LEGACY NARROW SCREEN · BROADER CLASSIFICATION PENDING"
    labels = {"fringe": "Broad claim present" if broad else "Flagged: narrow definition",
              "uncertain": "Uncertain", "not_fringe": "No flagged or uncertain claims",
              "not_assessable": "No assessable claim", "not_screened": "Screen-negative"}

    def title(fig, headline, subtitle):
        fig.text(.055, .97, tag, fontsize=10, weight="bold", color=COLORS["fringe"], va="top")
        fig.text(.055, .925, headline, fontsize=23, weight="bold", va="top")
        fig.text(.055, .873, subtitle, fontsize=11, color=MUTED, va="top")

    def save(fig, name):
        fig.savefig(output / f"{name}.png", dpi=180, facecolor=BG)
        fig.savefig(output / f"{name}.svg", facecolor=BG)
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13.4, 6.4))
    fig.subplots_adjust(left=.20, right=.96, top=.75, bottom=.24, wspace=.45)
    title(fig, "How often do flagged claims appear?", "Two denominators answer different questions • 10 selected episodes per show")
    specs = [("pooled_flagged_pct_all_windows", "All transcript windows", "windows"),
             ("pooled_flagged_pct_screen_positive_windows", "Health/science-positive windows", "screen_positive_windows")]
    for ax, (field, heading, denom) in zip(axes, specs):
        for i, row in enumerate(shows):
            rate = row[field]
            ax.barh(i, rate, height=.45, color=COLORS["fringe"], alpha=1 if i == 0 else .72)
            ax.text(rate + 1, i, f"{rate:.1f}%", va="center", weight="bold", fontsize=16)
            ax.text(.4, i + .34, f"{row['fringe_windows']:,} / {row[denom]:,} windows", color=MUTED, fontsize=10)
        ax.set_yticks(range(len(shows)), [SHOWS[r["show"]] for r in shows] if ax is axes[0] else [])
        ax.set_ylim(len(shows) - .35, -.65)
        ax.set_xlim(0, 100)
        ax.set_title(heading, loc="left", fontsize=13, weight="bold", pad=15)
        ax.xaxis.set_major_formatter(PercentFormatter(100))
        ax.xaxis.grid(True, color="#DEE3E6", linewidth=.6)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", length=0)
    fig.text(.055, .11, "Rates describe windows containing claims; they are not percentages of false statements or speaking time.", fontsize=10, color=MUTED)
    fig.text(.055, .065, "Pooled across each show's selected episodes. Adjacent 256-word windows overlap by 128 words.", fontsize=10, color=MUTED)
    save(fig, "01_show_comparison")

    fig, ax = plt.subplots(figsize=(14, 12))
    fig.subplots_adjust(left=.30, right=.87, top=.81, bottom=.15)
    title(fig, "Every episode, with uncertainty visible", "Share of all transcript windows • ranked within show by flagged share")
    y_labels = []
    for i, row in enumerate(episodes):
        left = 0
        for status in ORDER:
            width = 100 * row[status + "_windows"] / row["windows"]
            ax.barh(i, width, left=left, height=.64, color=COLORS[status])
            if status == "fringe" and width >= 7:
                ax.text(left + width / 2, i, f"{width:.1f}%", ha="center", va="center", color="white", fontsize=9, weight="bold")
            left += width
        ax.text(101.5, i, f"{row['flagged_pct_all_windows']:.1f}%  ({row['fringe_windows']}/{row['windows']})", va="center", fontsize=9)
        y_labels.append(f"{row['guest']}\n{row['show'].upper()} · {row['published_date']}")
    ax.set_yticks(range(len(episodes)), y_labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Percentage of episode windows", labelpad=10)
    ax.xaxis.set_major_formatter(PercentFormatter(100))
    ax.tick_params(axis="both", length=0)
    ax.text(101.5, -.9, "Flagged % (n/N)", fontsize=9, color=MUTED)
    fig.legend(handles=[Patch(facecolor=COLORS[s], label=labels[s]) for s in ORDER],
               loc="lower left", bbox_to_anchor=(.055, .048), ncol=3, frameon=False, fontsize=10)
    fig.text(.055, .028, "One window may contain several claims: flagged takes precedence, then uncertain. Uncertainty is not counted as fringe.", fontsize=9, color=MUTED)
    save(fig, "02_episode_profiles")

    fig, ax = plt.subplots(figsize=(14, 10))
    fig.subplots_adjust(left=.30, right=.95, top=.80, bottom=.17)
    title(fig, "Where flagged discussion occurs", "Each stripe is one classified window, positioned in transcript order • same episode order as above")
    for i, row in enumerate(episodes):
        group = groups[(row["show"], row["episode_id"])]
        for j, w in enumerate(group):
            ax.broken_barh([(100 * j / len(group), 100 / len(group))], (i - .33, .66),
                          facecolors=COLORS[w["status"]], edgecolors="none")
    ax.set_yticks(range(len(episodes)), [f"{r['show'].upper()} · {r['guest']}" for r in episodes], fontsize=9)
    ax.set_ylim(len(episodes) - .5, -.5)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Position in transcript window sequence (not elapsed minutes)", labelpad=10)
    ax.xaxis.set_major_formatter(PercentFormatter(100))
    ax.tick_params(axis="both", length=0)
    fig.legend(handles=[Patch(facecolor=COLORS[s], label=labels[s]) for s in ORDER],
               loc="lower left", bbox_to_anchor=(.055, .045), ncol=3, frameon=False, fontsize=10)
    fig.text(.055, .025, "Stripes show contextual windows, not the exact words making the claim. Overlapping windows can repeat the same spoken claim.", fontsize=9, color=MUTED)
    save(fig, "03_transcript_locations")

    if broad:
        fig, ax = plt.subplots(figsize=(12, 6))
        fig.subplots_adjust(left=.29, right=.94, top=.76, bottom=.20)
        title(fig, "Which kinds of broad fringe appear?", "Nonexclusive categories • percentage of all windows containing at least one matched claim")
        for si, show in enumerate(SHOWS):
            for i, (code, _) in enumerate(CATEGORY_SPECS):
                record = next(r for r in categories if r["show"] == show and r["category"] == code)
                value = record["pct_all_windows"]
                y = i + (si - .5) * .3
                ax.barh(y, value, height=.27, color=["#B64B3A", "#307E80"][si], label=SHOWS[show] if i == 0 else None)
                ax.text(value + .4, y, f"{value:.1f}%", va="center", fontsize=10)
        ax.set_yticks(range(len(CATEGORY_SPECS)), [label for _, label in CATEGORY_SPECS])
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(PercentFormatter(100))
        ax.margins(x=.20)
        fig.legend(*ax.get_legend_handles_labels(), frameon=False, loc="upper right",
                   bbox_to_anchor=(.94, .825), ncol=2, fontsize=10)
        fig.text(.055, .07, "Categories overlap and should not be summed. These are provisional judgments, not measured misinformation rates.", color=MUTED, fontsize=10)
        save(fig, "04_broad_categories")

        fig, ax = plt.subplots(figsize=(14, 11))
        fig.subplots_adjust(left=.30, right=.91, top=.80, bottom=.17)
        title(fig, "Mentioning a claim versus advancing it", "Percentage of all episode windows • advancing includes assertions and explicitly tentative hypotheses")
        for i, row in enumerate(episodes):
            present, advanced = row["flagged_pct_all_windows"], row["advanced_pct_all_windows"]
            ax.plot([advanced, present], [i, i], color="#B9C4CB", linewidth=3, zorder=1)
            ax.scatter(present, i, s=70, facecolor=BG, edgecolor=COLORS["fringe"], linewidth=1.8, zorder=3)
            ax.scatter(advanced, i, s=30, color=COLORS["not_fringe"], zorder=4)
            ax.text(max(present, advanced) + 1.6, i, f"{advanced:.1f}% / {present:.1f}%", va="center", fontsize=8)
        ax.set_yticks(range(len(episodes)), [f"{r['show'].upper()} · {r['guest']}" for r in episodes], fontsize=9)
        ax.invert_yaxis()
        ax.set_xlim(0, min(110, max(e["flagged_pct_all_windows"] for e in episodes) + 13))
        ax.xaxis.set_major_formatter(PercentFormatter(100))
        ax.xaxis.grid(True, color="#DEE3E6", linewidth=.6)
        ax.tick_params(axis="both", length=0)
        ax.set_xlabel("Percentage of episode windows", labelpad=10)
        from matplotlib.lines import Line2D
        fig.legend(handles=[Line2D([], [], marker="o", color="none", markerfacecolor=COLORS["not_fringe"], markeredgecolor=COLORS["not_fringe"], label="Asserted or tentatively advanced"),
                            Line2D([], [], marker="o", color="none", markerfacecolor=BG, markeredgecolor=COLORS["fringe"], label="Present, including reports and criticism")],
                   loc="lower left", bbox_to_anchor=(.055, .07), frameon=False, ncol=2)
        fig.text(.055, .035, "Figures beside each row show advanced % / present %. Reported, rejected, and unclear-stance claims do not establish advancement.", color=MUTED, fontsize=9)
        save(fig, "05_presence_and_advancement")


def report(output, path, broad, episodes, shows, manifest):
    total = sum(e["windows"] for e in episodes)
    flagged = sum(e["fringe_windows"] for e in episodes)
    uncertain = sum(e["uncertain_windows"] for e in episodes)
    definition = "Broad fringe classification" if broad else "Existing pilot: legacy narrow classification"
    text = [f"# {definition}", "",
        f"{len(episodes)} episodes; {total:,} windows. {flagged:,} windows ({100*flagged/total:.1f}%) flagged; "
        f"{uncertain:,} additional windows ({100*uncertain/total:.1f}%) have an uncertain leading status.", ""]
    if not broad:
        text += ["**These are the older narrow labels. The new broad-fringe rate has not been measured.** "
                 "Emerging ideas and exaggeration require fresh classification; uncertain windows cannot be relabeled as fringe.", ""]
    else:
        with (output / "category_summary.csv").open(newline="", encoding="utf-8") as handle:
            categories = list(csv.DictReader(handle))
        exaggerated = sum(int(r["windows_with_category"]) for r in categories if r["category"] == "exaggerated")
        collection = json.loads(path.with_name("collection_summary.json").read_text())
        text += [f"Exaggeration is the dominant component: {exaggerated:,} of the {flagged:,} flagged windows "
                 "contain a claim judged to overstate scientific evidence. Categories overlap. "
                 "Review the exaggeration decisions before treating these high screening rates as validated measurements.", "",
                 f"All {collection['requests_completed']:,} requested windows returned successfully, yielding "
                 f"{collection['claims_with_overlap']:,} claim instances across overlapping windows. "
                 f"{collection['unmatched_claims']:,} model quotations could not be aligned to the transcript; "
                 "their final claim flags are uncertain and they cannot establish positive category counts. "
                 f"{collection['long_explanations']} overlong explanations were preserved and flagged without changing their labels.", ""]
    text += ["![Show comparison](01_show_comparison.png)", "", "![Episode profiles](02_episode_profiles.png)", "",
             "![Locations in transcripts](03_transcript_locations.png)", ""]
    if broad:
        text += ["![Nonexclusive broad categories](04_broad_categories.png)", "",
                 "![Presence and advancement](05_presence_and_advancement.png)", ""]
    text += ["## Show summaries", "", "| Show | Flagged / all windows | Flagged / health-science windows | Mean episode percentage |",
             "| --- | ---: | ---: | ---: |"]
    for r in shows:
        text += [f"| {SHOWS[r['show']]} | {r['fringe_windows']}/{r['windows']} ({r['pooled_flagged_pct_all_windows']:.1f}%) | "
                 f"{r['fringe_windows']}/{r['screen_positive_windows']} ({r['pooled_flagged_pct_screen_positive_windows']:.1f}%) | {r['mean_episode_flagged_pct']:.1f}% |"]
    if broad:
        text += ["", "## Claims speakers advance", "",
                 "Advancement includes assertions and tentative hypotheses; it excludes neutral reports and debunking. "
                 "It does not mean firm belief or misinformation.", "",
                 "| Show | Windows with an advanced broad claim | Percentage of all windows |",
                 "| --- | ---: | ---: |"]
        for r in shows:
            text.append(f"| {SHOWS[r['show']]} | {r['advanced_windows']}/{r['windows']} | {r['pooled_advanced_pct_all_windows']:.1f}% |")
    text += ["", "## Episode summaries", "", "| Show / guest | Flagged windows | All windows | Flagged % | Uncertain % |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for r in episodes:
        text += [f"| {r['show'].upper()} / {r['guest']} | {r['fringe_windows']} | {r['windows']} | "
                 f"{r['flagged_pct_all_windows']:.1f}% | {r['uncertain_pct_all_windows']:.1f}% |"]
    text += ["", "## Interpretation and reproducibility", "",
        "The unit is a 256-word window with a 128-word stride. These percentages describe windows containing claims; "
        "they do not estimate the share of false statements, unique claims, or speaking time. The same spoken claim can "
        "appear in adjacent windows. No independent-window confidence intervals are calculated.", "",
        "Only Stage-04 health/science-positive windows received claim classification. Screen-negative windows remain "
        "in the full-episode denominator and can contain screening false negatives. Uncertain is a separate category. "
        "If a window contains both flagged and uncertain claims, the plot shows it as flagged.", "",
        "The labels are provisional model judgments from general knowledge, without independent literature verification. "
        "The presence of a claim does not establish endorsement or misinformation. These selected episodes do not "
        "establish show-wide population rates.", "",
        f"Source: `{path.relative_to(ROOT)}`. SHA-256: `{manifest['source_sha256']}`.", "",
        "Underlying counts and both denominators are in `episode_summary.csv` and `show_summary.csv`. "
        "Every chart also has an editable SVG version. Regenerate with `code/09_plot_fringe_extent.py`.", "",
        "Broader codebook: `notes/BROAD_FRINGE_CLASSIFICATION.md`; prompt: `config/broad_fringe_classification.json`."]
    if broad:
        text += ["", "The category figure's counts are in `category_summary.csv`. Categories overlap and must not be added. "
                 "Unmatched quotations cannot establish a positive category count. The transcript-window CSV retains "
                 "each claim, its exact/source-aligned quote, model text, scientific position, exaggeration, stance, and reason."]
    (output / "report.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    path = args.input.resolve()
    broad, episodes, groups = read_input(path)
    shows = show_summary(episodes)
    categories = category_summary(groups) if broad else []
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    output = ROOT / "output/fringe_science" / (("broad_" if broad else "legacy_") + source_hash[:12])
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "episode_summary.csv", episodes)
    write_csv(output / "show_summary.csv", shows)
    if broad:
        write_csv(output / "category_summary.csv", categories)
    manifest = {"source": str(path.relative_to(ROOT)), "source_sha256": source_hash,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "definition": "broad_fringe_v1" if broad else "legacy_narrow_fringe",
                "episodes": len(episodes), "windows": sum(e["windows"] for e in episodes),
                "metadata_sources": {show: hashlib.sha256((ROOT / f"config/{show}_starter_sample.json").read_bytes()).hexdigest() for show in SHOWS},
                "denominators": ["all episode windows", "Stage-04 health/science-positive windows"],
                "independent_window_confidence_intervals": False,
                "broad_fringe_reclassification_complete": broad}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    graphics(output, broad, episodes, shows, groups, categories)
    report(output, path, broad, episodes, shows, manifest)
    print(json.dumps(shows, indent=2))
    print("Report:", output / "report.md")


if __name__ == "__main__":
    main()
