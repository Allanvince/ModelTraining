from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Pool, PoolLedgerEntry


def lock_pool(db: Session) -> Pool:
    """SELECT ... FOR UPDATE on the single pool row. Every settlement takes this lock, so on Postgres
    concurrent round-finishes queue up here rather than racing (SQLite is already serialised)."""
    p = db.execute(select(Pool).where(Pool.id == 1).with_for_update()
                   .execution_options(populate_existing=True)).scalar_one_or_none()
    if p is None:
        p = Pool(id=1, balance_cents=0)
        db.add(p)
        db.flush()
    return p


def fund(db: Session, pool: Pool, cents: int, ref: str | None = None, kind: str = "PENALTY_FUNDS_POOL") -> None:
    """Money entering the pool: wrong-answer penalties, or a manual admin top-up."""
    if cents <= 0:
        return
    pool.balance_cents += cents
    pool.lifetime_funded_cents += cents
    db.add(PoolLedgerEntry(kind=kind, amount_cents=cents, balance_after_cents=pool.balance_cents, ref=ref))


def quote_payout(pool: Pool, points: int) -> tuple[int, int]:
    """Returns (target_cents, payable_cents). target is what full rate would pay; payable is what the
    pool can actually afford right now (never more than pool_settlement_fraction_percent of its balance).
    This is the whole solvency guarantee: payable_cents <= pool.balance_cents, always."""
    target = points * settings.point_value_cents
    budget = pool.balance_cents * settings.pool_settlement_fraction_percent // 100
    return target, max(0, min(target, budget))


def settle(db: Session, pool: Pool, points: int, ref: str) -> tuple[int, int]:
    """Pays out for a finished round. Returns (target_cents, paid_cents)."""
    target, paid = quote_payout(pool, points)
    if paid > 0:
        pool.balance_cents -= paid
        pool.lifetime_paid_cents += paid
        db.add(PoolLedgerEntry(kind="ROUND_PAYOUT", amount_cents=-paid, balance_after_cents=pool.balance_cents, ref=ref))
    return target, paid
