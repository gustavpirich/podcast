#!/usr/bin/env python3
"""Create simple episode-level descriptives for the broad-fringe pilot."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATEMENTS = (
    ROOT / "data/derived/classifications/health_objects/e5112711aca03600"
    / "statement_instances.csv"
)
WINDOWS = (
    ROOT / "data/derived/classifications/broad_fringe/5a165612d6459da0"
    / "broad_window_classification.csv"
)
OUTPUT = ROOT / "output/fringe_prevalence/simple_e5112711aca03600"
SHOW_LABELS = {"jre": "Joe Rogan Experience", "doac": "The Diary of a CEO"}
FRINGE = "#B64B3A"
UNCERTAIN = "#D9A441"
TEAL = "#307E80"
MIXED = "#8998A1"
INK = "#172D3B"
MUTED = "#526572"
BG = "#FCFBF8"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 6) if denominator else 0.0


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def build_episode_rows(
    instances: list[dict[str, str]], windows: list[dict[str, str]]
) -> list[dict[str, object]]:
    units: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in instances:
        units[row["statement_unit_id"]].append(row)

    units_by_episode: dict[tuple[str, str], list[list[dict[str, str]]]] = defaultdict(list)
    for group in units.values():
        keys = {(row["show"], row["episode_id"]) for row in group}
        if len(keys) != 1:
            raise ValueError("A statement unit crosses episode boundaries")
        units_by_episode[next(iter(keys))].append(group)

    windows_by_episode: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in windows:
        windows_by_episode[(row["show"], row["episode_id"])].append(row)
    if set(units_by_episode) != set(windows_by_episode):
        raise ValueError("Statement and window inputs cover different episodes")

    output: list[dict[str, object]] = []
    for key in sorted(units_by_episode):
        grouped_units = units_by_episode[key]
        episode_windows = windows_by_episode[key]
        representatives = [
            next(row for row in group if row["is_representative"] == "1")
            for group in grouped_units
        ]
        rep_counts = Counter(row["existing_broad_status"] for row in representatives)
        instance_counts = Counter(
            row["existing_broad_status"] for group in grouped_units for row in group
        )
        lower = sum(
            {row["existing_broad_status"] for row in group} == {"fringe"}
            for group in grouped_units
        )
        upper = sum(
            any(row["existing_broad_status"] == "fringe" for row in group)
            for group in grouped_units
        )
        mixed = sum(
            len({row["existing_broad_status"] for row in group}) > 1
            for group in grouped_units
        )
        window_counts = Counter(row["broad_status"] for row in episode_windows)
        screen_positive = sum(row["stage08_requested"] == "1" for row in episode_windows)
        sample = representatives[0]
        n_units = len(grouped_units)
        n_instances = sum(len(group) for group in grouped_units)
        n_windows = len(episode_windows)
        if sum(rep_counts.values()) != n_units or sum(instance_counts.values()) != n_instances:
            raise ValueError(f"Statement outcomes do not reconcile for {key}")
        if not lower <= rep_counts["fringe"] <= upper:
            raise ValueError(f"Fringe sensitivity bounds do not contain the representative estimate for {key}")
        if sum(window_counts.values()) != n_windows or screen_positive > n_windows:
            raise ValueError(f"Window outcomes do not reconcile for {key}")
        output.append({
            "show": key[0],
            "episode_id": key[1],
            "guest": sample["guest"],
            "published_date": sample["published_date"],
            "episode_title": sample["episode_title"],
            "unique_statement_units": n_units,
            "representative_fringe_statements": rep_counts["fringe"],
            "representative_uncertain_statements": rep_counts["uncertain"],
            "representative_not_fringe_statements": rep_counts["not_fringe"],
            "representative_fringe_pct": pct(rep_counts["fringe"], n_units),
            "representative_uncertain_pct": pct(rep_counts["uncertain"], n_units),
            "all_instances_fringe_units_lower": lower,
            "any_instance_fringe_units_upper": upper,
            "fringe_pct_lower": pct(lower, n_units),
            "fringe_pct_upper": pct(upper, n_units),
            "mixed_status_units": mixed,
            "mixed_status_pct": pct(mixed, n_units),
            "claim_instances_with_overlap": n_instances,
            "fringe_claim_instances": instance_counts["fringe"],
            "fringe_claim_instance_pct": pct(instance_counts["fringe"], n_instances),
            "all_windows": n_windows,
            "screen_positive_windows": screen_positive,
            "fringe_windows": window_counts["fringe"],
            "uncertain_windows": window_counts["uncertain"],
            "fringe_pct_all_windows": pct(window_counts["fringe"], n_windows),
            "fringe_pct_screen_positive_windows": pct(window_counts["fringe"], screen_positive),
        })
    return output


def aggregate(rows: list[dict[str, object]], show: str, label: str) -> dict[str, object]:
    sums = {
        key: sum(int(row[key]) for row in rows)
        for key in (
            "unique_statement_units", "representative_fringe_statements",
            "representative_uncertain_statements", "representative_not_fringe_statements",
            "all_instances_fringe_units_lower", "any_instance_fringe_units_upper",
            "mixed_status_units", "claim_instances_with_overlap", "fringe_claim_instances",
            "all_windows", "screen_positive_windows", "fringe_windows", "uncertain_windows",
        )
    }
    return {
        "show": show,
        "label": label,
        "episodes": len(rows),
        **sums,
        "representative_fringe_pct": pct(sums["representative_fringe_statements"], sums["unique_statement_units"]),
        "representative_uncertain_pct": pct(sums["representative_uncertain_statements"], sums["unique_statement_units"]),
        "fringe_pct_lower": pct(sums["all_instances_fringe_units_lower"], sums["unique_statement_units"]),
        "fringe_pct_upper": pct(sums["any_instance_fringe_units_upper"], sums["unique_statement_units"]),
        "mixed_status_pct": pct(sums["mixed_status_units"], sums["unique_statement_units"]),
        "fringe_claim_instance_pct": pct(sums["fringe_claim_instances"], sums["claim_instances_with_overlap"]),
        "fringe_pct_all_windows": pct(sums["fringe_windows"], sums["all_windows"]),
        "fringe_pct_screen_positive_windows": pct(sums["fringe_windows"], sums["screen_positive_windows"]),
    }


def make_figures(rows: list[dict[str, object]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp/matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "tmp/plot_cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import PercentFormatter

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "figure.facecolor": BG, "axes.facecolor": BG, "text.color": INK,
        "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": INK,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.spines.bottom": False,
        "svg.fonttype": "none",
    })

    ordered = sorted(rows, key=lambda row: (str(row["show"]), -float(row["representative_fringe_pct"])))
    labels = [f"{str(row['show']).upper()} · {row['guest']}" for row in ordered]
    y = list(range(len(ordered)))

    fig, ax = plt.subplots(figsize=(13, 10))
    fig.subplots_adjust(left=.30, right=.91, top=.82, bottom=.13)
    fig.text(.055, .965, "PROVISIONAL MODEL-ASSISTED CLASSIFICATION", fontsize=9, weight="bold", color=FRINGE, va="top")
    fig.text(.055, .925, "Fringe claims among unique statements", fontsize=22, weight="bold", va="top")
    fig.text(.055, .878, "Point: centrally located representative context · line: lower-to-upper range from repeated-window disagreements", fontsize=10, color=MUTED, va="top")
    for index, row in enumerate(ordered):
        low, high = float(row["fringe_pct_lower"]), float(row["fringe_pct_upper"])
        rate = float(row["representative_fringe_pct"])
        ax.plot([low, high], [index, index], color=MIXED, linewidth=4, solid_capstyle="round", zorder=1)
        ax.scatter(rate, index, s=55, color=FRINGE, zorder=2)
        ax.text(high + .7, index, f"{rate:.1f}%", va="center", fontsize=9, weight="bold")
    ax.set_yticks(y, labels, fontsize=8.5)
    ax.set_ylim(len(ordered) - .5, -.5)
    ax.set_xlim(0, max(float(row["fringe_pct_upper"]) for row in ordered) + 8)
    ax.xaxis.set_major_formatter(PercentFormatter(100))
    ax.xaxis.grid(True, color="#DEE3E6", linewidth=.6)
    ax.tick_params(axis="both", length=0)
    ax.set_xlabel("Percentage of deduplicated statement units")
    fig.legend(handles=[
        Line2D([], [], marker="o", color="none", markerfacecolor=FRINGE, markeredgecolor=FRINGE, label="Representative-context estimate"),
        Line2D([], [], color=MIXED, linewidth=4, label="All-instance to any-instance fringe range"),
    ], loc="lower left", bbox_to_anchor=(.055, .035), ncol=2, frameon=False)
    fig.savefig(output / "01_episode_statement_prevalence.png", dpi=180, facecolor=BG)
    fig.savefig(output / "01_episode_statement_prevalence.svg", facecolor=BG)
    plt.close(fig)

    ordered = sorted(rows, key=lambda row: (str(row["show"]), -float(row["fringe_pct_all_windows"])))
    labels = [f"{str(row['show']).upper()} · {row['guest']}" for row in ordered]
    fig, ax = plt.subplots(figsize=(13, 10))
    fig.subplots_adjust(left=.30, right=.91, top=.82, bottom=.13)
    fig.text(.055, .965, "PROVISIONAL MODEL-ASSISTED CLASSIFICATION", fontsize=9, weight="bold", color=FRINGE, va="top")
    fig.text(.055, .925, "Transcript windows containing fringe claims", fontsize=22, weight="bold", va="top")
    fig.text(.055, .878, "Share of all 256-word windows in each episode · uncertainty remains a separate category", fontsize=10, color=MUTED, va="top")
    for index, row in enumerate(ordered):
        fringe = float(row["fringe_pct_all_windows"])
        uncertain = 100 * int(row["uncertain_windows"]) / int(row["all_windows"])
        ax.barh(index, fringe, height=.58, color=FRINGE)
        ax.barh(index, uncertain, left=fringe, height=.58, color=UNCERTAIN)
        ax.text(fringe + uncertain + .7, index, f"{fringe:.1f}%", va="center", fontsize=9, weight="bold")
    ax.set_yticks(range(len(ordered)), labels, fontsize=8.5)
    ax.set_ylim(len(ordered) - .5, -.5)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(PercentFormatter(100))
    ax.xaxis.grid(True, color="#DEE3E6", linewidth=.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", length=0)
    ax.set_xlabel("Percentage of all transcript windows")
    fig.legend(handles=[
        Line2D([], [], color=FRINGE, linewidth=7, label="Fringe claim present"),
        Line2D([], [], color=UNCERTAIN, linewidth=7, label="Uncertain claim, no fringe claim"),
    ], loc="lower left", bbox_to_anchor=(.055, .035), ncol=2, frameon=False)
    fig.savefig(output / "02_episode_window_prevalence.png", dpi=180, facecolor=BG)
    fig.savefig(output / "02_episode_window_prevalence.svg", facecolor=BG)
    plt.close(fig)


def write_report(
    episode_rows: list[dict[str, object]], show_rows: list[dict[str, object]]
) -> None:
    overall = next(row for row in show_rows if row["show"] == "all")
    lines = [
        "# Simple descriptives of broad-fringe prevalence",
        "",
        "These are provisional model-assisted descriptives for the selected 20-episode pilot. "
        "The broad-fringe definition includes emerging non-mainstream, alternative or speculative, "
        "consensus-contradicting, and materially exaggerated scientific claims. It is broader than misinformation.",
        "",
        "## Pooled results",
        "",
        f"- **Unique statements:** {int(overall['representative_fringe_statements']):,} of "
        f"{int(overall['unique_statement_units']):,} representative statements are fringe "
        f"({float(overall['representative_fringe_pct']):.1f}%).",
        f"- **Uncertain statements:** {int(overall['representative_uncertain_statements']):,} of "
        f"{int(overall['unique_statement_units']):,} ({float(overall['representative_uncertain_pct']):.1f}%). "
        "Uncertain is not counted as fringe.",
        f"- **Overlap sensitivity:** the unique-statement fringe rate ranges from "
        f"{float(overall['fringe_pct_lower']):.1f}% when every overlapping instance must be fringe to "
        f"{float(overall['fringe_pct_upper']):.1f}% when any instance may be fringe. "
        f"There are {int(overall['mixed_status_units']):,} mixed-status units "
        f"({float(overall['mixed_status_pct']):.1f}%).",
        f"- **All transcript windows:** {int(overall['fringe_windows']):,} of "
        f"{int(overall['all_windows']):,} contain at least one fringe claim "
        f"({float(overall['fringe_pct_all_windows']):.1f}%).",
        f"- **Health/science-positive windows:** {int(overall['fringe_windows']):,} of "
        f"{int(overall['screen_positive_windows']):,} contain at least one fringe claim "
        f"({float(overall['fringe_pct_screen_positive_windows']):.1f}%).",
        "",
        "## By show",
        "",
        "| Show | Unique statements | Fringe statements | Fringe % | Uncertain % | Fringe windows / all windows |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in show_rows:
        if row["show"] == "all":
            continue
        lines.append(
            f"| {row['label']} | {int(row['unique_statement_units']):,} | "
            f"{int(row['representative_fringe_statements']):,} | "
            f"{float(row['representative_fringe_pct']):.1f}% | "
            f"{float(row['representative_uncertain_pct']):.1f}% | "
            f"{int(row['fringe_windows']):,}/{int(row['all_windows']):,} "
            f"({float(row['fringe_pct_all_windows']):.1f}%) |"
        )
    lines.extend([
        "",
        "The statement-level rates are similar across shows: 42.0% for JRE and 42.4% for DOAC. "
        "The all-window rate is higher for DOAC (44.0%) than JRE (38.2%) because the prevalence and "
        "density of health/science-positive windows differ.",
        "",
        "## By episode",
        "",
        "| Show | Guest | Unique statements | Fringe n | Fringe % | Uncertain % | Fringe-window % |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in sorted(episode_rows, key=lambda value: -float(value["representative_fringe_pct"])):
        lines.append(
            f"| {str(row['show']).upper()} | {row['guest']} | {int(row['unique_statement_units']):,} | "
            f"{int(row['representative_fringe_statements']):,} | "
            f"{float(row['representative_fringe_pct']):.1f}% | "
            f"{float(row['representative_uncertain_pct']):.1f}% | "
            f"{float(row['fringe_pct_all_windows']):.1f}% |"
        )
    lines.extend([
        "",
        "![Episode statement prevalence](01_episode_statement_prevalence.png)",
        "",
        "![Episode window prevalence](02_episode_window_prevalence.png)",
        "",
        "## Interpretation limits",
        "",
        "The episodes are a selected pilot, so these figures do not estimate all episodes of either show. "
        "Long episodes and episodes containing more extractable claims contribute more statements to pooled rates. "
        "Episode percentages with small denominators, such as the Ray Dalio episode with 26 unique statements, "
        "are especially unstable. The labels require human validation before use as research findings.",
        "",
    ])
    (OUTPUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    instances = read_csv(STATEMENTS)
    windows = read_csv(WINDOWS)
    if len(instances) != 8504 or len(windows) != 4124:
        raise ValueError("Unexpected pilot input dimensions")
    episode_rows = build_episode_rows(instances, windows)
    show_rows = [
        aggregate([row for row in episode_rows if row["show"] == show], show, SHOW_LABELS[show])
        for show in ("jre", "doac")
    ]
    show_rows.append(aggregate(episode_rows, "all", "All 20 episodes"))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "episode_prevalence.csv", episode_rows)
    write_csv(OUTPUT / "show_prevalence.csv", show_rows)
    make_figures(episode_rows, OUTPUT)
    write_report(episode_rows, show_rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "provisional_model_assisted_not_human_validated",
        "episodes": len(episode_rows),
        "statement_instances": len(instances),
        "unique_statement_units": len({row["statement_unit_id"] for row in instances}),
        "windows": len(windows),
        "statement_input": str(STATEMENTS.relative_to(ROOT)),
        "statement_input_sha256": sha256(STATEMENTS),
        "window_input": str(WINDOWS.relative_to(ROOT)),
        "window_input_sha256": sha256(WINDOWS),
        "script": str(Path(__file__).relative_to(ROOT)),
        "script_sha256": sha256(Path(__file__)),
        "definitions": {
            "representative_fringe_pct": "Fringe representative instances divided by unique statement units.",
            "fringe_pct_lower": "Units for which every overlapping instance is fringe divided by unique statement units.",
            "fringe_pct_upper": "Units with at least one fringe instance divided by unique statement units.",
            "fringe_pct_all_windows": "Windows containing at least one fringe claim divided by all episode windows.",
            "fringe_pct_screen_positive_windows": "Fringe windows divided by Stage-04 health/science-positive windows.",
        },
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(episode_rows)} episode rows to {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
