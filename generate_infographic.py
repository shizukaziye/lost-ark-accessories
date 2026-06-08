#!/usr/bin/env python3
"""Generate a concise single-page HTML infographic.

Run: python3 generate_infographic.py > infographic.html
"""

import html
import sys
from accessory_value import (
    EFFECTS, PRIMARY, FLAT, TIERS, TIER_BASE_PROB, LINE_DAMAGE,
    MAIN_STAT_RANGE, MAIN_STAT_DAMAGE_PER_UNIT, CUT_COST, DEMAND_MAX,
    SALE_TAX, BLUE_CRYSTAL_GOLD, PRICE_ANCHORS, get_pricing,
    enumerate_distribution, STRATEGIES, strategy3, strategy1,
    expected_gold, prob_reach_3,
    primary_tier_grid, HIGHLIGHTED_BUCKETS,
    ev_of_cutting, value_at, normalized_three_line_distribution,
    line_damage, line_logdmg, main_stat_logdmg, baseline_logdmg,
    get_strategy_distribution, strategy_metrics,
    optimal_value, optimal_should_cut, optimal_distribution,
)


def fmt_pct(p, digits=3):
    return f"{p * 100:.{digits}f}%"


def fmt_pct_smart(p):
    if p == 0:
        return "0%"
    if p < 0.0001:
        return f"{p * 100:.4f}%"
    if p < 0.01:
        return f"{p * 100:.3f}%"
    return f"{p * 100:.2f}%"


def fmt_gold(g):
    """Compact gold formatter:
       - magnitudes under 10,000 (including negatives): full digits with commas
       - 10k to <100k: "X.Xk" (one decimal)
       - 100k to <1M: "Xk" (integer)
       - >= 1M: "X.XXM"
    """
    if abs(g) < 10_000:
        return f"{g:,.0f}"
    if abs(g) < 100_000:
        return f"{g / 1_000:.1f}k"
    if abs(g) < 1_000_000:
        return f"{g / 1_000:.0f}k"
    return f"{g / 1_000_000:.2f}M"


def fmt_one_in(p):
    if p <= 0:
        return "&mdash;"
    n = 1 / p
    if n >= 1_000_000:
        return f"1 / {n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"1 / {n / 1_000:.1f}k"
    return f"1 / {n:.0f}"


def esc(s):
    return html.escape(str(s))


def tier_class(tier):
    return {
        "high": "th",
        "mid": "tm",
        "low": "tl",
        "none": "tn",
        "useless": "tu",
    }.get(tier, "")


def pair_html(pt1, pt2):
    return (f"<span class='{tier_class(pt1)}'>{esc(pt1)}</span>"
            f"<span class='sep'>/</span>"
            f"<span class='{tier_class(pt2)}'>{esc(pt2)}</span>")


ACC_DISPLAY = {"neck": "Necklace", "earring": "Earring", "ring": "Ring"}
ACC_PRIMARY_SHORT = {
    "neck": ("Outgoing", "Additional"),
    "earring": ("ATK%", "WPN%"),
    "ring": ("Crit Dmg", "Crit Rate"),
}


# ---------- catalog row generator ----------

TIER_RANK = {"high": 3, "mid": 2, "low": 1}


def catalog_rows_by_tier(acc_type):
    """For each (primary_pair, third_tier), aggregate probability and value.

    primary_pair is (p1_tier, p2_tier) where each tier is high/mid/low or
    'none' if that primary line did not roll. third_tier is the BEST flat tier
    (ATK+/WPN+) present among the non-primary lines, or 'useless' if none.
    Damage is aggregated in LOG space (probability-weighted), then valued
    above the baseline. This yields the 9 both-primary pairs plus the
    single-primary (high/none, none/high, ...) and no-primary (none/none)
    categories."""
    p1_name, p2_name = PRIMARY[acc_type]
    lo, hi = MAIN_STAT_RANGE[acc_type]
    mid_ms = (lo + hi) / 2
    line_dist = normalized_three_line_distribution(acc_type)
    cats = {}
    for line_set, line_prob in line_dist.items():
        tier_map = {e: t for e, t in line_set}
        pt1 = tier_map.get(p1_name, "none")
        pt2 = tier_map.get(p2_name, "none")
        # Best flat tier among the non-primary lines.
        flats = [t for e, t in line_set if e in FLAT]
        third_tier = max(flats, key=lambda t: TIER_RANK[t]) if flats else "useless"
        key = (pt1, pt2, third_tier)
        line_d = sum(line_logdmg(e, t) for e, t in line_set)
        slot = cats.setdefault(key, [0.0, 0.0])
        slot[0] += line_prob
        slot[1] += line_prob * line_d
    rows = []
    for (pt1, pt2, third_tier), (total_p, weighted_d) in cats.items():
        if total_p < 1e-15:
            continue
        d_line = weighted_d / total_p
        d_min = main_stat_logdmg(lo) + d_line
        d_mid = main_stat_logdmg(mid_ms) + d_line
        d_max = main_stat_logdmg(hi) + d_line
        rows.append({
            "pair": (pt1, pt2),
            "third_tier": third_tier,
            "prob": total_p,
            "d_min": d_min,
            "d_mid": d_mid,
            "d_max": d_max,
            "v_min": value_at(acc_type, d_min),
            "v_mid": value_at(acc_type, d_mid),
            "v_max": value_at(acc_type, d_max),
        })
    return rows


# ---------- output buffer ----------

_buf = []


def w(s=""):
    _buf.append(s)


# ---------- styles ----------

CSS = """
:root {
  --bg: #0d1017;
  --panel: #161a24;
  --panel-2: #1b2030;
  --border: #2a3142;
  --text: #e7e9ee;
  --dim: #97a0b4;
  --accent: #66c7ff;
  --high: #ffb86b;
  --mid: #c78cff;
  --low: #6ad4ff;
  --none: #4f5666;
  --useless: #707788;
  --good: #6ee7a8;
  --bad: #ff7f7f;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text); }
body {
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI",
        "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 28px 20px 60px; }

/* header */
header { margin-bottom: 22px; }
h1 {
  font-size: 26px; line-height: 1.15; margin: 0 0 4px;
  letter-spacing: -0.02em;
}
header .tag { color: var(--dim); font-size: 13px; }

/* sections */
h2 {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em;
  color: var(--accent); margin: 24px 0 10px; font-weight: 700;
}

/* panel/grid */
.panel {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px;
}
.grid { display: grid; gap: 14px; }
.grid.cols-3 { grid-template-columns: repeat(3, 1fr); }
.grid.cols-2 { grid-template-columns: repeat(2, 1fr); }
.panel h3 {
  font-size: 12px; margin: 0 0 10px; color: var(--dim);
  text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600;
}
.panel .big {
  font-size: 22px; font-weight: 700; color: var(--text);
  letter-spacing: -0.01em;
}
.panel .row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 4px 0; border-top: 1px solid var(--border);
}
.panel .row:first-of-type { border-top: none; }
.panel .row .k { color: var(--dim); font-size: 12px; }
.panel .row .v { font-variant-numeric: tabular-nums; font-weight: 600; }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td {
  padding: 6px 10px; text-align: left;
  border-bottom: 1px solid var(--border);
}
th {
  color: var(--dim); font-size: 10px; text-transform: uppercase;
  letter-spacing: 0.06em; font-weight: 600;
}
tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.c, th.c { text-align: center; }

/* tier colors */
.th { color: var(--high); font-weight: 700; }
.tm { color: var(--mid);  font-weight: 700; }
.tl { color: var(--low);  font-weight: 700; }
.tn { color: var(--none); }
.tu { color: var(--useless); font-style: italic; }
.sep { color: var(--dim); margin: 0 2px; }

/* code / formula */
code, .mono {
  font-family: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  font-size: 12px;
}
.formula {
  background: var(--panel-2); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 14px;
  font-family: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  font-size: 13px; overflow-x: auto;
}

/* probability grid (4x4) */
table.grid4 { font-size: 13px; }
table.grid4 th, table.grid4 td { text-align: center; padding: 5px 8px; }
table.grid4 th:first-child, table.grid4 td:first-child {
  text-align: left; color: var(--dim); font-weight: 600;
}

/* catalog dropdown */
.catalog-controls {
  display: flex; align-items: center; gap: 10px;
  margin: 10px 0 12px;
}
.catalog-controls label {
  color: var(--dim); font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.08em;
}
select {
  background: var(--panel-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 6px 10px; font-size: 13px; font-family: inherit;
  cursor: pointer;
}
select:focus { outline: 1px solid var(--accent); }

/* hide rows not matching selected tier */
table.cat[data-tier="useless"] tr[data-tier]:not([data-tier="useless"]) { display: none; }
table.cat[data-tier="low"]     tr[data-tier]:not([data-tier="low"])     { display: none; }
table.cat[data-tier="mid"]     tr[data-tier]:not([data-tier="mid"])     { display: none; }
table.cat[data-tier="high"]    tr[data-tier]:not([data-tier="high"])    { display: none; }

footer {
  margin-top: 28px; padding-top: 14px;
  border-top: 1px solid var(--border);
  color: var(--dim); font-size: 11px; line-height: 1.6;
}

@media (max-width: 800px) {
  .grid.cols-3 { grid-template-columns: 1fr; }
  .grid.cols-2 { grid-template-columns: 1fr; }
  h1 { font-size: 22px; }
  th, td { padding: 5px 6px; }
}
"""

# ---------- HTML build ----------

w("<!DOCTYPE html>")
w("<html lang='en'><head>")
w("<meta charset='utf-8'>")
w("<meta name='viewport' content='width=device-width, initial-scale=1'>")
w("<title>Lost Ark Accessory Value &mdash; Infographic</title>")
w(f"<style>{CSS}</style>")
w("</head><body><div class='wrap'>")

# ---------- header ----------

w("<header>")
w("<h1>Lost Ark Accessories: Odds, Damage, Value</h1>")
w("<div class='tag'>Closed-form model with convex demand calibrated "
  "per accessory. Optimal cutting strategy via Bellman dynamic programming.</div>")
w("</header>")

# ---------- top stats grid ----------

w("<h2>Mechanics</h2>")
w("<div class='grid cols-3'>")

# Quick facts
w("<div class='panel'><h3>Cutting</h3>")
w(f"<div class='row'><span class='k'>Cost per cut</span>"
  f"<span class='v'>{CUT_COST:,}g</span></div>")
w(f"<div class='row'><span class='k'>Max cuts</span>"
  f"<span class='v'>3</span></div>")
w(f"<div class='row'><span class='k'>Max cost per attempt</span>"
  f"<span class='v'>{CUT_COST * 3:,}g</span></div>")
w(f"<div class='row'><span class='k'>Effects per pool</span>"
  f"<span class='v'>10</span></div>")
w("</div>")

# Tier probabilities
w("<div class='panel'><h3>Per-effect tier odds</h3>")
for tier in TIERS:
    w(f"<div class='row'><span class='k {tier_class(tier)}'>{tier}</span>"
      f"<span class='v'>{fmt_pct(TIER_BASE_PROB[tier], 1)}</span></div>")
w(f"<div class='row'><span class='k'>any tier</span>"
  f"<span class='v'>10.0%</span></div>")
w("</div>")

# Main stat ranges
w("<div class='panel'><h3>Main stat ranges</h3>")
for acc_type in EFFECTS:
    lo, hi = MAIN_STAT_RANGE[acc_type]
    w(f"<div class='row'><span class='k'>{ACC_DISPLAY[acc_type]}</span>"
      f"<span class='v'>{lo:,}&ndash;{hi:,}</span></div>")
w(f"<div class='row'><span class='k'>per 1000 main stat</span>"
  f"<span class='v'>{MAIN_STAT_DAMAGE_PER_UNIT * 1000:.3f}%</span></div>")
w("</div>")

w("</div>")  # /grid

# ---------- damage table + strategy table ----------

w("<h2>Damage per line tier (multiplicative)</h2>")
w("<div class='panel' style='margin-bottom:14px'>")
w("<div style='font-size:13px'>"
  "Lines <strong>multiply</strong>, not add: 2% &times; 1.2% &times; 0.17% = "
  "<code>1.02&times;1.012&times;1.0017 = +3.41%</code>. Pricing runs on the "
  "log-multiplier <code>D = 100&middot;&Sigma; ln(1 + p<sub>i</sub>/100)</code> "
  "(+ main stat, 0.060% per 1,000 pts) so damage is additive.</div>")
w("</div>")

w("<div class='grid cols-2'>")

# Damage table
w("<div class='panel'>")
w("<table><thead><tr><th>Effect</th>"
  "<th class='num tl'>Low</th><th class='num tm'>Mid</th>"
  "<th class='num th'>High</th></tr></thead><tbody>")
ordered = [
    ("Outgoing Damage %", "neck"),
    ("Additional Damage %", "neck"),
    ("Attack Power %", "earring"),
    ("Weapon Attack Power %", "earring"),
    ("Crit Damage %", "ring"),
    ("Crit Rate %", "ring"),
    ("Attack Power+", "all"),
    ("Weapon Attack Power+", "all"),
]
for effect, slot in ordered:
    row = LINE_DAMAGE[effect]
    w(f"<tr><td>{esc(effect)} <span class='mono' style='color:var(--dim)'>"
      f"({slot})</span></td>"
      f"<td class='num tl'>{row['low']:.3f}%</td>"
      f"<td class='num tm'>{row['mid']:.3f}%</td>"
      f"<td class='num th'>{row['high']:.3f}%</td></tr>")
w("</tbody></table>")
w("</div>")

# Strategy table — includes EV at mid main stat for each accessory type.
w("<div class='panel'>")
w("<h3>Strategy comparison &mdash; EV at mid main stat</h3>")
w("<table><thead><tr><th>Strategy</th><th class='num'>E[gold]</th>"
  "<th class='num'>P(3 cuts)</th>"
  "<th class='num'>EV neck</th>"
  "<th class='num'>EV earring</th>"
  "<th class='num'>EV ring</th></tr></thead><tbody>")
strategy_names = {
    1: "1 &mdash; Conservative",
    2: "2 &mdash; Optimal (DP)",
    3: "3 &mdash; Full cut",
}
for s_id in (1, 2, 3):
    # use mid main stat for the representative; optimal needs a main stat anyway
    metrics_by_type = {
        acc: strategy_metrics(s_id, acc,
                              (MAIN_STAT_RANGE[acc][0] + MAIN_STAT_RANGE[acc][1]) // 2)
        for acc in EFFECTS
    }
    rep = metrics_by_type["neck"]  # e_gold and p_3 vary tiny across types under S2; use neck
    w(f"<tr><td>{strategy_names[s_id]}</td>"
      f"<td class='num'>{rep['e_gold']:,.0f}</td>"
      f"<td class='num'>{fmt_pct(rep['p_3'], 1)}</td>"
      f"<td class='num'>{fmt_gold(metrics_by_type['neck']['ev'])}</td>"
      f"<td class='num'>{fmt_gold(metrics_by_type['earring']['ev'])}</td>"
      f"<td class='num'>{fmt_gold(metrics_by_type['ring']['ev'])}</td></tr>")
w("</tbody></table>")
w("<div style='color:var(--dim); font-size:11px; margin-top:6px'>"
  "EV = E[value of accessory above baseline] &minus; E[gold spent on cuts]. "
  "Partial cuts (S1/S2 stops) valued at 0g. After subtracting the baseline, "
  "<strong>blind full-cutting (S3) loses gold</strong> on earrings/rings "
  "&mdash; the optimal policy (S2) stops on bad cuts and is the only "
  "reliably positive-EV play.</div>")
w("</div>")
w("</div>")  # /grid

# ---------- primary tier grid (strategy 3) ----------

w("<h2>Strategy 3 primary tier pair distribution (full cut)</h2>")
w("<div class='panel'>")
dist_s3 = enumerate_distribution("neck", strategy3)
grid_s3 = primary_tier_grid(dist_s3, "neck")
labels = ("high", "mid", "low", "none")
w("<table class='grid4'><thead><tr><th></th>")
for c in labels:
    w(f"<th class='{tier_class(c)}'>{esc(c)}</th>")
w("</tr></thead><tbody>")
for r in labels:
    w(f"<tr><td class='{tier_class(r)}'>{esc(r)}</td>")
    for c in labels:
        p = grid_s3.get((r, c), 0.0)
        cls = ""
        if r in ("high", "mid") and c in ("high", "mid"):
            cls = "th" if r == "high" and c == "high" else ""
        w(f"<td class='{cls}'>{fmt_pct(p, 3)}</td>")
    w("</tr>")
w("</tbody></table>")
_neck_nodist = primary_tier_grid(enumerate_distribution("neck", strategy3), "neck")
_p_none = sum(p for (r, c), p in _neck_nodist.items() if r == "none" and c == "none")
_p_hh = _neck_nodist.get(("high", "high"), 0.0)
w("<div style='color:var(--dim); font-size:12px; margin-top:8px'>"
  f"<strong>{_p_none*100:.0f}%</strong> of full-cut accessories roll "
  f"<em>neither</em> primary line. Only <strong>{_p_hh*100:.3f}%</strong> "
  f"are high/high (&approx;1 / {1/_p_hh:,.0f} cuts).</div>")
w("</div>")

# ---------- pricing model (detailed) ----------

w("<h2>Pricing methodology</h2>")
w("<div class='panel'>")
w("<div class='formula'>"
  "value(D) = max(0,  &int;<sub>baseline</sub><sup>D</sup> "
  "min(10M, p<sub>min</sub>(1&minus;F(x))<sup>&minus;1/a</sup>) dx "
  "&minus; 60k pheon tax)"
  "</div>")
w("<ul style='font-size:13px; margin:10px 0 0; padding-left:18px'>")
w("<li><strong>Supply <code>F(D)</code>:</strong> share of full cuts scoring "
  "&le; <code>D</code> (all 19,440 outcomes &times; 3 main-stat levels). Rare "
  "good cuts sit near F = 1.</li>")
w("<li><strong>Demand:</strong> the buyer at rarity <code>F</code> pays "
  "<code>p<sub>min</sub>(1&minus;F)<sup>&minus;1/a</sup></code> per unit "
  "log-damage &mdash; the 80/20 Pareto curve, capped at 10M. It only spikes "
  "as F&rarr;1, so high/high earns its premium from <em>rarity</em>, not its "
  "small damage edge.</li>")
w("<li><strong>Baseline:</strong> integrate only above a "
  "{high primary + 2 low flats} piece (worth 0). You pay for damage beyond a "
  "throwaway one-line drop.</li>")
w("<li><strong>Pheon tax:</strong> see below &mdash; flat 60k off the gross.</li>")
w("</ul>")
w("<table style='margin-top:10px'><thead><tr><th>Accessory</th>"
  "<th class='num'>Pareto a</th>"
  "<th class='num'>p<sub>min</sub> /unit</th>"
  "<th class='num'>h/m</th>"
  "<th class='num'>h/h</th>"
  "</tr></thead><tbody>")
for acc in EFFECTS:
    a_i, pmin_i = get_pricing(acc)
    w(f"<tr><td>{ACC_DISPLAY[acc]}</td>"
      f"<td class='num'>{a_i:.3f}</td>"
      f"<td class='num'>{fmt_gold(pmin_i)}</td>"
      f"<td class='num'>{fmt_gold(PRICE_ANCHORS[acc]['hm'])}</td>"
      f"<td class='num'>{fmt_gold(PRICE_ANCHORS[acc]['hh'])}</td></tr>")
w("</tbody></table>")
w("<div style='color:var(--dim); font-size:11px; margin-top:6px'>"
  "I hand-picked the two anchor prices per slot &mdash; the going rate for the "
  "<strong>lowest-roll high/mid</strong> and <strong>lowest-roll high/high</strong> "
  "I saw on the market &mdash; and solve (a, p<sub>min</sub>) so the formula "
  "reproduces them exactly. Everything else is extrapolated from those two "
  "points.</div>")
w("</div>")

# Pheon tax explainer
w("<div class='panel' style='margin-top:14px'>")
w(f"<div style='font-size:13px'><strong>The 60k &ldquo;pheon tax.&rdquo;</strong> "
  f"Buying an accessory on the market costs <strong>Pheons</strong>, a bound "
  f"currency you get from <strong>Blue Crystals</strong>. At an assumed Blue "
  f"Crystal price of <strong>~{BLUE_CRYSTAL_GOLD:,}g</strong> (per 95-crystal "
  f"pack), the Pheons for one relic accessory run about "
  f"<strong>60,000g</strong>. The buyer pays it on top of the listing, so the "
  f"seller nets 60k less &mdash; we bake it in as a flat tax.</div>")
w("</div>")


# ---------- optimal policy ----------

w("<h2>Optimal cutting policy (Strategy 2)</h2>")
w("<div class='panel'>")
w("<div style='font-size:15px; font-weight:600; color:var(--good); margin-bottom:8px'>"
  "The simple rule: after cut 1, keep cutting only if you hit a primary "
  "mid-or-better, or a flat high. Otherwise stop.</div>")
w("<div style='color:var(--dim); font-size:12px; margin-bottom:8px'>"
  "Bellman DP over every state: cut if expected gain beats 1,200g. Bad "
  "openings rarely earn back two more cuts, so the policy abandons them. The "
  "threshold loosens with main stat (stricter at min, looser at max). Table: "
  "mid main stat.</div>")
w("<div class='grid cols-3' style='gap:14px'>")
for acc in EFFECTS:
    lo, hi = MAIN_STAT_RANGE[acc]
    mid_ms = (lo + hi) // 2
    p1_name, p2_name = PRIMARY[acc]

    # Group cut-1 outcomes by category and check decision.
    def category(eff, tier):
        if eff in (p1_name, p2_name):
            return f"primary {tier}"
        if eff in FLAT:
            return f"flat {tier}"
        return f"useless {tier}"

    cat_decisions = {}  # cat -> set of decisions ("cut" / "stop")
    for eff in EFFECTS[acc]:
        for tier in TIERS:
            state = ((eff, tier),)
            decision = "cut" if optimal_should_cut(acc, state, mid_ms) else "stop"
            cat_decisions.setdefault(category(eff, tier), set()).add(decision)

    # Also compute cut-2 rule: count over 30*27 states how often optimal cuts again.
    n_cut2_cut = 0
    n_cut2_total = 0
    for e1 in EFFECTS[acc]:
        for t1 in TIERS:
            state1 = ((e1, t1),)
            if not optimal_should_cut(acc, state1, mid_ms):
                continue
            for e2 in EFFECTS[acc]:
                if e2 == e1:
                    continue
                for t2 in TIERS:
                    state2 = state1 + ((e2, t2),)
                    n_cut2_total += 1
                    if optimal_should_cut(acc, state2, mid_ms):
                        n_cut2_cut += 1
    cut2_share = n_cut2_cut / n_cut2_total if n_cut2_total else 0

    w("<div>")
    w(f"<div style='font-weight:600; margin-bottom:6px'>{ACC_DISPLAY[acc]}</div>")
    w("<table class='compact'><thead><tr><th>After cut 1 was&hellip;</th>"
      "<th class='c'>cut?</th></tr></thead><tbody>")
    order = ["primary high", "primary mid", "primary low",
             "flat high", "flat mid", "flat low",
             "useless high", "useless mid", "useless low"]
    for cat in order:
        decs = cat_decisions.get(cat, set())
        if not decs:
            continue
        if decs == {"cut"}:
            disp = "<span class='th'>cut</span>"
        elif decs == {"stop"}:
            disp = "<span class='tu'>stop</span>"
        else:
            disp = "<span class='tm'>mixed</span>"
        # category label color
        if cat.startswith("primary"):
            cls = "th"
        elif cat.startswith("flat"):
            cls = "tm"
        else:
            cls = "tu"
        w(f"<tr><td class='{cls}'>{cat}</td><td class='c'>{disp}</td></tr>")
    w("</tbody></table>")
    w(f"<div style='color:var(--dim); font-size:11px; margin-top:6px'>"
      f"After cut 2: continue in {cut2_share:.0%} of post-cut-2 states "
      f"(of those reached).</div>")
    w("</div>")
w("</div>")
w("</div>")

# ---------- EV of cutting naked ----------

w("<h2>EV of cutting a naked accessory, by main stat</h2>")
w("<div class='grid cols-3'>")
for acc_type in EFFECTS:
    lo, hi = MAIN_STAT_RANGE[acc_type]
    mid_ms = (lo + hi) // 2
    w("<div class='panel'>")
    w(f"<h3>{ACC_DISPLAY[acc_type]}</h3>")
    w("<table><thead><tr><th>Main stat</th>"
      "<th class='num'>S1</th><th class='num'>Optimal</th>"
      "<th class='num'>S3</th></tr></thead><tbody>")
    for label, ms in [("min", lo), ("mid", mid_ms), ("max", hi)]:
        cells = [f"{label} ({ms:,})"]
        for s_id in (1, 2, 3):
            ev = ev_of_cutting(acc_type, ms, s_id)
            cells.append(f"<td class='num'>{fmt_gold(ev)}</td>")
        w(f"<tr><td>{cells[0]}</td>{''.join(cells[1:])}</tr>")
    w("</tbody></table>")
    w("</div>")
w("</div>")
w("<div style='color:var(--dim); font-size:12px; margin-top:6px'>"
  "After the 60k sale tax, the margins are brutal. <strong>Blind full-cut "
  "(S3) loses gold everywhere except a max-main-stat neck.</strong> Even the "
  "optimal policy yields ~0 on earrings/rings at low/mid main stat &mdash; the "
  "best move there is often <em>not to cut a naked drop at all</em>. Cutting "
  "only reliably pays on high-main-stat necklaces or when you open with a "
  "primary mid+. Per attempt, partial cuts valued at 0g.</div>")

# ---------- accessory catalog with dropdown ----------

w("<h2>Accessory catalog</h2>")
w("<div class='catalog-controls'>")
w("<label for='tier-select'>3rd line:</label>")
w("<select id='tier-select' onchange='setTier(this.value)'>")
w("<option value='useless' selected>Useless (any 0%-damage 3rd line)</option>")
w("<option value='low'>Flat low (ATK+ or WPN+ low)</option>")
w("<option value='mid'>Flat mid</option>")
w("<option value='high'>Flat high</option>")
w("</select>")
w("<span style='color:var(--dim); font-size:12px'>"
  "mid/mid, high/low, low/high and better. Weaker pairs net ~0 after tax."
  "</span>")
w("</div>")

# Only the worthwhile pairs: mid/mid, high/low, low/high and above.
CATALOG_PAIRS = {
    ("high", "high"), ("high", "mid"), ("mid", "high"),
    ("high", "low"), ("low", "high"), ("mid", "mid"),
}

for acc_type in EFFECTS:
    rows = [r for r in catalog_rows_by_tier(acc_type)
            if r["pair"] in CATALOG_PAIRS]
    rows.sort(key=lambda r: (r["third_tier"], -r["v_mid"]))
    lo, hi = MAIN_STAT_RANGE[acc_type]
    mid_ms = (lo + hi) // 2
    p1s, p2s = ACC_PRIMARY_SHORT[acc_type]
    w("<div class='panel' style='margin-bottom:12px'>")
    w(f"<h3>{ACC_DISPLAY[acc_type]} "
      f"<span style='color:var(--dim); font-weight:400; "
      f"text-transform:none; letter-spacing:0'>({p1s} / {p2s}) &mdash; "
      f"main stat {lo:,} / {mid_ms:,} / {hi:,}</span></h3>")
    w("<table class='cat' data-tier='useless'><thead><tr>"
      "<th>Primary</th>"
      "<th class='num'>P</th>"
      "<th class='num'>Dmg min</th>"
      "<th class='num'>Dmg mid</th>"
      "<th class='num'>Dmg max</th>"
      "<th class='num'>Gold min</th>"
      "<th class='num'>Gold mid</th>"
      "<th class='num'>Gold max</th>"
      "</tr></thead><tbody>")
    for r in rows:
        pt1, pt2 = r["pair"]
        w(f"<tr data-tier='{r['third_tier']}'>"
          f"<td>{pair_html(pt1, pt2)}</td>"
          f"<td class='num'>{fmt_pct_smart(r['prob'])}</td>"
          f"<td class='num'>{r['d_min']:.2f}%</td>"
          f"<td class='num'>{r['d_mid']:.2f}%</td>"
          f"<td class='num'>{r['d_max']:.2f}%</td>"
          f"<td class='num'>{fmt_gold(r['v_min'])}</td>"
          f"<td class='num'>{fmt_gold(r['v_mid'])}</td>"
          f"<td class='num'>{fmt_gold(r['v_max'])}</td>"
          "</tr>")
    w("</tbody></table>")
    w("</div>")

# JS for dropdown
w("<script>")
w("function setTier(t){")
w("  document.querySelectorAll('table.cat').forEach(function(el){")
w("    el.dataset.tier = t;")
w("  });")
w("}")
w("</script>")

# ---------- footer ----------

w("<footer>")
w("Model: closed-form enumeration of all 3-cut outcomes (30 &times; 27 "
  "&times; 24 = 19,440 ordered triples). Damage scored in log-multiplier "
  "space. Per-accessory Pareto demand (10M gold/unit ceiling) fit to two "
  "anchor prices each, valued above a zero-baseline accessory. Supply uses "
  "3 equally-likely main-stat levels. Optimal strategy via Bellman DP with "
  "memoization; partial-cut accessories valued at 0g. Probability data from "
  "the official Korean drop-rate page; damage values from community testing "
  "(corrections: flat mid 0.082%/0.085%; ATK% low/mid 0.40%/0.95%). Junk "
  "lines (Max HP, debuff duration, etc.) treated as 0% damage. "
  "Reproducible: <code>accessory_value.py verify</code> (all checks).")
w("</footer>")

w("</div></body></html>")

sys.stdout.write("\n".join(_buf))
