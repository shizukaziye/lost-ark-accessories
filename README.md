# Lost Ark Accessory Value Calculator

A from-first-principles model for pricing cut accessories (necklace / earring /
ring) under the Ark Passive system, rendered as a single-page infographic.

**Live site:** `index.html` (open it locally or via GitHub Pages).

## What it does

- Computes the exact probability of every 3-cut outcome (closed-form, no Monte
  Carlo) using the official Korean drop-rate table (6.3% / 3.0% / 0.7% per
  effect tier, with renormalization after each locked line).
- Scores damage **multiplicatively**: lines stack as a product, so the model
  works in log-multiplier space, `D = 100·Σ ln(1 + pᵢ/100)`.
- Prices each accessory by matching a **supply curve** (cut probabilities × 3
  main-stat levels) to a **Pareto demand curve** (`min(10M, pmin·(1−F)^(−1/a))`
  gold per unit log-damage, the 80/20 principle), integrated above a
  zero-value baseline.
- Subtracts the **60k Pheon tax** (buyer-paid, assuming Blue Crystals ~19,100g)
  so all gold figures are what the seller actually nets.
- Solves the optimal cutting policy via Bellman DP and compares it to simple
  heuristics.

Pricing is anchored to two hand-picked market observations per slot (the
cheapest high/mid and cheapest high/high); everything else is extrapolated.

## Usage

```bash
# Regenerate the infographic
python3 generate_infographic.py > index.html

# Inspect strategy odds / costs for one accessory type
python3 accessory_value.py strategy neck

# Value a specific accessory
python3 accessory_value.py value \
    --type neck --main-stat 17000 \
    --line1 "Outgoing Damage %" high \
    --line2 "Additional Damage %" mid \
    --line3 "Weapon Attack Power+" high

# Full report (all strategies, EV, catalog)
python3 accessory_value.py report

# Run the verification suite (closed-form sanity checks)
python3 accessory_value.py verify
```

Pure Python standard library — no dependencies.

## Files

- `accessory_value.py` — the model and CLI.
- `generate_infographic.py` — renders `index.html` from the model.
- `index.html` — the generated infographic (the published page).
