"""Mock-up of the 'politicians on podcasts' descriptives with PURELY SIMULATED data.

Shows what the figures/tables would look like ideally (Dupas et al. 2026 style).
Nothing here is real data. Run:
    /opt/anaconda3/envs/podcasts/bin/python temp_claude/politicians_mockup/simulate_and_plot.py
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import matplotlib as mpl
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
rng = np.random.default_rng(20261012)

# ---------------------------------------------------------------- palette
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
DEM, REP = "#2a78d6", "#e34948"          # categorical slots 1 and 8
POD, TRAD = "#eb6834", "#b4b3ad"          # podcast accent vs traditional neutral
mpl.rcParams.update({
    "font.family": "Helvetica", "font.size": 9, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "pdf.fonttype": 42, "savefig.dpi": 220,
})


def stamp(fig):
    fig.text(0.995, 0.995, "SIMULATED DATA - layout mock-up", ha="right", va="top",
             fontsize=7, color=MUTED, style="italic")


# ---------------------------------------------------------------- simulate
P = 120
pol = pd.DataFrame({
    "pol": np.arange(P),
    "party": np.where(np.arange(P) < 60, "D", "R"),
    "alpha": rng.normal(0, 1, P),           # politician's own style (FE)
})
# selection: more 'personal' politicians go on podcasts more often
pol["k_pod"] = 1 + rng.poisson(np.exp(0.4 + 0.35 * pol.alpha))
pol["k_trad"] = 3 + rng.poisson(3, P)

trad_venues = ["Press conference", "Sunday show", "Cable news interview", "Long-form TV (60 Minutes-style)"]
pod_venues = ["Podcast: co-partisan host", "Podcast: cross-partisan host", "Podcast: small show (placebo)"]
rows = []
for r in pol.itertuples():
    for _ in range(r.k_trad):
        rows.append((r.pol, r.party, r.alpha, 0, rng.choice(trad_venues, p=[.25, .3, .35, .1])))
    for _ in range(r.k_pod):
        rows.append((r.pol, r.party, r.alpha, 1, rng.choice(pod_venues, p=[.5, .3, .2])))
d = pd.DataFrame(rows, columns=["pol", "party", "alpha", "podcast", "venue"])
n = len(d)
rep = (d.party == "R").astype(float)
pod = d.podcast.astype(float)

d["length_min"] = np.where(pod == 1, rng.lognormal(np.log(95), .35, n), rng.lognormal(np.log(14), .4, n))
d["days_to_election"] = rng.integers(0, 730, n)
d["copartisan"] = (d.venue == "Podcast: co-partisan host").astype(float)
d["q_personal"] = np.clip(rng.normal(10 + 18 * pod, 6, n), 0, 80)  # % of host questions on personal topics

e = lambda s: rng.normal(0, s, n)
d["personal_share"] = 11 + 2.5 * d.alpha + 7 * pod + 0.35 * d.q_personal + e(4)
d["policy_specifics"] = np.clip(6.2 - 0.6 * d.alpha - 2.4 * pod + e(1.3), 0, None)
d["anti_media"] = np.clip(0.9 + 0.5 * rep + 0.15 * d.alpha + pod * (0.35 + 0.45 * rep) + 0.4 * d.copartisan + e(.45), 0, None)
d["contested_claims"] = np.clip(0.45 + 0.1 * d.alpha + 0.22 * pod + 0.08 * rep * pod + e(.25), 0, None)
d["hedging"] = np.clip(4.1 + 0.3 * d.alpha - 0.9 * pod + e(.9), 0, None)
d["laughter"] = np.clip(0.9 + 0.3 * d.alpha + 1.4 * pod + e(1.0), 0, None)
d["turn_len"] = np.clip(34 + 4 * d.alpha + 38 * pod + 0.08 * d.length_min + e(9), 4, None)
venue_rate = {"Press conference": 24, "Sunday show": 21, "Cable news interview": 17,
              "Long-form TV (60 Minutes-style)": 13, "Podcast: co-partisan host": 2.6,
              "Podcast: cross-partisan host": 5.8, "Podcast: small show (placebo)": 4.4}
d["challenges_hr"] = np.clip(d.venue.map(venue_rate) - 0.8 * d.alpha + e(3), 0.2, None)
d.to_csv(OUT / "simulated_appearances.csv", index=False)

MEASURES = [
    ("personal_share", "Personal stories & biography\n(% of speaking time)"),
    ("laughter", "Laughter\n(per hour)"),
    ("turn_len", "Uninterrupted turn length\n(seconds)"),
    ("anti_media", "Criticism of media & institutions\n(mentions per hour)"),
    ("contested_claims", "Against-consensus claims\n(per hour)"),
    ("hedging", "Hedging markers\n(per 1,000 words)"),
    ("policy_specifics", "Concrete policy specifics\n(per 1,000 words)"),
]
CONTROLS = "np.log(length_min) + days_to_election + q_personal"


def fe_fit(y, data, rhs="podcast + C(pol)"):
    m = smf.ols(f"{y} ~ {rhs}", data=data).fit(cov_type="cluster", cov_kwds={"groups": data.pol})
    return m.params["podcast"], m.bse["podcast"], m.pvalues["podcast"]


# ---------------------------------------------------------------- estimates (semielasticities)
res = []
for y, lab in MEASURES:
    for grp, sub in [("Pooled", d), ("Democrats", d[d.party == "D"]), ("Republicans", d[d.party == "R"])]:
        rhs = "podcast + C(pol) + np.log(length_min) + days_to_election"
        b, se, p = fe_fit(y, sub, rhs)
        base = sub.loc[sub.podcast == 0, y].mean()
        res.append(dict(measure=y, label=lab, group=grp, b=b, se=se, p=p, base=base,
                        pct=100 * b / base, lo90=100 * (b - 1.645 * se) / base, hi90=100 * (b + 1.645 * se) / base,
                        lo95=100 * (b - 1.96 * se) / base, hi95=100 * (b + 1.96 * se) / base))
res = pd.DataFrame(res)
res.to_csv(OUT / "estimates.csv", index=False)

# ---------------------------------------------------------------- Figure 1: register shift (Dupas Fig. 2 analogue)
groups = [("Pooled", INK), ("Democrats", DEM), ("Republicans", REP)]
fig, axes = plt.subplots(1, 3, figsize=(7.2, 4.4), sharey=True)
ypos = np.arange(len(MEASURES))[::-1]
for ax, (g, col) in zip(axes, groups):
    sub = res[res.group == g].set_index("measure").loc[[m for m, _ in MEASURES]]
    ax.axvline(0, color=MUTED, lw=0.8, ls=(0, (3, 3)))
    ax.hlines(ypos, sub.lo95, sub.hi95, color=col, lw=1, alpha=.45)
    ax.hlines(ypos, sub.lo90, sub.hi90, color=col, lw=2.2)
    ax.scatter(sub.pct, ypos, s=34, color=col, edgecolor="white", linewidth=1.2, zorder=3)
    for yy, v, lo, hi in zip(ypos, sub.pct, sub.lo95, sub.hi95):
        if v >= 0:
            ax.text(hi + 6, yy, f"{v:+.0f}%", ha="left", va="center", fontsize=7.5, color=INK2)
        else:
            ax.text(lo - 6, yy, f"{v:+.0f}%", ha="right", va="center", fontsize=7.5, color=INK2)
    ax.set_title(g, color=col if g != "Pooled" else INK)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(-130, 230)
axes[0].set_yticks(ypos, [lab for _, lab in MEASURES], fontsize=8)
axes[0].tick_params(axis="y", length=0)
fig.supxlabel("Podcast vs. the same politician in traditional venues (% of traditional-venue mean)",
              fontsize=8.5, color=INK2)
fig.suptitle("How the same politicians talk on podcasts", x=0.01, ha="left", fontsize=11, fontweight="bold")
fig.text(0.01, 0.925, "Politician FE, controls for appearance length and election timing; SEs clustered by politician. "
         "Thick = 90% CI, thin = 95% CI.", fontsize=7.5, color=INK2)
fig.tight_layout(rect=(0, 0.02, 1, 0.92))
stamp(fig)
fig.savefig(OUT / "fig1_register_shift.pdf"); fig.savefig(OUT / "fig1_register_shift.png")
plt.close(fig)

# ---------------------------------------------------------------- Figure 2: interviewer treatment (minutes between challenges)
order = trad_venues + ["Podcast: small show (placebo)", "Podcast: cross-partisan host", "Podcast: co-partisan host"]
boot = []
pols = d.pol.unique()
for _ in range(500):
    s = rng.choice(pols, len(pols))
    bd = pd.concat([d[d.pol == p] for p in s[:60]] + [d[d.pol == p] for p in s[60:]])
    boot.append(60 / bd.groupby("venue").challenges_hr.mean())
boot = pd.DataFrame(boot)
mins = 60 / d.groupby("venue").challenges_hr.mean()
fig, ax = plt.subplots(figsize=(7.2, 3.4))
yp = np.arange(len(order))[::-1]
for yy, v in zip(yp, order):
    col = POD if v.startswith("Podcast") else TRAD
    ax.barh(yy, mins[v], height=0.62, color=col, edgecolor="white", linewidth=2)
    lo, hi = boot[v].quantile([.025, .975])
    ax.hlines(yy, lo, hi, color=INK2, lw=1)
    ax.text(hi + 0.4, yy, f"every {mins[v]:.1f} min", va="center", fontsize=8, color=INK)
seminar = 84.41 / 35.08
ax.axvline(seminar, color=INK, lw=1, ls=(0, (2, 2)))
ax.text(seminar + 0.3, len(order) - 0.35, f"Economics job talk: one interruption every {seminar:.1f} min (Dupas et al. 2026, Table 1)",
        fontsize=7.5, color=INK, va="bottom")
ax.set_ylim(-0.6, len(order) + 0.25)
ax.set_yticks(yp, order, fontsize=8.5)
ax.tick_params(axis="y", length=0)
ax.set_xlabel("Minutes of politician speech between interviewer challenges (higher = less pushback)")
ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
ax.set_xlim(0, mins.max() * 1.35)
fig.suptitle("How often interviewers push back", x=0.01, ha="left", fontsize=11, fontweight="bold")
fig.text(0.01, 0.9, "Challenge = LLM-coded interjection that disputes, fact-checks or demands evidence. "
         "Whiskers: 95% CI, cluster bootstrap by politician.", fontsize=7.5, color=INK2)
fig.tight_layout(rect=(0, 0.02, 1, 0.88))
stamp(fig)
fig.savefig(OUT / "fig2_pushback.pdf"); fig.savefig(OUT / "fig2_pushback.png")
plt.close(fig)

# ---------------------------------------------------------------- Figure 3: specification ladder (Dupas Fig. 1 analogue)
ladder = [
    ("No controls", "podcast"),
    ("Politician FE", "podcast + C(pol)"),
    ("+ length, election timing", "podcast + C(pol) + np.log(length_min) + days_to_election"),
    ("+ question topics", "podcast + C(pol) + np.log(length_min) + days_to_election + q_personal"),
    ("+ co-partisan host", "podcast + C(pol) + np.log(length_min) + days_to_election + q_personal + copartisan"),
]
panels = [("personal_share", "Personal stories (% of speaking time)"),
          ("anti_media", "Criticism of media & institutions (per hour)")]
fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9), sharey=True)
yl = np.arange(len(ladder))[::-1]
ladder_out = {}
for ax, (y, title) in zip(axes, panels):
    est = [fe_fit(y, d, rhs) for _, rhs in ladder]
    ladder_out[y] = [dict(spec=s, b=b, se=se) for (s, _), (b, se, _) in zip(ladder, est)]
    for yy, (b, se, _) in zip(yl, est):
        ax.hlines(yy, b - 1.96 * se, b + 1.96 * se, color=POD, lw=1, alpha=.5)
        ax.hlines(yy, b - 1.645 * se, b + 1.645 * se, color=POD, lw=2.2)
        ax.scatter(b, yy, s=34, color=POD, edgecolor="white", linewidth=1.2, zorder=3)
        ax.text(b + 1.96 * se, yy, f"  {b:.2f}", ha="left", va="center", fontsize=7.5, color=INK2)
    ax.axvline(0, color=MUTED, lw=0.8, ls=(0, (3, 3)))
    ax.set_title(title, fontsize=9)
    ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
    lo, hi = ax.get_xlim(); ax.set_xlim(min(0, lo) - 0.05 * hi, hi * 1.15)
axes[0].set_yticks(yl, [s for s, _ in ladder], fontsize=8.5)
axes[0].tick_params(axis="y", length=0)
fig.supxlabel("Coefficient on Podcast (level units)", fontsize=8.5, color=INK2)
fig.suptitle("Sensitivity to controls", x=0.01, ha="left", fontsize=11, fontweight="bold")
fig.tight_layout(rect=(0, 0.02, 1, 0.93))
stamp(fig)
fig.savefig(OUT / "fig3_spec_ladder.pdf"); fig.savefig(OUT / "fig3_spec_ladder.png")
plt.close(fig)

# ---------------------------------------------------------------- Figure 4: appearances over time
q = pd.period_range("2019Q1", "2026Q3", freq="Q")
t = np.arange(len(q))
base = 3 + 0.9 * t
spike = 28 * np.exp(-0.5 * ((t - q.get_loc(pd.Period("2024Q4"))) / 1.0) ** 2) \
      + 8 * np.exp(-0.5 * ((t - q.get_loc(pd.Period("2020Q4"))) / 1.0) ** 2) \
      + 10 * np.exp(-0.5 * ((t - q.get_loc(pd.Period("2026Q3"))) / 0.8) ** 2)
dem = rng.poisson(0.45 * (base + spike)); repn = rng.poisson(0.55 * (base + spike))
fig, ax = plt.subplots(figsize=(7.2, 2.8))
ax.bar(t, dem, width=0.78, color=DEM, edgecolor="white", linewidth=1, label="Democrats")
ax.bar(t, repn, bottom=dem, width=0.78, color=REP, edgecolor="white", linewidth=1, label="Republicans")
for lab, per in [("2020 election", "2020Q4"), ("2022 midterms", "2022Q4"), ("2024 election", "2024Q4")]:
    x = q.get_loc(pd.Period(per))
    ax.text(x, (dem + repn)[max(0, x - 1):x + 2].max() + 1.5, lab, ha="center", fontsize=7.5, color=INK2)
ax.set_xticks(t[::4], [str(p.year) for p in q[::4]])
ax.set_ylabel("Appearances per quarter")
ax.grid(axis="y", color=GRID, lw=0.6); ax.set_axisbelow(True)
ax.legend(frameon=False, loc="upper left", fontsize=8)
ax.set_ylim(0, (dem + repn).max() * 1.18)
fig.suptitle("Politician appearances on the top 25 podcasts", x=0.01, ha="left", fontsize=11, fontweight="bold")
fig.tight_layout(rect=(0, 0.02, 1, 0.93))
stamp(fig)
fig.savefig(OUT / "fig4_appearances.pdf"); fig.savefig(OUT / "fig4_appearances.png")
plt.close(fig)

# ---------------------------------------------------------------- Table 1 (Dupas Table 2 style)
cols = [("personal_share", "Personal\nshare (\\%)"), ("policy_specifics", "Policy\nspecifics"),
        ("anti_media", "Media/inst.\ncriticism"), ("contested_claims", "Against-cons.\nclaims"),
        ("challenges_hr", "Host\nchallenges")]
cells = []
for y, _ in cols:
    b, se, p = fe_fit(y, d, "podcast + C(pol) + np.log(length_min) + days_to_election")
    cells.append((b, se, p, d.loc[d.podcast == 0, y].mean()))
BR = "\\\\"
head = " & ".join("\\shortstack{" + c.replace("\n", BR) + "}" for _, c in cols)
lines = [
    "\\begin{tabular}{l" + "c" * len(cols) + "}", "\\toprule",
    " & " + head + " \\\\", " & " + " & ".join(f"({i+1})" for i in range(len(cols))) + " \\\\", "\\midrule",
    "Podcast & " + " & ".join(f"{b:.3f}" for b, *_ in cells) + " \\\\",
    " & " + " & ".join(f"({se:.3f})" for _, se, *_ in cells) + " \\\\",
    " & " + " & ".join("\\{$<$0.001\\}" if p < .001 else f"\\{{{p:.3f}\\}}" for _, _, p, _ in cells) + " \\\\[3pt]",
    "\\emph{Controls} & & & & & \\\\",
    "Politician FE & " + " & ".join(["Yes"] * len(cols)) + " \\\\",
    "Appearance length & " + " & ".join(["Yes"] * len(cols)) + " \\\\",
    "Days to election & " + " & ".join(["Yes"] * len(cols)) + " \\\\[3pt]",
    "Mean (traditional venue) & " + " & ".join(f"{m:.2f}" for *_, m in cells) + " \\\\",
    "Politicians & " + " & ".join([str(d.pol.nunique())] * len(cols)) + " \\\\",
    "Appearances & " + " & ".join([str(len(d))] * len(cols)) + " \\\\",
    "\\bottomrule", "\\end{tabular}",
]
(OUT / "tab1_podcast_gap.tex").write_text("\n".join(lines) + "\n")

# ---------------------------------------------------------------- numbers for the headline sentences
pooled = res[res.group == "Pooled"].set_index("measure")
by = res.set_index(["group", "measure"])
headline = {
    "personal_pct": pooled.loc["personal_share", "pct"],
    "policy_pct": pooled.loc["policy_specifics", "pct"],
    "turn_pct": pooled.loc["turn_len", "pct"],
    "media_pct_D": by.loc[("Democrats", "anti_media"), "pct"],
    "media_pct_R": by.loc[("Republicans", "anti_media"), "pct"],
    "claims_pct": pooled.loc["contested_claims", "pct"],
    "mins_trad": float(60 / d[d.podcast == 0].challenges_hr.mean()),
    "mins_pod": float(60 / d[d.venue != "Podcast: small show (placebo)"].query("podcast == 1").challenges_hr.mean()),
    "mins_copart": float(mins["Podcast: co-partisan host"]),
    "n_pol": int(d.pol.nunique()), "n_app": int(len(d)), "n_pod": int(d.podcast.sum()),
    "ladder": ladder_out,
}
(OUT / "headline_numbers.json").write_text(json.dumps(headline, indent=2, default=float))
print(json.dumps({k: v for k, v in headline.items() if k != "ladder"}, indent=2, default=float))