"""What does the reward/penalty rule cost you? Monte-Carlo of a player who cashes out everything.

    python -m scripts.economics
"""
import random

ENTRY, REWARD, PENALTY, Q_PER_ROUND = 300, 50, 50, 10


def simulate(p: float, rounds: int, users: int = 4000, seed: int = 1) -> tuple[float, float]:
    rng = random.Random(seed)
    payouts = []
    for _ in range(users):
        n, w = ENTRY, 0                       # non-withdrawable ($3 entry), withdrawable earnings
        for _ in range(rounds * Q_PER_ROUND):
            if rng.random() < p:
                w += REWARD
            else:
                take = min(n, PENALTY); n -= take
                w = max(0, w - (PENALTY - take))
        payouts.append(w)
    avg = sum(payouts) / users
    return avg / 100, (ENTRY - avg) / 100


if __name__ == "__main__":
    print(f"Entry fee $3.00. +${REWARD/100:.2f} per correct, -${PENALTY/100:.2f} per wrong.\n")
    print(f"{'accuracy':>9} | {'rounds':>6} | {'avg cash-out':>12} | {'your net per player':>19}")
    for rounds in (1, 10, 50):
        for p in (0.40, 0.50, 0.60, 0.70, 0.825):
            out, net = simulate(p, rounds)
            print(f"{p:>8.1%} | {rounds:>6} | ${out:>11.2f} | {'+' if net >= 0 else '-'}${abs(net):>17.2f}")
        print("-" * 58)
