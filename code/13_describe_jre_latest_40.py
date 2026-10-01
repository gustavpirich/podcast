#!/usr/bin/env python3
"""Create descriptive tables and figures for the latest-40 JRE Stage-05 screen."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "config/jre_latest_40_2026-09-15.json"
SOURCE_PATHS = [
    ROOT / "data/derived/classifications/openai_passage_content/"
    "jre_2550_and_previous_9_2026-09-10/3d140a303b6c/"
    "window_claim_classification.csv",
    ROOT / "data/derived/classifications/openai_passage_content/"
    "jre_latest_40_new_30_2026-09-16/32b86e7a88f5/"
    "window_claim_classification.csv",
]
VALID_STATUSES = {"fringe", "uncertain", "not_fringe", "not_assessable"}
DISPLAY_STATUSES = ["fringe", "uncertain", "not_fringe", "no_claim", "screen_negative"]
STATUS_LABELS = {
    "fringe": "Fringe",
    "uncertain": "Uncertain",
    "not_fringe": "Not fringe",
    "no_claim": "No assessable claim",
    "screen_negative": "Screen-negative",
}
COLORS = {
    "fringe": "#B64B3A",
    "uncertain": "#D9A441",
    "not_fringe": "#307E80",
    "no_claim": "#9BA8B0",
    "screen_negative": "#E5E9EC",
}
INK, MUTED, BG = "#172D3B", "#526572", "#FCFBF8"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def load_sources() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rows: list[dict[str, str]] = []
    provenance: list[dict[str, Any]] = []
    for path in SOURCE_PATHS:
        with path.open(newline="", encoding="utf-8") as handle:
            source_rows = list(csv.DictReader(handle))
        summary_path = path.with_name("classification_summary.json")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if len(source_rows) != summary["totals"]["windows"]:
            raise ValueError(f"Source row count does not match summary: {path}")
        rows.extend(source_rows)
        provenance.append({
            "csv": str(path.relative_to(ROOT)),
            "csv_sha256": sha256(path),
            "summary": str(summary_path.relative_to(ROOT)),
            "summary_sha256": sha256(summary_path),
            "sample_id": summary["sample_id"],
            "run_id": summary["method"]["run_id"],
            "prompt_version": summary["method"]["prompt_version"],
            "model": summary["method"]["model_requested"],
            "windows": len(source_rows),
        })
    return rows, provenance


def episode_summaries(
    rows: list[dict[str, str]], sample: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata = {episode["episode_id"]: episode for episode in sample["episodes"]}
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_keys: set[tuple[str, int]] = set()
    for row in rows:
        episode_id = row["episode_id"]
        window_id = int(row["window_id"])
        key = (episode_id, window_id)
        if key in seen_keys:
            raise ValueError(f"Duplicate episode/window key: {key}")
        seen_keys.add(key)
        if episode_id not in metadata:
            raise ValueError(f"Unexpected episode: {episode_id}")
        if int(row["word_count"]) != 256:
            raise ValueError(f"Non-256-word window: {key}")
        if int(row["word_start_index"]) != window_id * 128:
            raise ValueError(f"Unexpected window stride: {key}")
        if row["fringe_status"] not in VALID_STATUSES:
            raise ValueError(f"Invalid fringe status: {key}")
        screen_positive = bool(
            int(row["screen_health_related"]) or int(row["screen_science_related"])
        )
        if int(row["stage05_requested"]) != int(screen_positive):
            raise ValueError(f"Stage-05 selection differs from Stage-04 labels: {key}")
        groups[episode_id].append(row)
    if set(groups) != set(metadata):
        missing = sorted(set(metadata) - set(groups))
        extra = sorted(set(groups) - set(metadata))
        raise ValueError(f"Episode coverage mismatch; missing={missing}, extra={extra}")

    output: list[dict[str, Any]] = []
    for sequence, episode in enumerate(sample["episodes"], 1):
        episode_id = episode["episode_id"]
        group = sorted(groups[episode_id], key=lambda row: int(row["window_id"]))
        if [int(row["window_id"]) for row in group] != list(range(len(group))):
            raise ValueError(f"Incomplete window sequence: {episode_id}")
        display_counts: Counter[str] = Counter()
        health = science = claims = unmatched = inconsistent = 0
        for row in group:
            screen_positive = bool(
                int(row["screen_health_related"]) or int(row["screen_science_related"])
            )
            if not screen_positive:
                display_counts["screen_negative"] += 1
            elif row["fringe_status"] == "not_assessable":
                display_counts["no_claim"] += 1
            else:
                display_counts[row["fringe_status"]] += 1
            health += int(row["screen_health_related"])
            science += int(row["screen_science_related"])
            claims += int(row["claim_count"])
            unmatched += int(row["unmatched_claim_text_count"])
            inconsistent += int(row["inconsistent_claim_coding_count"])
        windows = len(group)
        screened = windows - display_counts["screen_negative"]
        if sum(display_counts.values()) != windows:
            raise ValueError(f"Status counts do not reconcile: {episode_id}")
        output.append({
            "sequence_latest_to_oldest": sequence,
            "episode_id": episode_id,
            "episode_number": episode.get("episode_number", ""),
            "episode_kind": episode["episode_kind"],
            "guest": episode["guest_name"],
            "published_date": episode["published_date"],
            "episode_title": group[0]["episode_title"],
            "windows": windows,
            "screen_positive_windows": screened,
            "health_positive_windows": health,
            "science_positive_windows": science,
            **{f"{status}_windows": display_counts[status] for status in DISPLAY_STATUSES},
            "fringe_pct_all_windows": 100 * display_counts["fringe"] / windows,
            "fringe_pct_screen_positive_windows": (
                100 * display_counts["fringe"] / screened if screened else 0
            ),
            "uncertain_pct_all_windows": 100 * display_counts["uncertain"] / windows,
            "uncertain_pct_screen_positive_windows": (
                100 * display_counts["uncertain"] / screened if screened else 0
            ),
            "claim_instances_with_overlap": claims,
            "unmatched_claim_quotations": unmatched,
            "inconsistent_claim_codings": inconsistent,
        })

    windows = sum(row["windows"] for row in output)
    screened = sum(row["screen_positive_windows"] for row in output)
    totals = {status: sum(row[f"{status}_windows"] for row in output)
              for status in DISPLAY_STATUSES}
    overall = {
        "episodes": len(output),
        "windows": windows,
        "screen_positive_windows": screened,
        "health_positive_windows": sum(row["health_positive_windows"] for row in output),
        "science_positive_windows": sum(row["science_positive_windows"] for row in output),
        **{f"{status}_windows": totals[status] for status in DISPLAY_STATUSES},
        "fringe_pct_all_windows": 100 * totals["fringe"] / windows,
        "fringe_pct_screen_positive_windows": 100 * totals["fringe"] / screened,
        "uncertain_pct_all_windows": 100 * totals["uncertain"] / windows,
        "uncertain_pct_screen_positive_windows": 100 * totals["uncertain"] / screened,
        "mean_episode_fringe_pct_all_windows": (
            sum(row["fringe_pct_all_windows"] for row in output) / len(output)
        ),
        "claim_instances_with_overlap": sum(
            row["claim_instances_with_overlap"] for row in output
        ),
        "unmatched_claim_quotations": sum(
            row["unmatched_claim_quotations"] for row in output
        ),
        "inconsistent_claim_codings": sum(
            row["inconsistent_claim_codings"] for row in output
        ),
    }
    if sum(totals.values()) != windows:
        raise ValueError("Overall status counts do not reconcile")
    return output, overall


def configure_plots() -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp/matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "tmp/plot_cache"))


def plots(output: Path, episodes: list[dict[str, Any]], overall: dict[str, Any]) -> None:
    configure_plots()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.ticker import PercentFormatter

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "figure.facecolor": BG, "axes.facecolor": BG, "text.color": INK,
        "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": INK,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.spines.bottom": False,
        "svg.fonttype": "none",
    })

    def heading(fig: Any, title: str, subtitle: str) -> None:
        fig.text(.055, .97, "PROVISIONAL NARROW CLAIM/FRINGE SCREEN", fontsize=9,
                 weight="bold", color=COLORS["fringe"], va="top")
        fig.text(.055, .925, title, fontsize=21, weight="bold", va="top")
        fig.text(.055, .88, subtitle, fontsize=10, color=MUTED, va="top")

    def save(fig: Any, name: str) -> None:
        fig.savefig(output / f"{name}.png", dpi=180, facecolor=BG)
        fig.savefig(output / f"{name}.svg", facecolor=BG)
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8))
    fig.subplots_adjust(left=.08, right=.96, top=.74, bottom=.27, wspace=.32)
    heading(fig, "What do the latest 40 JRE windows contain?",
            "Pooled window composition using all windows and screened-positive windows")
    all_values = [100 * overall[f"{status}_windows"] / overall["windows"]
                  for status in DISPLAY_STATUSES]
    positive_statuses = DISPLAY_STATUSES[:-1]
    positive_values = [100 * overall[f"{status}_windows"] /
                       overall["screen_positive_windows"] for status in positive_statuses]
    for ax, values, statuses, title in [
        (axes[0], all_values, DISPLAY_STATUSES, "All transcript windows"),
        (axes[1], positive_values, positive_statuses, "Health/science-positive windows"),
    ]:
        left = 0.0
        for value, status in zip(values, statuses):
            ax.barh(0, value, left=left, color=COLORS[status], height=.46)
            if value >= 7:
                ax.text(left + value / 2, 0, f"{value:.1f}%", ha="center", va="center",
                        color="white" if status in {"fringe", "not_fringe"} else INK,
                        weight="bold")
            left += value
        ax.set_title(title, loc="left", fontsize=12, weight="bold")
        ax.set_xlim(0, 100)
        ax.set_yticks([])
        ax.xaxis.set_major_formatter(PercentFormatter(100))
        ax.tick_params(axis="x", length=0)
    fig.legend(handles=[Patch(color=COLORS[s], label=STATUS_LABELS[s])
                        for s in DISPLAY_STATUSES], loc="lower left",
               bbox_to_anchor=(.055, .08), ncol=3, frameon=False)
    fig.text(.055, .035, "Adjacent 256-word windows overlap by 128 words. Uncertain is not counted as fringe.",
             color=MUTED, fontsize=9)
    save(fig, "01_overall_composition")

    chronological = list(reversed(episodes))
    fig, ax = plt.subplots(figsize=(14, 10.5))
    fig.subplots_adjust(left=.29, right=.96, top=.82, bottom=.12)
    heading(fig, "Episode-level flagged and uncertain shares",
            "Percentage of all episode windows, ordered from newest to oldest")
    for index, row in enumerate(chronological):
        ax.scatter(row["fringe_pct_all_windows"], index, color=COLORS["fringe"], s=42)
        ax.scatter(row["uncertain_pct_all_windows"], index, color=COLORS["uncertain"], s=42)
    ax.set_yticks(range(len(chronological)), [
        f"{row['published_date']} · {row['episode_title']}" for row in chronological
    ], fontsize=8)
    ax.set_xlim(0, max(55, max(row["uncertain_pct_all_windows"] for row in episodes) + 5))
    ax.xaxis.set_major_formatter(PercentFormatter(100))
    ax.xaxis.grid(True, color="#DEE3E6", linewidth=.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", length=0)
    ax.set_xlabel("Percentage of all episode windows")
    fig.legend(handles=[Patch(color=COLORS["fringe"], label="Fringe"),
                        Patch(color=COLORS["uncertain"], label="Uncertain")],
               loc="lower left", bbox_to_anchor=(.055, .035), ncol=2, frameon=False)
    save(fig, "02_episode_rates")

    fig, ax = plt.subplots(figsize=(14, 11))
    fig.subplots_adjust(left=.29, right=.96, top=.82, bottom=.13)
    heading(fig, "Composition of every episode",
            "All standardized windows, ordered from newest to oldest")
    for index, row in enumerate(chronological):
        left = 0.0
        for status in DISPLAY_STATUSES:
            value = 100 * row[f"{status}_windows"] / row["windows"]
            ax.barh(index, value, left=left, color=COLORS[status], height=.66)
            left += value
    ax.set_yticks(range(len(chronological)), [
        f"{row['published_date']} · {row['guest']}" for row in chronological
    ], fontsize=8)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(PercentFormatter(100))
    ax.tick_params(axis="both", length=0)
    ax.set_xlabel("Percentage of all episode windows")
    fig.legend(handles=[Patch(color=COLORS[s], label=STATUS_LABELS[s])
                        for s in DISPLAY_STATUSES], loc="lower left",
               bbox_to_anchor=(.055, .035), ncol=3, frameon=False)
    save(fig, "03_episode_composition")


def report(
    output: Path, episodes: list[dict[str, Any]], overall: dict[str, Any],
    provenance: list[dict[str, Any]], bundle_hash: str,
) -> None:
    text = [
        "# Latest 40 JRE episodes: descriptive Stage-05 results", "",
        "These are provisional model-assisted results under the narrow claim/fringe definition. "
        "They have not been validated against scientific literature or human coding and must not "
        "be described as misinformation prevalence.", "",
        "## Corpus", "",
        f"The frozen latest-40 sample contains **{overall['episodes']} episodes** and "
        f"**{overall['windows']:,} overlapping 256-word windows**. Stage 05 examined "
        f"**{overall['screen_positive_windows']:,}** windows selected by the Stage-04 "
        "health/science screen and extracted "
        f"**{overall['claim_instances_with_overlap']:,} claim instances**. Because adjacent "
        "windows overlap, these are not unique claims.", "",
        "## Pooled window results", "",
        "| Outcome | Windows | % of all windows | % of screened-positive windows |", 
        "| --- | ---: | ---: | ---: |",
    ]
    for status in ["fringe", "uncertain", "not_fringe", "no_claim"]:
        count = overall[f"{status}_windows"]
        text.append(
            f"| {STATUS_LABELS[status]} | {count:,} | "
            f"{100 * count / overall['windows']:.1f}% | "
            f"{100 * count / overall['screen_positive_windows']:.1f}% |"
        )
    text.append(
        f"| Screen-negative | {overall['screen_negative_windows']:,} | "
        f"{100 * overall['screen_negative_windows'] / overall['windows']:.1f}% | — |"
    )
    text += ["", "![Overall composition](01_overall_composition.png)", "",
             "![Episode rates](02_episode_rates.png)", "",
             "![Episode composition](03_episode_composition.png)", "",
             "## Episode table", "",
             "| Date | Episode | Windows | Screened | Fringe / all | Fringe / screened | Uncertain / all |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in episodes:
        text.append(
            f"| {row['published_date']} | {row['episode_title']} | {row['windows']:,} | "
            f"{row['screen_positive_windows']:,} | {row['fringe_windows']:,} "
            f"({row['fringe_pct_all_windows']:.1f}%) | "
            f"{row['fringe_pct_screen_positive_windows']:.1f}% | "
            f"{row['uncertain_pct_all_windows']:.1f}% |"
        )
    prompt_versions = ", ".join(
        f"`{source['prompt_version']}` ({source['windows']:,} windows)"
        for source in provenance
    )
    text += ["", "## Interpretation and limitations", "",
        "- The primary denominator is all standardized windows. The secondary denominator is "
        "Stage-04 health/science-positive windows.",
        "- A fringe window contains at least one claim provisionally coded fringe. If no fringe "
        "claim is present, uncertain takes precedence over not-fringe.",
        "- Screen-negative windows were not sent to Stage 05. They can include false negatives.",
        "- Window overlap means observations are dependent and claim instances can repeat. No "
        "independent-window confidence intervals are reported.",
        "- Claim presence does not establish speaker endorsement, intent, factual falsity, harm, "
        "or misinformation.",
        f"- The two frozen cohorts used compatible rules but different prompt versions: "
        f"{prompt_versions}. Cohort differences may therefore reflect instrumentation as well as content.",
        f"- The collector flagged {overall['unmatched_claim_quotations']:,} unmatched claim quotations "
        f"and {overall['inconsistent_claim_codings']:,} consensus/fringe inconsistencies for review.",
        "- These 40 recent selected episodes do not establish rates for the complete JRE archive.",
        "", "## Reproducibility", "",
        f"Source-bundle SHA-256: `{bundle_hash}`.", "",
        "Underlying values are in `overall_summary.csv` and `episode_summary.csv`. Every figure "
        "is supplied as PNG and editable SVG. Regenerate with "
        "`.venv/bin/python code/13_describe_jre_latest_40.py`.",
    ]
    (output / "report.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def main() -> int:
    rows, provenance = load_sources()
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    episodes, overall = episode_summaries(rows, sample)
    bundle_material = "\n".join(
        [sha256(SAMPLE_PATH), *(source["csv_sha256"] for source in provenance)]
    ).encode()
    bundle_hash = hashlib.sha256(bundle_material).hexdigest()
    output = ROOT / "output/jre_latest_40_stage05" / bundle_hash[:12]
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "episode_summary.csv", episodes)
    write_csv(output / "overall_summary.csv", [overall])
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "provisional_model_assisted_not_human_validated",
        "definition": "legacy_narrow_claim_fringe",
        "sample": str(SAMPLE_PATH.relative_to(ROOT)),
        "sample_sha256": sha256(SAMPLE_PATH),
        "sources": provenance,
        "source_bundle_sha256": bundle_hash,
        "script_sha256": sha256(Path(__file__)),
        "denominators": ["all standardized windows", "Stage-04 screen-positive windows"],
        "checks": {
            "episodes": overall["episodes"],
            "windows": overall["windows"],
            "unique_episode_window_keys": True,
            "all_windows_256_words": True,
            "within_episode_stride_128_words": True,
            "status_counts_reconcile": True,
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    plots(output, episodes, overall)
    report(output, episodes, overall, provenance, bundle_hash)
    print(json.dumps(overall, indent=2))
    print(f"Report: {output.relative_to(ROOT) / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
