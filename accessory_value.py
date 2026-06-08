#!/usr/bin/env python3
"""Lost Ark accessory cutting value calculator.

Computes:
- Expected gold cost and outcome distribution for three cutting strategies.
- Estimated market value of a finished accessory using a linear demand curve
  whose supply distribution is "strategy 3" (always cut to completion).

See ./README.md for usage examples.
"""

import argparse
import bisect
import math
import sys

# ---------- constants ----------

CUT_COST = 1200            # gold per cut

# "Pheon tax": buying an accessory on the market costs Pheons, a bound currency
# acquired with Blue Crystals. At an assumed Blue Crystal price of ~19,100 gold
# (per 95-crystal pack), the Pheons for one relic accessory come to ~60,000
# gold. The buyer pays it on top of the listing, so the seller effectively nets
# 60k less; we bake it in as a flat tax.
BLUE_CRYSTAL_GOLD = 19_100
SALE_TAX = 60_000

# Pareto-principle demand pricing per accessory type, on a LOG-DAMAGE axis.
#
# Damage is multiplicative: a line that reads "2%" multiplies your damage by
# 1.02, and lines stack as a product. To make damage additive (so it can be a
# supply/demand axis) we work in log space. The damage metric for an accessory
# is D = 100 * sum_i ln(1 + p_i/100) over all lines + main stat, i.e. 100 *
# ln(total multiplier). For small p this is approximately the old percent sum,
# so D stays in familiar "percent-ish" units, but it is multiplicatively exact.
#
# Baseline: value is measured only ABOVE a baseline accessory worth 0 gold,
# defined as {primary-1 high, Attack Power+ low, Weapon Attack Power+ low} at
# min main stat. Anything at or below that log-damage is worth 0; everything
# else is priced by the damage it adds on top of the baseline.
#
# Supply curve: the probability distribution over strategy-3 cut outcomes, with
# main stat at 3 equally-likely levels (min, med, max). F(D) is the cumulative
# probability of a cut producing <= D log-damage.
#
# Demand curve: marginal price per unit log-damage at supply percentile F
# follows a Pareto curve rising from a floor `pmin` (at F=0) toward a ceiling
# DEMAND_MAX (at F->1):
#     marginal_price(F) = min(DEMAND_MAX, pmin * (1 - F) ** (-1 / a))
# The Pareto index `a` near 1.16 is the literal 80/20 principle. Because the
# curve only blows up as F->1, the best-in-slot premium lands on high/high
# without inflating mid-tier outcomes. At fixed rarity, gold is linear in
# log-damage (the integrand is constant in D), honoring the multiplicative
# damage model.
#
# Value(D) = integral of marginal_price(F(x)) dx from D_baseline to D
#          = G(D) - G(D_baseline), floored at 0, where G is the cumulative
#            integral from the bottom of the supply curve.
#
# Each accessory type fits (a, pmin) to two anchors, given as NET prices (what
# the seller pockets after the Pheon tax). Gross = net + SALE_TAX.
#   - hm: cheapest high/mid (P1=high, P2=mid, useless 3rd, min main stat)
#   - hh: cheapest high/high (P1=high, P2=high, useless 3rd, min main stat)
DEMAND_MAX = 1_000_000_000  # effectively-uncapped demand ceiling (gold/unit log-dmg)

PRICE_ANCHORS = {
    "neck":    {"hm": 500_000, "hh": 2_700_000},
    "earring": {"hm": 400_000, "hh": 2_000_000},
    "ring":    {"hm": 400_000, "hh": 2_000_000},
}

_PRICING_CACHE = {}    # acc_type -> (a, pmin); filled lazily by _calibrate_for
_BASELINE_CACHE = {}   # acc_type -> baseline log-damage

# Effect pool per accessory type (10 effects each). Order matters only for
# display; primary lines are listed first.
EFFECTS = {
    "neck": [
        "Outgoing Damage %", "Additional Damage %",
        "Gauge Gain %", "Stigma %", "Max HP+",
        "Attack Power+", "Weapon Attack Power+",
        "Max MP+", "Debuff Duration %", "HP Recovery+",
    ],
    "earring": [
        "Attack Power %", "Weapon Attack Power %",
        "Healing %", "Shield %", "Max HP+",
        "Attack Power+", "Weapon Attack Power+",
        "Max MP+", "Debuff Duration %", "HP Recovery+",
    ],
    "ring": [
        "Crit Damage %", "Crit Rate %",
        "Ally Atk Buff %", "Ally Dmg Buff %", "Max HP+",
        "Attack Power+", "Weapon Attack Power+",
        "Max MP+", "Debuff Duration %", "HP Recovery+",
    ],
}

# Ordered pair: (primary_1, primary_2). Used as a canonical order for the
# (tier1, tier2) outcome grid.
PRIMARY = {
    "neck":    ("Outgoing Damage %", "Additional Damage %"),
    "earring": ("Attack Power %", "Weapon Attack Power %"),
    "ring":    ("Crit Damage %", "Crit Rate %"),
}

# Universally desirable "third line" set.
FLAT = frozenset({"Attack Power+", "Weapon Attack Power+"})

TIERS = ("low", "mid", "high")
TIER_BASE_PROB = {"low": 0.063, "mid": 0.030, "high": 0.007}
# Sum per effect = 0.10; ten effects total to 1.00.

# Marginal %damage per line tier, derived from the stat model (see README /
# the interactive site for the formulas). Computed at the baseline character:
#   base weapon power 250000, base main stat 750000, support mult 0.33,
#   base additional 35.85%, base atk power 11.2%, crit 90% / 280% (x1.12).
# These reproduce the previously observed values closely (Weapon% almost
# exactly). The interactive index.html recomputes them live from editable
# parameters; here they are the static defaults.
LINE_DAMAGE = {
    "Outgoing Damage %":     {"low": 0.550, "mid": 1.200, "high": 2.000},
    "Additional Damage %":   {"low": 0.699, "mid": 1.178, "high": 1.914},
    "Attack Power %":        {"low": 0.360, "mid": 0.854, "high": 1.394},
    "Weapon Attack Power %": {"low": 0.300, "mid": 0.674, "high": 1.119},
    "Crit Damage %":         {"low": 0.379, "mid": 0.828, "high": 1.380},
    "Crit Rate %":           {"low": 0.292, "mid": 0.694, "high": 1.133},
    "Attack Power+":         {"low": 0.031, "mid": 0.075, "high": 0.149},
    "Weapon Attack Power+":  {"low": 0.029, "mid": 0.072, "high": 0.144},
}
# Effects not in this map contribute 0 %damage.

MAIN_STAT_RANGE = {
    "neck":    (15178, 17857),
    "earring": (11806, 13889),
    "ring":    (10962, 12897),
}

MAIN_STAT_DAMAGE_PER_UNIT = 0.060 / 1000  # %damage per main stat point


# ---------- damage (multiplicative, measured in log space) ----------

def line_damage(effect, tier):
    """Raw percent damage increase of one line (additive %, pre-log)."""
    return LINE_DAMAGE.get(effect, {}).get(tier, 0.0)


def _log_units(pct):
    """Convert a single percent increase to additive log-damage units.

    100 * ln(1 + pct/100). Summing these over lines equals 100 * ln(product of
    multipliers), so log-damage is additive and multiplicatively exact. For
    small pct this is ~= pct, keeping the axis in familiar percent-ish units.
    """
    return 100.0 * math.log1p(pct / 100.0)


def line_logdmg(effect, tier):
    return _log_units(line_damage(effect, tier))


SUPPORT_MULT = 0.33      # support contributes sup_base * this to your atk power
BASE_MAIN_STAT = 750000  # character main stat before the accessory's roll


def main_stat_logdmg(acc_main_stat):
    """Log-damage from an accessory's main stat, via the sqrt attack-power
    model: base atk = sqrt(weapon_power * main_stat / 6), with a support that
    adds SUPPORT_MULT of the baseline base atk (and so dilutes your gains).
    Weapon power and the atk multipliers/flats cancel in this ratio."""
    ratio = ((1.0 + acc_main_stat / BASE_MAIN_STAT) ** 0.5 + SUPPORT_MULT) / (1.0 + SUPPORT_MULT)
    return 100.0 * math.log(ratio)


def accessory_damage(acc_type, main_stat, lines):
    """Total log-damage D of an accessory (lines + main stat)."""
    d = main_stat_logdmg(main_stat)
    for eff, tier in lines:
        d += line_logdmg(eff, tier)
    return d


def baseline_logdmg(acc_type):
    """Log-damage of the zero-value baseline: {primary-1 high, ATK+ low,
    WPN+ low} at min main stat. Value is only credited above this."""
    if acc_type not in _BASELINE_CACHE:
        p1, _ = PRIMARY[acc_type]
        lo, _ = MAIN_STAT_RANGE[acc_type]
        lines = [(p1, "high"), ("Attack Power+", "low"), ("Weapon Attack Power+", "low")]
        _BASELINE_CACHE[acc_type] = accessory_damage(acc_type, lo, lines)
    return _BASELINE_CACHE[acc_type]


# ---------- single-cut conditional probability ----------

def single_cut_outcomes(acc_type, excluded):
    """Yield (effect, tier, prob) for one cut given already-locked effects.

    With k effects excluded, each remaining effect's total mass is 0.10, so the
    pool sums to 0.10 * (10 - k) and tier probability renormalizes to
    TIER_BASE_PROB[tier] / (1 - 0.10 * k).
    """
    remaining_mass = 1.0 - 0.10 * len(excluded)
    for effect in EFFECTS[acc_type]:
        if effect in excluded:
            continue
        for tier in TIERS:
            yield effect, tier, TIER_BASE_PROB[tier] / remaining_mass


# ---------- strategies ----------

def _outcome_in(outcome, names, tiers):
    eff, tier = outcome
    return eff in names and tier in tiers


def strategy1(outcomes, primary, flat):
    """Cut once; finish all 3 cuts only if cut 1 is primary mid+."""
    if len(outcomes) == 0:
        return True
    if len(outcomes) >= 3:
        return False
    return _outcome_in(outcomes[0], primary, ("mid", "high"))


def strategy3(outcomes, primary, flat):
    """Always cut all 3."""
    return len(outcomes) < 3


# Strategy 2 is the *optimal* policy and lives in the DP block below; it's
# not a simple should_continue function. STRATEGIES holds only the rule-based
# strategies; optimal is dispatched separately by strategy id == 2.
STRATEGIES = {1: strategy1, 3: strategy3}


# ---------- optimal strategy (Bellman DP) ----------

import functools


@functools.lru_cache(maxsize=None)
def optimal_value(acc_type, state, main_stat):
    """Expected gold of optimally playing from this state.

    State = tuple of (effect, tier) cuts already made. Partial-cut accessories
    that we stop on are worth 0g (we abandon). At each non-terminal state we
    choose max(stop=0, cut_again=E[V(next)] - CUT_COST).
    """
    if len(state) == 3:
        return value_at(acc_type, accessory_damage(acc_type, main_stat, state))
    excluded = frozenset(e for e, _ in state)
    e_v_next = 0.0
    for effect, tier, p in single_cut_outcomes(acc_type, excluded):
        new_state = state + ((effect, tier),)
        e_v_next += p * optimal_value(acc_type, new_state, main_stat)
    return max(0.0, e_v_next - CUT_COST)


def optimal_should_cut(acc_type, state, main_stat):
    """Optimal decision at this state: True = cut again, False = stop now."""
    if len(state) == 3:
        return False
    excluded = frozenset(e for e, _ in state)
    e_v_next = 0.0
    for effect, tier, p in single_cut_outcomes(acc_type, excluded):
        new_state = state + ((effect, tier),)
        e_v_next += p * optimal_value(acc_type, new_state, main_stat)
    return e_v_next - CUT_COST > 0


def optimal_distribution(acc_type, main_stat):
    """dict[outcomes -> probability] under optimal play."""
    dist = {}

    def recurse(state, prob):
        if len(state) == 3 or not optimal_should_cut(acc_type, state, main_stat):
            dist[state] = dist.get(state, 0.0) + prob
            return
        excluded = frozenset(e for e, _ in state)
        for effect, tier, p in single_cut_outcomes(acc_type, excluded):
            recurse(state + ((effect, tier),), prob * p)

    recurse((), 1.0)
    return dist


def get_strategy_distribution(strategy_id, acc_type, main_stat):
    """Unified entry point for getting an outcome distribution by strategy id."""
    if strategy_id == 2:
        return optimal_distribution(acc_type, main_stat)
    return enumerate_distribution(acc_type, STRATEGIES[strategy_id])


def strategy_metrics(strategy_id, acc_type, main_stat):
    """Return {e_gold, e_value, ev, p_3, p_good}."""
    dist = get_strategy_distribution(strategy_id, acc_type, main_stat)
    e_gold = sum(prob * CUT_COST * len(o) for o, prob in dist.items())
    e_value = 0.0
    p_3 = 0.0
    for outcomes, prob in dist.items():
        if len(outcomes) == 3:
            p_3 += prob
            d = accessory_damage(acc_type, main_stat, outcomes)
            e_value += prob * value_at(acc_type, d)
    p_good = sum(
        prob for outcomes, prob in dist.items()
        if len(outcomes) == 3 and _good_outcome(outcomes, acc_type)
    )
    return {
        "e_gold": e_gold,
        "e_value": e_value,
        "ev": e_value - e_gold,
        "p_3": p_3,
        "p_good": p_good,
    }


def _good_outcome(outcomes, acc_type):
    """Outcome falls in HIGHLIGHTED_BUCKETS (both primaries present, decent tier pair)."""
    p1_name, p2_name = PRIMARY[acc_type]
    tier_map = {e: t for e, t in outcomes}
    t1 = tier_map.get(p1_name, "none")
    t2 = tier_map.get(p2_name, "none")
    return (t1, t2) in set(HIGHLIGHTED_BUCKETS)


# ---------- joint distribution ----------

def enumerate_distribution(acc_type, should_continue):
    """Depth-first enumeration of outcome distribution under a stopping rule.

    Returns dict[tuple-of-(effect, tier)] -> probability. Key length is the
    number of cuts performed (1, 2, or 3).
    """
    primary = set(PRIMARY[acc_type])
    dist = {}

    def recurse(outcomes, prob, excluded):
        if not should_continue(outcomes, primary, FLAT):
            key = tuple(outcomes)
            dist[key] = dist.get(key, 0.0) + prob
            return
        for effect, tier, p in single_cut_outcomes(acc_type, excluded):
            recurse(outcomes + [(effect, tier)], prob * p, excluded | {effect})

    recurse([], 1.0, set())
    return dist


def forward_distribution(acc_type, should_continue):
    """Step-by-step forward recursion. Functionally equivalent to
    enumerate_distribution; used as a closed-form cross-check."""
    primary = set(PRIMARY[acc_type])
    states = {(): 1.0}
    while True:
        nxt = {}
        any_continued = False
        for state, prob in states.items():
            if not should_continue(list(state), primary, FLAT):
                nxt[state] = nxt.get(state, 0.0) + prob
                continue
            any_continued = True
            excluded = {e for e, _ in state}
            for effect, tier, p in single_cut_outcomes(acc_type, excluded):
                ns = state + ((effect, tier),)
                nxt[ns] = nxt.get(ns, 0.0) + prob * p
        states = nxt
        if not any_continued:
            return states


# ---------- strategy analysis ----------

def expected_gold(dist):
    return sum(prob * CUT_COST * len(outcomes) for outcomes, prob in dist.items())


def prob_reach_3(dist):
    return sum(prob for outcomes, prob in dist.items() if len(outcomes) == 3)


def primary_tier_grid(dist, acc_type):
    """For 3-cut outcomes, joint probability of (tier_of_primary1, tier_of_primary2).

    Tier is 'none' if the primary line did not appear among the 3 cuts.
    """
    p1_name, p2_name = PRIMARY[acc_type]
    grid = {}
    for outcomes, prob in dist.items():
        if len(outcomes) != 3:
            continue
        line_map = {eff: tier for eff, tier in outcomes}
        t1 = line_map.get(p1_name, "none")
        t2 = line_map.get(p2_name, "none")
        grid[(t1, t2)] = grid.get((t1, t2), 0.0) + prob
    return grid


HIGHLIGHTED_BUCKETS = [
    ("high", "high"),
    ("high", "mid"),
    ("mid", "high"),
    ("mid", "mid"),
    ("high", "low"),
    ("low", "high"),
]


# ---------- strategy-3 CDF ----------

def normalized_three_line_distribution(acc_type):
    """Strategy-3 distribution over completed 3-line sets (order-invariant)."""
    dist = enumerate_distribution(acc_type, strategy3)
    out = {}
    for outcomes, prob in dist.items():
        key = tuple(sorted(outcomes))
        out[key] = out.get(key, 0.0) + prob
    return out


MAIN_STAT_LEVELS = 3  # supply uses 3 equally-likely main stat levels


def _main_stat_levels(acc_type):
    """The 3 main stat levels (min, med, max), each with probability 1/3."""
    lo, hi = MAIN_STAT_RANGE[acc_type]
    return [lo, (lo + hi) / 2.0, hi]


def _build_raw_supply(acc_type):
    """Return (damages, cum_probs): supply curve under strategy 3 with main
    stat at 3 equally-likely levels. cum_probs[i] = P(cut damage <= damages[i])."""
    levels = _main_stat_levels(acc_type)
    level_weight = 1.0 / len(levels)
    line_dist = normalized_three_line_distribution(acc_type)
    points = []
    for line_set, line_prob in line_dist.items():
        line_d = sum(line_logdmg(e, t) for e, t in line_set)
        for ms in levels:
            d = main_stat_logdmg(ms) + line_d
            points.append((d, line_prob * level_weight))
    points.sort()
    damages = []
    cum_probs = []
    running = 0.0
    for d, p in points:
        running += p
        damages.append(d)
        cum_probs.append(running)
    return damages, cum_probs


def _marginal_price(f, a, pmin):
    """Pareto demand: gold per 1% damage at supply percentile f."""
    if f >= 1.0:
        return DEMAND_MAX
    return min(DEMAND_MAX, pmin * (1.0 - f) ** (-1.0 / a))


def _integral_pareto(damages, cum_probs, a, pmin, d_target):
    """Integral of marginal_price(F(x)) from 0 to d_target, where F is the
    piecewise-constant supply CDF with jumps at `damages`."""
    total = 0.0
    n = len(damages)
    for i in range(n):
        if damages[i] >= d_target:
            break
        next_break = damages[i + 1] if i + 1 < n else d_target
        d_end = min(next_break, d_target)
        if d_end > damages[i]:
            total += _marginal_price(cum_probs[i], a, pmin) * (d_end - damages[i])
    return total


def _anchor_logdmg(acc_type):
    """Log-damage of the hm and hh anchors (useless 3rd, min main stat)."""
    lo, _ = MAIN_STAT_RANGE[acc_type]
    p1, p2 = PRIMARY[acc_type]
    d_hm = accessory_damage(acc_type, lo, [(p1, "high"), (p2, "mid")])
    d_hh = accessory_damage(acc_type, lo, [(p1, "high"), (p2, "high")])
    return d_hm, d_hh


def _calibrate_for(acc_type):
    """Fit (a, pmin) for one accessory type to its hm/hh anchors.

    Value is measured above the baseline: V(D) = pmin-scaled
    (I(D) - I(D_base)) where I is the unit-pmin cumulative integral. The
    hh:hm ratio is pmin-independent, so binary-search a on the ratio, then set
    pmin to hit the hm anchor.
    """
    damages, cum_probs = _build_raw_supply(acc_type)
    d_base = baseline_logdmg(acc_type)
    d_hm, d_hh = _anchor_logdmg(acc_type)
    # Anchors are NET; calibrate the gross integral to net + tax so that
    # value_at (gross - tax) reproduces the net anchors.
    v_hm = PRICE_ANCHORS[acc_type]["hm"] + SALE_TAX
    v_hh = PRICE_ANCHORS[acc_type]["hh"] + SALE_TAX
    target_ratio = v_hh / v_hm

    def above_base(a, d):  # unit-pmin value above baseline
        return (_integral_pareto(damages, cum_probs, a, 1.0, d)
                - _integral_pareto(damages, cum_probs, a, 1.0, d_base))

    # Larger a => gentler top => smaller hh/hm ratio (monotone decreasing).
    a_lo, a_hi = 0.30, 30.0
    for _ in range(200):
        mid = 0.5 * (a_lo + a_hi)
        i_hm = above_base(mid, d_hm)
        i_hh = above_base(mid, d_hh)
        if i_hm <= 0:
            a_lo = mid
            continue
        ratio = i_hh / i_hm
        if ratio > target_ratio:
            a_lo = mid  # too steep, increase a to soften
        else:
            a_hi = mid
    a = 0.5 * (a_lo + a_hi)
    i_hm = above_base(a, d_hm)
    pmin = v_hm / i_hm if i_hm > 0 else 0.0
    return a, pmin


def get_pricing(acc_type):
    """Lazily compute (a, pmin) for one accessory type."""
    if acc_type not in _PRICING_CACHE:
        _PRICING_CACHE[acc_type] = _calibrate_for(acc_type)
    return _PRICING_CACHE[acc_type]


def build_value_curve(acc_type):
    """Return (damages, cum_probs, cum_values) under strategy 3 with the
    Pareto demand model: marginal price per 1% damage at supply percentile F
    is min(DEMAND_MAX, pmin*(1-F)^(-1/a)); value is the integral.

    cum_values[j] = integral of marginal_price from damages[0] to damages[j],
    where the segment (damages[i-1], damages[i]] is priced at F = cum_probs[i-1].
    This matches _integral_pareto so calibration and lookup agree.
    """
    a, pmin = get_pricing(acc_type)
    damages, cum_probs = _build_raw_supply(acc_type)
    cum_values = [0.0]
    for i in range(1, len(damages)):
        seg = _marginal_price(cum_probs[i - 1], a, pmin) * (damages[i] - damages[i - 1])
        cum_values.append(cum_values[-1] + seg)
    return damages, cum_probs, cum_values


_curve_cache = {}


def get_curve(acc_type):
    if acc_type not in _curve_cache:
        _curve_cache[acc_type] = build_value_curve(acc_type)
    return _curve_cache[acc_type]


def cdf_at(acc_type, d):
    damages, cum_probs, _ = get_curve(acc_type)
    idx = bisect.bisect_right(damages, d) - 1
    return cum_probs[idx] if idx >= 0 else 0.0


def _cumulative_value(acc_type, d):
    """G(d): cumulative integral of marginal price from the bottom of the
    supply curve up to log-damage d (before baseline subtraction)."""
    a, pmin = get_pricing(acc_type)
    damages, cum_probs, cum_values = get_curve(acc_type)
    idx = bisect.bisect_right(damages, d) - 1
    if idx < 0:
        return 0.0
    extra = _marginal_price(cum_probs[idx], a, pmin) * (d - damages[idx])
    return cum_values[idx] + extra


def gross_value_at(acc_type, d):
    """Gross sale price (what a buyer pays / the AH lists): the integral of
    marginal price from the baseline up to log-damage d, floored at 0. This is
    what the demand curve and the price anchors are calibrated to."""
    if d <= 0:
        return 0.0
    base = _cumulative_value(acc_type, baseline_logdmg(acc_type))
    return max(0.0, _cumulative_value(acc_type, d) - base)


def value_at(acc_type, d):
    """Net value to the seller: gross sale price minus the per-accessory sale
    tax, floored at 0. An accessory whose gross price is below the tax nets 0
    (not worth selling)."""
    return max(0.0, gross_value_at(acc_type, d) - SALE_TAX)


def estimate_value(acc_type, main_stat, lines):
    d = accessory_damage(acc_type, main_stat, lines)
    f = cdf_at(acc_type, d)
    return d, f, value_at(acc_type, d)


# ---------- formatters ----------

def fmt_pct(p):
    return f"{p * 100:6.3f}%"


def fmt_gold(g):
    return f"{g:,.0f}g"


# ---------- CLI: strategy ----------

def cmd_strategy(args):
    acc_type = args.type
    print(f"=== {acc_type.upper()} ===")
    print(f"Primary lines:   {PRIMARY[acc_type]}")
    print(f"Good flat lines: {sorted(FLAT)}")
    print()
    summary = []
    lo, hi = MAIN_STAT_RANGE[acc_type]
    mid_ms_for_s2 = (lo + hi) // 2
    for s_id in (1, 2, 3):
        dist = get_strategy_distribution(s_id, acc_type, mid_ms_for_s2)
        eg = expected_gold(dist)
        p3 = prob_reach_3(dist)
        grid = primary_tier_grid(dist, acc_type)
        print(f"--- Strategy {s_id} ---")
        print(f"  E[gold per attempt]: {fmt_gold(eg)}")
        print(f"  P(reach 3 cuts):     {fmt_pct(p3)}")
        labels = ("high", "mid", "low", "none")
        print(f"  P(primary_1 row x primary_2 col):")
        print("       " + " ".join(f"{c:>7}" for c in labels))
        for r in labels:
            cells = " ".join(f"{fmt_pct(grid.get((r, c), 0.0))}" for c in labels)
            print(f"    {r:>4} {cells}")
        print(f"  Highlighted buckets:")
        for bucket in HIGHLIGHTED_BUCKETS:
            print(f"    {bucket[0]:>4}/{bucket[1]:<4}: {fmt_pct(grid.get(bucket, 0.0))}")
        good = sum(grid.get(b, 0.0) for b in HIGHLIGHTED_BUCKETS)
        print(f"    sum highlighted:   {fmt_pct(good)}")
        summary.append((s_id, eg, p3, good))
        print()
    print("--- Summary ---")
    print(f"  {'strat':>5} {'E[gold]':>12} {'P(3 cuts)':>12} {'P(highlighted)':>16}")
    for s_id, eg, p3, good in summary:
        print(f"  {s_id:>5} {fmt_gold(eg):>12} {fmt_pct(p3):>12} {fmt_pct(good):>16}")


# ---------- CLI: value ----------

def parse_line(spec):
    if len(spec) != 2:
        sys.exit(f"invalid line spec: {spec!r} (expected EFFECT and TIER)")
    eff, tier = spec
    if tier not in TIERS:
        sys.exit(f"invalid tier {tier!r}; must be one of {TIERS}")
    return eff, tier


def cmd_value(args):
    acc_type = args.type
    main_stat = args.main_stat
    lo, hi = MAIN_STAT_RANGE[acc_type]
    if not (lo <= main_stat <= hi):
        print(f"warning: main_stat {main_stat} outside expected [{lo}, {hi}]")
    lines = [parse_line(args.line1), parse_line(args.line2), parse_line(args.line3)]
    for eff, _ in lines:
        if eff not in EFFECTS[acc_type]:
            sys.exit(f"effect {eff!r} not valid for {acc_type}")
    if len({e for e, _ in lines}) != 3:
        sys.exit("the 3 lines must be different effects")
    d, f, gold = estimate_value(acc_type, main_stat, lines)
    print(f"=== {acc_type.upper()} accessory ===")
    print(f"  main stat:      {main_stat}")
    for i, (eff, tier) in enumerate(lines, 1):
        print(f"  line {i}:         {eff} ({tier})  +{line_damage(eff, tier):.3f}%")
    print(f"  main-stat dmg:  +{main_stat * MAIN_STAT_DAMAGE_PER_UNIT:.3f}%")
    mult = math.exp(d / 100.0)
    base = baseline_logdmg(acc_type)
    a, pmin = get_pricing(acc_type)
    gross = gross_value_at(acc_type, d)
    print(f"  damage multiplier:            x{mult:.4f}  (+{(mult - 1) * 100:.3f}% total)")
    print(f"  log-damage D:                 {d:.3f}  (baseline {base:.3f})")
    print(f"  F(D) under strategy 3:        {f:.5f}  (rarer = higher)")
    print(f"  pricing (Pareto a, pmin):     a={a:.3f}, pmin={fmt_gold(pmin)}/unit")
    print(f"  gross sale price:             {fmt_gold(gross)}")
    print(f"  sale tax:                     -{fmt_gold(SALE_TAX)}")
    print(f"  net value to seller:          {fmt_gold(gold)}")


# ---------- EV of cutting + catalog ----------

def ev_of_cutting(acc_type, main_stat, strategy_id):
    """E[value of final accessory] - E[gold spent on cuts].

    Partial outcomes (when the strategy stops before cut 3) are valued at 0g:
    the player abandons them.
    """
    dist = get_strategy_distribution(strategy_id, acc_type, main_stat)
    e_value = 0.0
    e_cost = 0.0
    for outcomes, prob in dist.items():
        e_cost += prob * CUT_COST * len(outcomes)
        if len(outcomes) == 3:
            d = accessory_damage(acc_type, main_stat, outcomes)
            e_value += prob * value_at(acc_type, d)
    return e_value - e_cost


def catalog_rows(acc_type):
    """Enumerate (primary tier pair, 3rd-line bucket) categories where both
    primaries appear among the 3 lines. Returns 63 rows max (9 primary pairs x
    7 third-line buckets: useless + flat ATK low/mid/high + flat WPN low/mid/high).
    """
    p1_name, p2_name = PRIMARY[acc_type]
    lo, hi = MAIN_STAT_RANGE[acc_type]
    mid_ms = (lo + hi) / 2
    line_dist = normalized_three_line_distribution(acc_type)
    cats = {}  # (pt1, pt2, third_label) -> [prob, prob-weighted line_damage]
    for line_set, line_prob in line_dist.items():
        tier_map = {e: t for e, t in line_set}
        if p1_name not in tier_map or p2_name not in tier_map:
            continue
        pt1, pt2 = tier_map[p1_name], tier_map[p2_name]
        third = [(e, t) for e, t in line_set if e != p1_name and e != p2_name]
        if len(third) != 1:
            continue
        e3, t3 = third[0]
        third_label = f"{e3} {t3}" if e3 in FLAT else "useless"
        key = (pt1, pt2, third_label)
        line_d = sum(line_logdmg(e, t) for e, t in line_set)
        slot = cats.setdefault(key, [0.0, 0.0])
        slot[0] += line_prob
        slot[1] += line_prob * line_d
    rows = []
    for (pt1, pt2, third_label), (total_p, weighted_d) in cats.items():
        if total_p < 1e-15:
            continue
        avg_line_d = weighted_d / total_p
        v_min = value_at(acc_type, main_stat_logdmg(lo) + avg_line_d)
        v_mid = value_at(acc_type, main_stat_logdmg(mid_ms) + avg_line_d)
        v_max = value_at(acc_type, main_stat_logdmg(hi) + avg_line_d)
        rows.append({
            "pair": (pt1, pt2),
            "third": third_label,
            "prob": total_p,
            "line_damage": avg_line_d,
            "v_min": v_min,
            "v_mid": v_mid,
            "v_max": v_max,
        })
    return rows


# ---------- CLI: report ----------

def cmd_report(args):
    for acc_type in EFFECTS:
        lo, hi = MAIN_STAT_RANGE[acc_type]
        mid_ms = (lo + hi) // 2
        print(f"=== {acc_type.upper()} ===  (main stat: {lo}-{hi}, mid={mid_ms})")
        print()
        print("EV of cutting a naked accessory")
        print("(E[value of final accessory] - E[gold spent]; partial cuts valued at 0g)")
        print(f"  {'main stat':>14}  {'Strategy 1':>14}  {'Optimal (S2)':>14}  {'Strategy 3':>14}")
        for label, ms in [("min", lo), ("mid", mid_ms), ("max", hi)]:
            cells = [f"{label}={ms}"]
            for s_id in (1, 2, 3):
                ev = ev_of_cutting(acc_type, ms, s_id)
                cells.append(fmt_gold(ev))
            print("  " + "  ".join(f"{c:>14}" for c in cells))
        print()

        rows = catalog_rows(acc_type)
        rows.sort(key=lambda r: r["v_mid"], reverse=True)
        print("Catalog under strategy 3 (sorted by value at mid main stat)")
        print(f"  {'pri pair':<10} {'3rd line':<26} "
              f"{'P(this)':>10} {'line dmg':>10} "
              f"{'Val(min)':>14} {'Val(mid)':>14} {'Val(max)':>14}")
        for r in rows:
            pt1, pt2 = r["pair"]
            pair_label = f"{pt1}/{pt2}"
            print(f"  {pair_label:<10} {r['third']:<26} "
                  f"{fmt_pct(r['prob']):>10} {r['line_damage']:>9.3f}% "
                  f"{fmt_gold(r['v_min']):>14} {fmt_gold(r['v_mid']):>14} "
                  f"{fmt_gold(r['v_max']):>14}")
        print()


# ---------- CLI: verify ----------

def cmd_verify(args):
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        status = "PASS" if cond else "FAIL"
        suffix = f" - {detail}" if detail else ""
        print(f"  [{status}] {label}{suffix}")
        if not cond:
            ok = False

    print("1. Distribution sanity + forward-recursion cross-check (rule-based strategies)")
    for acc_type in EFFECTS:
        print(f"\n  {acc_type}:")
        for s_id in (1, 3):
            enum_dist = enumerate_distribution(acc_type, STRATEGIES[s_id])
            fwd_dist = forward_distribution(acc_type, STRATEGIES[s_id])
            s_enum = sum(enum_dist.values())
            s_fwd = sum(fwd_dist.values())
            check(f"strategy {s_id}: enumerate sums to 1",
                  abs(s_enum - 1.0) < 1e-9, f"got {s_enum:.12f}")
            check(f"strategy {s_id}: forward   sums to 1",
                  abs(s_fwd - 1.0) < 1e-9, f"got {s_fwd:.12f}")
            keys = set(enum_dist) | set(fwd_dist)
            max_diff = max(abs(enum_dist.get(k, 0.0) - fwd_dist.get(k, 0.0))
                           for k in keys)
            check(f"strategy {s_id}: enumerate == forward",
                  max_diff < 1e-12, f"max delta {max_diff:.2e}")

    print("\n2. Manual spot checks (necklace)")
    enum_neck_s3 = enumerate_distribution("neck", strategy3)
    p_cut1_outgoing_high = sum(
        prob for outcomes, prob in enum_neck_s3.items()
        if outcomes[0] == ("Outgoing Damage %", "high")
    )
    check("P(cut 1 = Outgoing high) == 0.007",
          abs(p_cut1_outgoing_high - 0.007) < 1e-9,
          f"got {p_cut1_outgoing_high:.6f}")
    p_both = sum(
        prob for outcomes, prob in enum_neck_s3.items()
        if outcomes[0] == ("Additional Damage %", "mid")
        and outcomes[1] == ("Outgoing Damage %", "high")
    )
    p_cond1 = sum(
        prob for outcomes, prob in enum_neck_s3.items()
        if outcomes[0] == ("Additional Damage %", "mid")
    )
    p_cond = p_both / p_cond1
    check("P(cut 2 = Outgoing high | cut 1 = Additional mid) == 0.007 / 0.9",
          abs(p_cond - 0.007 / 0.9) < 1e-9, f"got {p_cond:.6f}")
    p_cut1_primary_midplus = sum(
        prob for outcomes, prob in enum_neck_s3.items()
        if outcomes[0][0] in PRIMARY["neck"]
        and outcomes[0][1] in ("mid", "high")
    )
    check("P(cut 1 is primary mid+) == 0.074",
          abs(p_cut1_primary_midplus - 0.074) < 1e-9,
          f"got {p_cut1_primary_midplus:.6f}")

    print("\n3. Value formula spot checks (top/bottom outcomes)")
    for acc_type in EFFECTS:
        lo, hi = MAIN_STAT_RANGE[acc_type]
        line_dist = normalized_three_line_distribution(acc_type)
        best_lines = max(
            line_dist.keys(),
            key=lambda ls: sum(line_damage(e, t) for e, t in ls),
        )
        d_top, f_top, g_top = estimate_value(acc_type, hi, list(best_lines))
        print(f"  {acc_type} top: lines={[(e, t) for e, t in best_lines]}, "
              f"d={d_top:.3f}%, F={f_top:.4f}, value={fmt_gold(g_top)}")
        non_dps = [e for e in EFFECTS[acc_type] if e not in LINE_DAMAGE][:3]
        bot_lines = [(e, "low") for e in non_dps]
        d_bot, f_bot, g_bot = estimate_value(acc_type, lo, bot_lines)
        print(f"  {acc_type} bot: lines={[e for e,_ in bot_lines]}, "
              f"d={d_bot:.3f}%, F={f_bot:.4f}, value={fmt_gold(g_bot)}")
        damages, cum_probs, cum_values = get_curve(acc_type)
        check(f"{acc_type}: CDF terminal value == 1.0",
              abs(cum_probs[-1] - 1.0) < 1e-9, f"got {cum_probs[-1]:.6f}")
        check(f"{acc_type}: true argmax F(d) ~= 1.0",
              abs(f_top - 1.0) < 1e-4, f"got {f_top:.6f}")
        check(f"{acc_type}: V(0) == 0", value_at(acc_type, 0.0) == 0.0)
        # V monotone non-decreasing across the supply curve.
        monotone = all(cum_values[i] <= cum_values[i + 1] + 1e-9
                       for i in range(len(cum_values) - 1))
        check(f"{acc_type}: V monotone non-decreasing on supply curve", monotone)
        # Top item's value upper-bounded by DEMAND_MAX * d_top (price cap).
        check(f"{acc_type}: V(d_top) <= DEMAND_MAX * d_top",
              g_top <= DEMAND_MAX * d_top + 1.0,
              f"V={fmt_gold(g_top)}, cap={fmt_gold(DEMAND_MAX * d_top)}")
        check(f"{acc_type}: bot value < 1k gold",
              g_bot < 1_000, f"got {fmt_gold(g_bot)}")

    print("\n4. Per-accessory Pareto calibration hits anchors (above baseline)")
    for acc_type in EFFECTS:
        a, pmin = get_pricing(acc_type)
        lo, _ = MAIN_STAT_RANGE[acc_type]
        p1, p2 = PRIMARY[acc_type]
        base = baseline_logdmg(acc_type)
        print(f"  {acc_type}: a={a:.3f}, pmin={fmt_gold(pmin)}/unit, "
              f"baseline D={base:.3f}")
        # Baseline accessory itself is worth 0 (gross and net).
        base_lines = [(p1, "high"), ("Attack Power+", "low"), ("Weapon Attack Power+", "low")]
        v_base = value_at(acc_type, accessory_damage(acc_type, lo, base_lines))
        check(f"  {acc_type}: baseline accessory == 0g", v_base == 0.0,
              f"got {fmt_gold(v_base)}")
        d_hm = accessory_damage(acc_type, lo, [(p1, "high"), (p2, "mid")])
        d_hh = accessory_damage(acc_type, lo, [(p1, "high"), (p2, "high")])
        # Anchors are NET prices; net = gross - tax should hit them.
        n_hm = value_at(acc_type, d_hm)
        n_hh = value_at(acc_type, d_hh)
        anchor_hm = PRICE_ANCHORS[acc_type]["hm"]
        anchor_hh = PRICE_ANCHORS[acc_type]["hh"]
        check(f"  {acc_type}: net(cheapest h/m) ~= {anchor_hm:,}",
              abs(n_hm - anchor_hm) < max(5_000, anchor_hm * 0.01),
              f"got {fmt_gold(n_hm)}")
        check(f"  {acc_type}: net(cheapest h/h) ~= {anchor_hh:,}",
              abs(n_hh - anchor_hh) < max(20_000, anchor_hh * 0.01),
              f"got {fmt_gold(n_hh)}")
        check(f"  {acc_type}: gross h/h == net + tax",
              abs(gross_value_at(acc_type, d_hh) - (anchor_hh + SALE_TAX)) < 5_000,
              f"gross={fmt_gold(gross_value_at(acc_type, d_hh))}")
        # Middle trio (high/low, low/high, mid/mid) should stay clustered.
        d_hl = accessory_damage(acc_type, lo, [(p1, "high"), (p2, "low")])
        d_lh = accessory_damage(acc_type, lo, [(p1, "low"), (p2, "high")])
        d_mm = accessory_damage(acc_type, lo, [(p1, "mid"), (p2, "mid")])
        mids = [value_at(acc_type, x) for x in (d_hl, d_lh, d_mm)]
        spread = max(mids) / max(min(mids), 1.0)
        print(f"    middle trio (h/l, l/h, m/m): "
              f"{fmt_gold(mids[0])}, {fmt_gold(mids[1])}, {fmt_gold(mids[2])} "
              f"(spread {spread:.1f}x)")

    print("\n5. Strategy ordering on EV (optimal >= S1 and >= S3, all >= 0)")
    for acc_type in EFFECTS:
        lo, hi = MAIN_STAT_RANGE[acc_type]
        mid_ms = (lo + hi) // 2
        ev1 = ev_of_cutting(acc_type, mid_ms, 1)
        ev2 = ev_of_cutting(acc_type, mid_ms, 2)
        ev3 = ev_of_cutting(acc_type, mid_ms, 3)
        print(f"  {acc_type} (mid stat): EV S1={fmt_gold(ev1)}, "
              f"S2(opt)={fmt_gold(ev2)}, S3={fmt_gold(ev3)}")
        check(f"{acc_type}: optimal EV >= S1 EV", ev2 >= ev1 - 1.0)
        check(f"{acc_type}: optimal EV >= S3 EV", ev2 >= ev3 - 1.0)
        check(f"{acc_type}: optimal EV >= 0", ev2 >= -1.0)

    print()
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


# ---------- main ----------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_s = sub.add_parser("strategy", help="strategy comparison for an accessory type")
    p_s.add_argument("type", choices=list(EFFECTS))
    p_s.set_defaults(func=cmd_strategy)

    p_v = sub.add_parser("value", help="estimate gold value of a finished accessory")
    p_v.add_argument("--type", required=True, choices=list(EFFECTS))
    p_v.add_argument("--main-stat", type=int, required=True)
    p_v.add_argument("--line1", nargs=2, required=True, metavar=("EFFECT", "TIER"))
    p_v.add_argument("--line2", nargs=2, required=True, metavar=("EFFECT", "TIER"))
    p_v.add_argument("--line3", nargs=2, required=True, metavar=("EFFECT", "TIER"))
    p_v.set_defaults(func=cmd_value)

    p_r = sub.add_parser("report",
                         help="all-accessories catalog + EV of cutting naked")
    p_r.set_defaults(func=cmd_report)

    p_x = sub.add_parser("verify", help="run closed-form sanity checks")
    p_x.set_defaults(func=cmd_verify)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
