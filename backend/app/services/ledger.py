from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError
from app.models import LedgerEntry, User


def lock_user(db: Session, user_id: str) -> User:
    """SELECT ... FOR UPDATE on Postgres. On SQLite the whole transaction is already serialised."""
    user = db.execute(select(User).where(User.id == user_id).with_for_update()
                       .execution_options(populate_existing=True)).scalar_one_or_none()
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "Account not found.")
    return user


def add_entry(db: Session, user: User, kind: str, bucket: str, cents: int, ref: str | None = None) -> None:
    db.add(LedgerEntry(user_id=user.id, kind=kind, bucket=bucket, amount_cents=cents,
                       balance_after_cents=user.total_cents, ref=ref))


def apply_penalty(db: Session, user: User, ref: str) -> int:
    """A wrong or timed-out answer. Deducted from withdrawable (past winnings) first, then from the
    non-withdrawable entry-fee collateral. This order matters: it means the house only ever owes real
    cash for a player's *net* winnings, never their gross rewards. The caller hands whatever is
    deducted here to the pool, to fund future payouts. Never goes below zero. Returns the (negative)
    cash change."""
    left = settings.penalty_cents
    take_w = min(user.withdrawable_cents, left)
    user.withdrawable_cents -= take_w
    left -= take_w
    take_n = min(user.nonwithdrawable_cents, left)
    user.nonwithdrawable_cents -= take_n
    if take_w:
        add_entry(db, user, "ANSWER_PENALTY", "withdrawable", -take_w, ref)
    if take_n:
        add_entry(db, user, "ANSWER_PENALTY", "nonwithdrawable", -take_n, ref)
    return -(take_w + take_n)


def credit_payout(db: Session, user: User, cents: int, ref: str) -> None:
    if cents <= 0:
        return
    user.withdrawable_cents += cents
    add_entry(db, user, "POOL_PAYOUT", "withdrawable", cents, ref)
