#!/usr/bin/env python3
"""Draft figures for five candidate supply/demand descriptives (pilot mockups).

Figures 1-3 and 5 use the provisional, not yet human-validated pilot data.
Figure 4 (host treatment) uses SIMULATED data with invented parameters, because
host responses have not been coded; it only shows what the figure would look
like and must never be cited as a result.
"""

from __future__ import annotations

import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
RUN = "e5112711aca03600"
STATEMENTS = ROOT / f"data/derived/descriptives/fringe_supply_pilot_20_{RUN}/statements.csv"
SNAPSHOT = ROOT / "data/raw/audience_metrics/youtube/20261001T205301Z/metrics.json"
OUTPUT = ROOT / "output/descriptives_mockup"
SNAPSHOT_DATE = date(2026, 10, 1)
SIM_SEED = 20261001

SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
TIERS = ["A_emerging", "B_speculative", "C_contradicts_consensus"]
TIER_LABEL = {"A_emerging": "A  Emerging", "B_speculative": "B  Speculative",
              "C_contradicts_consensus": "C  Contradicts consensus"}
TIER_COLOR = {"A_emerging": "#86b6ef", "B_speculative": "#2a78d6", "C_contradicts_consensus": "#104281"}
ROLE_COLOR = {"guest": "#2a78d6", "host": "#eb6834"}
SHOW_LABEL = {"jre": "Joe Rogan Experience", "doac": "The Diary of a CEO"}
SHOW_COLOR = {"jre": "#2a78d6", "doac": "#eb6834"}
RESPONSES = ["Challenges", "Questions", "Neutral / moves on", "Affirms", "Amplifies"]
RESPONSE_COLOR = ["#e34948", "#f2a3a2", "#c9c8c3", "#86b6ef", "#2a78d6"]
PROVISIONAL = "Provisional model labels, not yet human-validated. Pilot: 20 episodes."

csv.field_size_limit(sys.maxsize)
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlecolor": INK,
})


def short(name: str) -> str:
    return name.replace("Professor ", "Prof. ").replace("Dr ", "Dr. ")


def load() -> tuple[list[dict[str, str]], dict[str, dict]]:
    with STATEMENTS.open(encoding="utf-8", newline="") as handle:
        statements = list(csv.DictReader(handle))
    episodes = {row["youtube_id"]: row for row in json.loads(SNAPSHOT.read_text())["episodes"]}
    return statements, episodes


def finish(fig, path: Path, title: str, subtitle: str, note: str, top: float = 0.88) -> None:
    fig.subplots_adjust(top=top)
    fig.suptitle(title, x=0.01, y=0.995, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.text(0.01, 0.955, subtitle, ha="left", va="top", color=MUTED, fontsize=10)
    fig.text(0.01, 0.005, note, ha="left", va="bottom", color=MUTED, fontsize=8)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def fig1_extent(statements, episodes) -> None:
    """Fringe claims per hour of audio, by episode and tier."""
    counts = defaultdict(Counter)
    for row in statements:
        if row["fringe_advanced"] == "1":
            counts[row["episode_id"]][row["fringe_tier"]] += 1
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharex=True, gridspec_kw={"wspace": 0.42})
    for ax, show in zip(axes, ["jre", "doac"]):
        ids = [k for k, v in episodes.items() if v["show"] == show]
        hours = {k: episodes[k]["duration"] / 3600 for k in ids}
        ids.sort(key=lambda k: sum(counts[k].values()) / hours[k])
        left = [0.0] * len(ids)
        for tier in TIERS:
            values = [counts[k][tier] / hours[k] for k in ids]
            ax.barh(range(len(ids)), values, left=left, color=TIER_COLOR[tier], height=0.7,
                    edgecolor=SURFACE, linewidth=1.5, label=TIER_LABEL[tier])
            left = [a + b for a, b in zip(left, values)]
        for y, total in enumerate(left):
            ax.text(total + 0.8, y, f"{total:.0f}", va="center", color=MUTED, fontsize=8)
        ax.set_yticks(range(len(ids)), [short(episodes[k]["guest_name"]) for k in ids])
        ax.set_title(SHOW_LABEL[show], loc="left")
        ax.xaxis.grid(True, color=GRID)
        ax.set_axisbelow(True)
        ax.tick_params(left=False)
        ax.set_xlabel("Fringe claims advanced per hour")
    axes[1].legend(frameon=False, loc="lower right")
    finish(fig, OUTPUT / "fig1_extent_per_hour.png",
           "1 · Extent: how much fringe science is aired?",
           "Unique fringe claims put forward per hour of audio, split by tier. A few episodes carry most of it.",
           PROVISIONAL)


def fig2_topics(statements) -> None:
    """What fringe claims are about: primary object x tier."""
    fringe = [row for row in statements if row["fringe_advanced"] == "1"]
    objects = [name for name, _ in Counter(row["primary_object"] for row in fringe).most_common(9)]
    table = defaultdict(Counter)
    for row in fringe:
        key = row["primary_object"] if row["primary_object"] in objects else "other"
        table[key][row["fringe_tier"]] += 1
    order = sorted(table, key=lambda k: sum(table[k].values()))
    fig, ax = plt.subplots(figsize=(10, 5.2))
    left = [0] * len(order)
    for tier in TIERS:
        values = [table[k][tier] for k in order]
        ax.barh(range(len(order)), values, left=left, color=TIER_COLOR[tier], height=0.7,
                edgecolor=SURFACE, linewidth=1.5, label=TIER_LABEL[tier])
        left = [a + b for a, b in zip(left, values)]
    for y, total in enumerate(left):
        ax.text(total + 5, y, str(total), va="center", color=MUTED, fontsize=8)
    ax.set_yticks(range(len(order)), [k.replace("_", " ").capitalize() for k in order])
    ax.xaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.tick_params(left=False)
    ax.set_xlabel("Unique fringe claims")
    ax.legend(frameon=False, loc="lower right")
    finish(fig, OUTPUT / "fig2_topics.png",
           "2 · Content: what are fringe claims about?",
           f"{len(fringe):,} fringe claims by primary object. Non-health science (cosmology, archaeology, UFOs…) dominates.",
           PROVISIONAL)


def fig3_suppliers(statements, episodes) -> None:
    """Fringe claims per 10,000 words spoken: guest vs host, per episode."""
    words = defaultdict(Counter)
    fringe = defaultdict(Counter)
    speaker_path = STATEMENTS.parent / "speakers.csv"
    with speaker_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["speaker_role"] in ROLE_COLOR:
                words[row["episode_id"]][row["speaker_role"]] += int(row["speaker_words"])
                fringe[row["episode_id"]][row["speaker_role"]] += int(row["fringe_advanced_statements"])
    rate = {k: {r: 1e4 * fringe[k][r] / words[k][r] for r in ROLE_COLOR} for k in words}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharex=True, gridspec_kw={"wspace": 0.42})
    for ax, show in zip(axes, ["jre", "doac"]):
        ids = sorted((k for k in rate if episodes[k]["show"] == show), key=lambda k: rate[k]["guest"])
        for y, k in enumerate(ids):
            ax.plot([rate[k]["guest"], rate[k]["host"]], [y, y], color=GRID, linewidth=2, zorder=1)
            for role in ROLE_COLOR:
                ax.scatter(rate[k][role], y, s=55, color=ROLE_COLOR[role], edgecolor=SURFACE,
                           linewidth=2, zorder=2, label=role.capitalize() if y == 0 else None)
        ax.set_yticks(range(len(ids)), [short(episodes[k]["guest_name"]) for k in ids])
        ax.set_title(SHOW_LABEL[show], loc="left")
        ax.xaxis.grid(True, color=GRID)
        ax.set_axisbelow(True)
        ax.tick_params(left=False)
        ax.set_xlabel("Fringe claims per 10,000 words spoken")
    axes[0].legend(frameon=False, loc="lower right")
    finish(fig, OUTPUT / "fig3_suppliers.png",
           "3 · Supply: who puts fringe claims forward, host or guest?",
           "Rates per words each person spoke, so talk time doesn't drive the comparison. Host restatements are not yet separated.",
           PROVISIONAL)


def fig4_treatment_simulated() -> None:
    """SIMULATED host responses to guest fringe claims, by tier and show."""
    rng = random.Random(SIM_SEED)
    # Invented response probabilities (challenges, questions, neutral, affirms, amplifies).
    invented = {
        "jre": {"A_emerging": [.04, .16, .30, .32, .18], "B_speculative": [.05, .18, .27, .28, .22],
                "C_contradicts_consensus": [.08, .17, .30, .27, .18]},
        "doac": {"A_emerging": [.03, .30, .37, .25, .05], "B_speculative": [.05, .33, .35, .22, .05],
                 "C_contradicts_consensus": [.07, .32, .37, .20, .04]},
    }
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, show in zip(axes, ["jre", "doac"]):
        for y, tier in enumerate(reversed(TIERS)):
            draws = Counter(rng.choices(range(5), weights=invented[show][tier], k=150))
            shares = [draws[i] / 150 for i in range(5)]
            left = 0.0
            for i, share in enumerate(shares):
                ax.barh(y, share, left=left, color=RESPONSE_COLOR[i], height=0.65,
                        edgecolor=SURFACE, linewidth=1.5, label=RESPONSES[i] if y == 0 else None)
                if share >= 0.08:
                    ax.text(left + share / 2, y, f"{share:.0%}", ha="center", va="center",
                            color=INK if i in (1, 2, 3) else SURFACE, fontsize=8)
                left += share
        ax.set_yticks(range(3), [TIER_LABEL[t] for t in reversed(TIERS)])
        ax.set_xlim(0, 1)
        ax.set_xticks([0, .25, .5, .75, 1], ["0%", "25%", "50%", "75%", "100%"])
        ax.set_title(SHOW_LABEL[show], loc="left")
        ax.tick_params(left=False)
        ax.text(0.5, 0.5, "SIMULATED", transform=ax.transAxes, ha="center", va="center",
                fontsize=34, color="#e34948", alpha=0.18, fontweight="bold", rotation=12)
    axes[1].legend(frameon=False, ncol=5, loc="upper right", bbox_to_anchor=(1.0, -0.12), fontsize=8)
    finish(fig, OUTPUT / "fig4_host_treatment_SIMULATED.png",
           "4 · Treatment: how do hosts respond when a guest advances a fringe claim?  [SIMULATED]",
           "Host's next turn after a guest fringe claim. Requires new human/model coding; shows the planned figure only.",
           "SIMULATED DATA with invented parameters (seed 20261001). Not a result; do not cite.", top=0.80)


def fig5_demand(statements, episodes) -> None:
    """Fringe intensity vs age-adjusted views, within show."""
    fringe = Counter(row["episode_id"] for row in statements if row["fringe_advanced"] == "1")
    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    for show in ["jre", "doac"]:
        ids = [k for k, v in episodes.items() if v["show"] == show]
        x = [fringe[k] / (episodes[k]["duration"] / 3600) for k in ids]
        ages = [(SNAPSHOT_DATE - date.fromisoformat(
            f"{episodes[k]['upload_date'][:4]}-{episodes[k]['upload_date'][4:6]}-{episodes[k]['upload_date'][6:]}")).days
            for k in ids]
        # Age adjustment: residual of log views on log age within show, as % of the show's typical episode.
        lv, la = [math.log(episodes[k]["view_count"]) for k in ids], [math.log(a) for a in ages]
        ma, mv = sum(la) / len(la), sum(lv) / len(lv)
        slope = sum((a - ma) * (v - mv) for a, v in zip(la, lv)) / sum((a - ma) ** 2 for a in la)
        y = [100 * (math.exp(v - (mv + slope * (a - ma))) - 1) for a, v in zip(la, lv)]
        ax.scatter(x, y, s=70, color=SHOW_COLOR[show], edgecolor=SURFACE, linewidth=2,
                   label=SHOW_LABEL[show], zorder=2)
        for xi, yi, k in zip(x, y, ids):
            if abs(yi) > 60 or xi > 45:
                ax.annotate(short(episodes[k]["guest_name"]), (xi, yi), xytext=(6, 4),
                            textcoords="offset points", fontsize=8, color=MUTED)
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_xlabel("Fringe claims advanced per hour")
    ax.set_ylabel("Views vs. show's typical episode of same age (%)")
    ax.legend(frameon=False, loc="upper right")
    finish(fig, OUTPUT / "fig5_demand.png",
           "5 · Demand: do fringe-heavy episodes draw bigger audiences?",
           "YouTube views on 2026-10-01, adjusted for episode age within each show. n = 10 per show: descriptive only.",
           PROVISIONAL + " YouTube snapshot 20261001T205301Z.")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    statements, episodes = load()
    fig1_extent(statements, episodes)
    fig2_topics(statements)
    fig3_suppliers(statements, episodes)
    fig4_treatment_simulated()
    fig5_demand(statements, episodes)
    print(f"Wrote 5 figures to {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
