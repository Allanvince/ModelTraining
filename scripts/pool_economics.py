"""Does the pooled model actually protect the house, at scale? Unlike scripts/economics.py (the old
symmetric per-answer model, kept for comparison), this simulates the REAL server logic end-to-end:
correct answers earn points, points convert to cash from the shared pool at round end, capped by
what the pool can afford. Wrong answers fund the pool immediately.

Accounting note: every dollar of the $3 entry fee is real cash the house already holds the moment
M-Pesa confirms it - the "house cut" vs "collateral" split is just an internal label for how much of
that cash is earmarked as being at risk, not a separation of where the money physically sits. So the
house's true liability at any moment is only what's sitting in players' WITHDRAWABLE balances (that's
the only money a player can actually cash out); the pool and the collateral bucket are still the
house's own cash.

    python -m scripts.pool_economics
"""
import random

from app.config import settings

ENTRY = settings.entry_fee_cents
HOUSE_CUT = ENTRY * settings.entry_house_cut_percent // 100
COLLATERAL = ENTRY - HOUSE_CUT
PENALTY = settings.penalty_cents
POINTS_PER_CORRECT = settings.points_per_correct
POINT_VALUE = settings.point_value_cents
SETTLE_FRACTION = settings.pool_settlement_fraction_percent
N = 10


def play_round(p, nonw, w, pool, rng):
    """One 10-question round against the real withdrawable-first / points / pool-settlement rules."""
    points = 0
    for _ in range(N):
        if rng.random() < p:
            points += POINTS_PER_CORRECT
        else:
            take_w = min(w, PENALTY); w -= take_w
            take_n = min(nonw, PENALTY - take_w); nonw -= take_n
            pool += take_w + take_n
    target = points * POINT_VALUE
    budget = pool * SETTLE_FRACTION // 100
    paid = min(target, budget)
    pool -= paid
    w += paid
    return nonw, w, pool


def simulate(p, rounds, users, seed):
    rng = random.Random(seed)
    total_collected_cents = ENTRY * users        # every dollar of entry fees ever paid in, real cash
    pool = 0
    accounts = [(COLLATERAL, 0) for _ in range(users)]

    for _ in range(rounds):
        for i, (nonw, w) in enumerate(accounts):
            if nonw + w <= 0:                        # wiped out: pay the entry fee again
                total_collected_cents += ENTRY
                nonw = COLLATERAL
            nonw, w, pool = play_round(p, nonw, w, pool, rng)
            accounts[i] = (nonw, w)

    liability_cents = sum(w for _, w in accounts)    # the ONLY money the house actually owes anyone
    house_net_cents = total_collected_cents - liability_cents
    return total_collected_cents / 100, liability_cents / 100, house_net_cents / 100, pool / 100


if __name__ == "__main__":
    print(f"Entry ${ENTRY/100:.2f} (house keeps ${HOUSE_CUT/100:.2f} upfront, ${COLLATERAL/100:.2f} goes to "
          f"collateral). {POINTS_PER_CORRECT} pts/correct * {POINT_VALUE}c = "
          f"${POINTS_PER_CORRECT*POINT_VALUE/100:.2f}/correct at full pool health.\n")
    print(f"{'accuracy':>9} | {'rounds':>6} | {'cash collected':>14} | {'owed to players':>16} | {'house net':>10} | {'pool left':>10}")
    for rounds in (10, 50, 200):
        for p in (0.50, 0.60, 0.70, 0.80, 0.90, 0.99):
            collected, owed, net, pool = simulate(p, rounds, users=500, seed=rounds * 97 + int(p * 1000))
            print(f"{p:>8.0%} | {rounds:>6} | ${collected:>13.2f} | ${owed:>15.2f} | ${net:>9.2f} | ${pool:>9.2f}")
        print("-" * 76)
    print("\nhouse net = cash collected - what's owed to players (their withdrawable balances). This can")
    print("never go negative by construction: the pool only ever pays out cash it's already holding, so")
    print("'owed to players' can never exceed 'cash collected'. Try accuracy 0.99 above: net gets thin")
    print("but never crosses zero, because payouts throttle down as the pool empties.")
