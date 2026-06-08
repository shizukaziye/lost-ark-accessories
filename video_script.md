# The Math Behind Accessories — Video Script

*Energetic, structured cut with a grounded first-person voice. No dramatic
metaphors. Lines in `[BRACKETS]` are on-screen / B-roll directions, not spoken.
Every number is pulled straight from the calculator (`accessory_value.py` /
`index.html`), so you can show the tool on screen as you say it.*

---

## COLD OPEN (0:00–0:35)

[VISUAL: A high/high necklace in the auction house with a multi-million gold price
tag. Cut to a screen full of low/low rolls in the cutting UI.]

> Two necklaces. Same slot, same item level. One sells for almost four million
> gold. The other one isn't worth the gold you spent cutting it.
>
> The only difference between them is a handful of dice rolls - and I'd bet most of
> you can't actually tell me what those rolls are worth. I couldn't either, for a
> long time.
>
> So I built a calculator that prices any accessory in the game from first
> principles. Just the drop rates and a demand model - no guessing off the auction
> house. And once I ran the numbers, it turned out a lot of us are making the same
> two mistakes over and over.

[VISUAL: Quick montage of the calculator — damage table, catalog, EV table.]

> Let me show you.

[TITLE CARD: "The Math Behind Accessories"]

---

## PART 1 — WHY THIS MATTERS (0:35–2:15)

[VISUAL: The Ark Passive cutting screen. Naked relic accessory, the cut button.]

> Quick refresher on the system. Every relic accessory - necklace, earring, ring -
> can be cut up to three times. Each cut reveals one effect at low, mid, or high,
> and then it's locked. No rerolls.

[VISUAL: Highlight the two primary lines for each slot.]

> Each slot has two lines that actually matter. Necklace is Outgoing Damage and
> Additional Damage. Earring is Attack Power percent and Weapon Attack Power
> percent. Ring is Crit Damage and Crit Rate. Plus two flat lines - flat Attack
> Power and flat Weapon Attack Power - that are fine on anything. Everything else,
> like Max HP or debuff duration, is dead weight if you're a DPS.

[VISUAL: Auction house, accessories sorted by price. Show the spread.]

> Here's the problem. The market for these spans three orders of magnitude. A clean
> roll is millions. A near-miss is tens of thousands. And the game tells you
> nothing about which is which - so people price by glancing at the auction house
> and guessing.
>
> But "what's it worth" is really two questions. One - if I already have this
> accessory, what should I sell it for. Two - if I've got a naked one, should I even
> be cutting it. Both have real answers, and they're not always the answer you'd
> expect. That's what this whole video is about.

---

## PART 2 — HOW THE CALCULATOR WORKS (2:15–7:30)

> To price an accessory you need three things - the odds of each roll, the damage
> each roll gives you, and the gold the market pays for that damage. Let me build
> them up one at a time.

### 2A — The odds (2:35–3:40)

[VISUAL: Table of the three tiers and their rates.]

> Start with the drop rates, straight from the Korean rate disclosures. For any one
> effect, a cut has a 6.3% chance of low, 3.0% for mid, and 0.7% for high. That's
> 10% per effect, ten effects in the pool, so it sums to a clean 100%.

[VISUAL: Animate locking one line, the pool renormalizing.]

> One detail that matters - once a cut locks an effect, that effect leaves the pool
> and everything renormalizes. So your second cut is out of 90%, your third out of
> 80%. The model conditions on that exactly.
>
> And because there's only three cuts, I don't have to simulate anything. The tool
> enumerates every possible outcome with its exact probability - the entire tree.
> No sampling, no error.

[VISUAL: The verify suite passing.]

> It's checked two different ways that have to agree to twelve decimal places, and
> they do.

### 2B — Turning rolls into damage (3:40–5:10)

[VISUAL: Two "+2%" lines with a multiplication sign between them.]

> Next - how much damage is each line worth. And this is the part most people get
> wrong, so stay with me. Damage in this game is multiplicative, not additive. A
> line that says 2% multiplies your damage by 1.02, and lines stack by multiplying
> together. You can't just add the percentages up and call it a day.
>
> The way the tool handles this is it works in log space. Take the log of each
> multiplier and multiplying turns into adding - so lines become additive again,
> but it stays exactly correct for the multiplication. You don't need to follow the
> math there; the point is the damage number is honest.

[VISUAL: The live "damage per line tier" table.]

> With real stats plugged in, a high Outgoing Damage line is worth about 2% on a
> necklace, a high Additional Damage about 1.9%. And notice high isn't three times
> low - the tiers aren't evenly spaced, so one high roll is worth a lot more than a
> couple of lows. That comes back later.

[VISUAL: The sqrt attack-power formula.]

> Main stat gets handled properly too, because attack power scales with the square
> root of your stats and a support in your party dilutes your personal
> contribution. The tool bakes both in, so the main stat roll is priced right
> instead of just bolted on.

### 2C — Turning damage into gold (5:10–6:50)

[VISUAL: A supply curve next to a demand curve.]

> Now we have, for every possible accessory, an exact probability and an exact
> damage number. Turning that into a price is just supply and demand.
>
> Supply is the probability distribution - if you cut to completion, how often does
> the game hand out a roll this good or better. The good stuff sits out on the tail,
> the junk piles up at the bottom.
>
> Demand is where I had to make a call. I model it as a Pareto curve - the 80/20
> rule. In practice that means buyers don't pay much extra for a mid roll, but the
> price climbs steeply as you approach best-in-slot, because the people bidding on
> the top items aren't price sensitive. I think that matches how this market
> actually behaves.

[VISUAL: Typing two anchor prices in, the curve fitting to them.]

> And I'm not inventing that curve. For each slot I calibrate it to two real
> listings - the cheapest high-mid and the cheapest high-high on the auction house -
> and the model fits itself to reproduce those exact prices. So it's pinned to
> reality at two points and interpolates the rest. If your server is different, you
> type your own prices in and it recalculates live.

### 2D — The assumptions, stated plainly (6:50–7:30)

[VISUAL: Clean bulleted list.]

> Let me be upfront about the assumptions, because every model has them. Demand
> follows that 80/20 shape. Your two anchor prices are accurate - so use your own.
> I bake in the Pheon tax, about 60,000 gold per accessory, since the buyer pays
> Pheons on top of your listing and you eat it. Cuts are 1,200 gold each. And I'm
> pricing for a DPS - supports are a different pool.
>
> Change any of those and the numbers move. That's the point of it being a
> calculator.

---

## PART 3 — THE RESULTS (7:30–12:30)

> Okay. We've got a model that prices any accessory in the game. Let me ask it the
> questions that actually matter.

### 3A — How rare a good one really is (7:40–9:00)

[VISUAL: The strategy-3 primary tier grid. Highlight high/high.]

> First, a reality check on rarity. If you cut a necklace all the way, the chance
> both primary lines come out high is 0.033%. That's three in ten thousand.
>
> And if I'm generous - counting every decent outcome, high-high down through the
> okay mixes - it still only adds up to about 1.5% of full cuts. So roughly 98 and a
> half percent of the time, you finish a cut and the market doesn't want it.

[VISUAL: The catalog, sorted by value, scroll from the top down to the zeros.]

> The value tracks that rarity closely. Here's the necklace catalog from the tool. A
> perfect high-high with a high flat Attack Power line and max main stat is around
> 13 million gold. A clean high-high with a junk third line is still about 3
> million. Drop to mid-mid and you're at roughly 42 thousand. And anything missing
> one of the two primaries is basically zero.
>
> That's the 80/20 in front of you. The top fraction of a percent of rolls holds
> almost all the value, and everything else is rounding error.

[VISUAL: The two `value` command outputs side by side.]

> Put it this way - a high-high necklace at max main stat is about 3.9 million. The
> same necklace at mid-mid is about 42 thousand. Same item, same slot, and that's a
> 90 times difference from two tier upgrades. That gap is way bigger than it looks
> on the auction house, which is exactly why eyeballing it gets you in trouble.

### 3B — Should you even be cutting? (9:00–11:00)

> Now the question that I think saves the most gold. You've got a naked accessory.
> Cut it, or sell it raw.

[VISUAL: The "EV of cutting a naked accessory" table.]

> This is expected value - the average gold you come out with per attempt, counting
> the hits and the whiffs, minus what you spend cutting. And it leans hard on your
> main stat roll. For a necklace - low main stat, cut all the way blindly, you lose
> about 560 gold on average. That's a losing play. Mid main stat, full send, is
> barely positive, around 50 gold - a coin flip that isn't worth your time. It's
> only on a high main stat that it's clearly worth doing.
>
> So I want to be clear about this one - cutting is not free money. On a mediocre
> base, the expected result is negative. The "I'll just cut it and get rich" idea
> is, for most accessories, not true.

[VISUAL: The optimal-policy decision table.]

> But how you cut matters as much as whether you cut. The tool compares three
> approaches. First - only commit if your first cut is a primary line at mid or
> better, otherwise stop. Second - always cut all three no matter what. Third - the
> mathematically optimal policy, which at every single step works out whether one
> more cut has positive expected value and stops the moment it doesn't.
>
> The optimal one wins everywhere, and on a high main stat necklace it's roughly
> double the expected value of blindly cutting everything. The reason is simple - it
> walks away from a bad start constantly. Most attempts, it stops early, because
> chasing a dead accessory is how you lose money. If you take one habit from this
> video, that's the one - know when to stop.

### 3C — The short version (11:00–11:45)

[VISUAL: Three points on a clean card.]

> If you remember nothing else, here's the three things.
>
> One - the value is way more skewed than it looks. A two-tier upgrade can be a 90
> times jump, so stop underselling your clean rolls.
>
> Two - blind cutting is often a losing bet. On a low or mid main stat base the
> expected value can be negative, so check before you commit.
>
> Three - cut with a stopping rule, not with hope. Walking away from a bad start
> early is the highest value habit in the whole system.

---

## OUTRO (11:45–12:30)

[VISUAL: The live calculator, plugging in the viewer's own anchors and stats.]

> The whole thing is a calculator that runs in your browser - you put in your own
> server's prices and your own stats, and it reprices everything live. I built it
> from the actual drop rates and a demand model you can argue with, and every
> formula is open, so if you think I got an assumption wrong, go change it and see
> what happens. Link's in the description.
>
> Go take a look at what your roster is actually sitting on. I'd bet a few of you
> are underpricing your good accessories and overpaying to cut your bad ones - and
> now you've got the math to fix it.
>
> If this was useful, a like helps a lot, and I'm thinking about giving gems the
> same treatment next - let me know if you'd want that. Thanks for watching, and
> good luck with your cuts.

[END CARD]

---

## APPENDIX — numbers cited, with sources

All reproducible from the repo:

| Claim | Value | How to reproduce |
|---|---|---|
| Tier base rates | low 6.3% / mid 3.0% / high 0.7% | `TIER_BASE_PROB` in `accessory_value.py` |
| Necklace high-line damage | Outgoing 2.00% / Additional 1.91% (high) | `python3 accessory_value.py value ...` |
| P(both primaries high, full cut) | 0.033% | `strategy neck`, high/high cell |
| Sum of "good" buckets (full cut) | 1.501% | `strategy neck`, sum highlighted |
| Perfect neck (high/high + flat ATK high, max MS) | ~13.0M | `report`, top catalog row |
| Clean high/high (useless 3rd) | ~2.98M (mid MS) / 3.4M (max) | `report` |
| mid/mid necklace | ~42.5k (mid MS) | `report` |
| high/high net @ max MS (ATK+ low 3rd) | 3,917,975g | `value --type neck --main-stat 17857 ...` |
| EV cut neck, min MS, Strategy 3 | −561g | `report` |
| EV cut neck, mid MS, Strategy 3 | +54g | `report` |
| EV cut neck, max MS, Optimal | +1,744g | `report` |
| Pheon (sale) tax | 60,000g | `SALE_TAX` |
| Cut cost | 1,200g | `CUT_COST` |

*Note for recording: anchor prices in the repo are placeholders
(neck hm 500k / hh 2.7M). Update them to current market before quoting absolute
gold figures on camera, or frame them as "with these example prices."*
