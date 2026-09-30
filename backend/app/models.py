import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("nonwithdrawable_cents >= 0", name="ck_nonwithdrawable_nonneg"),
        CheckConstraint("withdrawable_cents >= 0", name="ck_withdrawable_nonneg"),
        CheckConstraint("reserved_cents >= 0", name="ck_reserved_nonneg"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(12))
    password_hash: Mapped[str] = mapped_column(String(200))
    has_paid_entry_fee: Mapped[bool] = mapped_column(Boolean, default=False)
    nonwithdrawable_cents: Mapped[int] = mapped_column(Integer, default=0)
    withdrawable_cents: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cents: Mapped[int] = mapped_column(Integer, default=0)
    tests_completed: Mapped[int] = mapped_column(default=0)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    answers_total: Mapped[int] = mapped_column(Integer, default=0)
    answers_correct: Mapped[int] = mapped_column(Integer, default=0)
    response_ms_total: Mapped[int] = mapped_column(BigInteger, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    @property
    def total_cents(self) -> int:
        return self.nonwithdrawable_cents + self.withdrawable_cents


class Transaction(Base):
    """DEPOSIT: PENDING -> COMPLETED | FAILED | REVIEW.
    WITHDRAWAL: PROCESSING -> COMPLETED | FAILED | NEEDS_REVIEW."""
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_tx_idem"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(12))
    amount_cents: Mapped[int] = mapped_column(Integer)
    amount_kes: Mapped[int] = mapped_column(Integer)
    house_cut_cents: Mapped[int] = mapped_column(Integer, default=0)   # realized profit portion of a DEPOSIT
    status: Mapped[str] = mapped_column(String(16), index=True)
    checkout_request_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    merchant_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    originator_conversation_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mpesa_receipt: Mapped[str | None] = mapped_column(String(50), nullable=True)
    result_desc: Mapped[str | None] = mapped_column(String(300), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class LedgerEntry(Base):
    """Append-only audit trail of every balance change."""
    __tablename__ = "ledger_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    bucket: Mapped[str] = mapped_column(String(16))
    amount_cents: Mapped[int] = mapped_column(Integer)
    balance_after_cents: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Pool(Base):
    """Singleton row (id=1). Correct-answer payouts can never exceed this balance."""
    __tablename__ = "pool"
    __table_args__ = (CheckConstraint("balance_cents >= 0", name="ck_pool_nonneg"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    lifetime_funded_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    lifetime_paid_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class PoolLedgerEntry(Base):
    """Append-only audit trail of every pool inflow (penalties, admin top-ups) and outflow (payouts)."""
    __tablename__ = "pool_ledger_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(24))
    amount_cents: Mapped[int] = mapped_column(Integer)          # positive = inflow, negative = payout
    balance_after_cents: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class WebhookEvent(Base):
    """Raw copy of every Safaricom callback, kept for audit / replay."""
    __tablename__ = "webhook_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(24))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(60), index=True)
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    correct_idx: Mapped[int] = mapped_column(Integer)
    timer_seconds: Mapped[int] = mapped_column(Integer, default=4)


class GameSession(Base):
    __tablename__ = "game_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE")   # ACTIVE|FINISHED|ABANDONED
    plan: Mapped[list] = mapped_column(JSON)                             # [{"q": id, "perm": [..]}]
    answered_count: Mapped[int] = mapped_column(Integer, default=0)
    dispatched_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    is_test: Mapped[bool] = mapped_column(default=False)
    total_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    net_cents: Mapped[int] = mapped_column(Integer, default=0)          # penalties in-round, then +payout at settlement
    start_balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    points_earned: Mapped[int] = mapped_column(Integer, default=0)
    payout_target_cents: Mapped[int] = mapped_column(Integer, default=0)  # what full, un-throttled rate would pay
    payout_cents: Mapped[int] = mapped_column(Integer, default=0)         # what the pool actually paid
    pool_balance_after_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SessionAnswer(Base):
    __tablename__ = "session_answers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("game_sessions.id"), index=True)
    question_id: Mapped[str] = mapped_column(String(36))
    chosen_idx: Mapped[int] = mapped_column(Integer)
    correct: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(12))                      # CORRECT|WRONG|TIMEOUT
    delta_ms: Mapped[int] = mapped_column(BigInteger)
    response_ms: Mapped[int] = mapped_column(BigInteger)
    cents: Mapped[int] = mapped_column(Integer)     # instant cash change (penalties only; corrects earn points, not cash)
    points: Mapped[int] = mapped_column(Integer, default=0)