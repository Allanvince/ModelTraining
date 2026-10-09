"""Read-only admin analytics.  GET /api/v1/admin/overview?days=14   (header: X-Admin-Token)"""
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.models import GameSession, Pool, Transaction, User
from app.mpesa.daraja import get_daraja
from app.services import payments as pay_svc

router = APIRouter(prefix="/admin", tags=["admin"])
cron_router = APIRouter(prefix="/cron", tags=["cron"])


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if settings.admin_token == "dev-admin-token" and not settings.dev_mode:
        raise AppError(503, "ADMIN_DISABLED", "Set a strong ADMIN_TOKEN in .env before using the admin dashboard.")
    if not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise AppError(403, "FORBIDDEN", "Wrong admin token.")


def require_cron(authorization: str = Header(default="")) -> None:
    """Vercel Cron sends 'Authorization: Bearer <CRON_SECRET>' when the CRON_SECRET env var is set."""
    if not settings.cron_secret:
        raise AppError(503, "CRON_DISABLED", "Set CRON_SECRET to enable scheduled jobs.")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {settings.cron_secret}".encode()):
        raise AppError(403, "FORBIDDEN", "Bad cron secret.")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _val(db: Session, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def _sum(db: Session, col, *where) -> int:
    return _val(db, select(func.coalesce(func.sum(col), 0)).where(*where))


def _count(db: Session, col, *where) -> int:
    return _val(db, select(func.count(col)).where(*where))


def _daily(db: Session, date_col, value, since, *where) -> dict[str, int]:
    day = func.date(date_col)
    rows = db.execute(select(day, value).where(date_col >= since, *where).group_by(day)).all()
    return {str(d): int(v or 0) for d, v in rows}


def _mask_phone(p: str) -> str:
    return p[:5] + "****" + p[-3:] if len(p) >= 9 else "***"


@router.get("/overview", dependencies=[Depends(require_admin)])
def overview(days: int = Query(14, ge=7, le=60), db: Session = Depends(get_db)):
    now = _now()
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_keys = [(since + timedelta(days=i)).date().isoformat() for i in range(days)]

    def series(data: dict[str, int]) -> list[dict]:
        return [{"day": d, "value": data.get(d, 0)} for d in day_keys]

    T = Transaction
    dep_ok = (T.type == "DEPOSIT", T.status == "COMPLETED")
    wd_ok = (T.type == "WITHDRAWAL", T.status == "COMPLETED")

    # ---------------- users
    paid = User.has_paid_entry_fee.is_(True)
    users = {
        "total": _count(db, User.id),
        "new7d": _count(db, User.id, User.created_at >= now - timedelta(days=7)),
        "paid": _count(db, User.id, paid),
        "locked": _count(db, User.id, paid, (User.nonwithdrawable_cents + User.withdrawable_cents) <= 0),
        "active7d": _val(db, select(func.count(func.distinct(GameSession.user_id)))
                         .where(GameSession.created_at >= now - timedelta(days=7))),
        "completedPractice": _count(db, User.id, User.tests_completed >= settings.required_test_rounds),
    }

    # ---------------- money
    deposits_cents = _sum(db, T.amount_cents, *dep_ok)
    deposit_cut = _sum(db, T.house_cut_cents, *dep_ok)
    wd_gross = _sum(db, T.amount_cents, *wd_ok)
    wd_fees = _sum(db, T.house_cut_cents, *wd_ok)
    nonw = _sum(db, User.nonwithdrawable_cents)
    wdable = _sum(db, User.withdrawable_cents)
    reserved = _sum(db, User.reserved_cents)
    pool = db.get(Pool, 1)
    pool_bal = int(pool.balance_cents) if pool else 0
    money = {
        "depositsCount": _count(db, T.id, *dep_ok), "depositsCents": deposits_cents,
        "withdrawalsCount": _count(db, T.id, *wd_ok), "withdrawalsGrossCents": wd_gross,
        "depositCutCents": deposit_cut, "withdrawalFeesCents": wd_fees,
        "realizedRevenueCents": deposit_cut + wd_fees,
        "inFlightWithdrawalsCents": _sum(db, T.amount_cents, T.type == "WITHDRAWAL", T.status.in_(("PROCESSING", "NEEDS_REVIEW"))),
        "owedToPlayersCents": wdable + reserved,        # cash we would pay out if everyone withdrew now
        "playerCollateralCents": nonw,
        "poolBalanceCents": pool_bal,
        "poolLifetimeFundedCents": int(pool.lifetime_funded_cents) if pool else 0,
        "poolLifetimePaidCents": int(pool.lifetime_paid_cents) if pool else 0,
    }
    # Sanity check: cash in - completed withdrawals - our deposit cut should equal what players + pool hold.
    # In dev mode (dev top-ups) or after admin pool top-ups this will not be 0.
    money["reconciliationDiffCents"] = (deposits_cents - deposit_cut - wd_gross) - (nonw + wdable + reserved + pool_bal)

    # ---------------- games
    finished = (GameSession.status == "FINISHED", GameSession.is_test.is_(False))
    answers_total = _sum(db, User.answers_total)
    games = {
        "finished": _count(db, GameSession.id, GameSession.status == "FINISHED"),
        "practiceFinished": _count(db, GameSession.id, GameSession.status == "FINISHED", GameSession.is_test.is_(True)),
        "abandoned": _count(db, GameSession.id, GameSession.status == "ABANDONED"),
        "accuracyPercent": round(100 * _sum(db, User.answers_correct) / answers_total, 1) if answers_total else 0,
        "throttledRounds": _val(db, select(func.count(GameSession.id)).where(*finished, GameSession.payout_cents < GameSession.payout_target_cents)),
        "paidOutCents": _sum(db, GameSession.payout_cents, *finished),
    }
    cat_rows = db.execute(select(GameSession.category, func.count(), func.coalesce(func.sum(GameSession.correct_count), 0),
                                 func.coalesce(func.sum(GameSession.answered_count), 0), func.coalesce(func.sum(GameSession.net_cents), 0))
                          .where(GameSession.status == "FINISHED").group_by(GameSession.category)).all()
    categories = [{"category": c, "rounds": int(n), "accuracyPercent": round(100 * int(ok) / int(ans)) if ans else 0,
                   "playersNetCents": int(net)} for c, n, ok, ans, net in cat_rows]

    # ---------------- daily series
    charts = {
        "signups": series(_daily(db, User.created_at, func.count(), since)),
        "depositsCents": series(_daily(db, T.created_at, func.sum(T.amount_cents), since, *dep_ok)),
        "rounds": series(_daily(db, GameSession.created_at, func.count(), since, GameSession.status == "FINISHED")),
        "withdrawalsCents": series(_daily(db, T.created_at, func.sum(T.amount_cents), since, *wd_ok)),
    }

    # ---------------- needs attention + recent
    def tx_row(t: Transaction, username: str, phone: str) -> dict:
        return {"id": t.id, "type": t.type, "status": t.status, "amountCents": t.amount_cents, "amountKes": t.amount_kes,
                "feeCents": t.house_cut_cents if t.type == "WITHDRAWAL" else 0, "user": username,
                "phone": _mask_phone(t.conversation_id[7:] if t.type == "DEPOSIT" and (t.conversation_id or "").startswith("msisdn:") else phone),
                "receipt": t.mpesa_receipt, "note": t.result_desc, "createdAt": t.created_at.isoformat()}

    base = select(T, User.username, User.phone).join(User, User.id == T.user_id)
    review = [tx_row(*r) for r in db.execute(base.where(T.status.in_(("REVIEW", "NEEDS_REVIEW"))).order_by(T.created_at.desc()).limit(50)).all()]
    recent = [tx_row(*r) for r in db.execute(base.order_by(T.created_at.desc()).limit(15)).all()]
    top = [{"username": u.username, "games": u.games_played, "gamesAccuracyPercent": round(100 * u.answers_correct / u.answers_total) if u.answers_total else 0,
            "withdrawableCents": u.withdrawable_cents, "bestStreak": u.best_streak}
           for u in db.scalars(select(User).order_by(User.games_played.desc()).limit(10))]

    money["owedKes"] = int(round((wdable + reserved) * settings.kes_per_usd / 100))
    return {"generatedAt": now.isoformat(), "mpesaBalance": pay_svc.latest_balance(db), "days": days, "kesPerUsd": settings.kes_per_usd, "devMode": settings.dev_mode,
            "users": users, "money": money, "games": games, "categories": categories, "charts": charts,
            "needsReview": review, "recentTransactions": recent, "topPlayers": top}


# ------------------------------------------------------------------ admin actions ------------
class StatusCheckBody(BaseModel):
    receipt: str | None = None      # optional: M-Pesa receipt from the Org Portal statement


class ResolveBody(BaseModel):
    action: str                     # "complete" | "refund"
    receipt: str | None = None


@router.post("/withdrawals/{tx_id}/check-status", dependencies=[Depends(require_admin)])
def check_status(tx_id: str, body: StatusCheckBody, db: Session = Depends(get_db), daraja=Depends(get_daraja)):
    tx = pay_svc.request_withdrawal_status_check(db, tx_id, daraja, body.receipt)
    return {"ok": True, "note": tx.result_desc}


@router.post("/withdrawals/{tx_id}/resolve", dependencies=[Depends(require_admin)])
def resolve(tx_id: str, body: ResolveBody, db: Session = Depends(get_db)):
    return {"ok": True, "result": pay_svc.manual_resolve_withdrawal(db, tx_id, body.action, body.receipt)}


@router.post("/mpesa-balance/refresh", dependencies=[Depends(require_admin)])
def refresh_balance(db: Session = Depends(get_db), daraja=Depends(get_daraja)):
    return {"ok": True, "result": pay_svc.request_balance(db, daraja)}


@router.post("/reconcile", dependencies=[Depends(require_admin)])
def reconcile_now(db: Session = Depends(get_db), daraja=Depends(get_daraja)):
    return {"deposits": pay_svc.reconcile_pending_deposits(db, daraja),
            "withdrawalChecks": pay_svc.check_stale_withdrawals(db, daraja)}


# ------------------------------------------------------------------ scheduled jobs (Vercel Cron) -----
@cron_router.get("/reconcile", dependencies=[Depends(require_cron)])
def cron_reconcile(db: Session = Depends(get_db), daraja=Depends(get_daraja)):
    return {"deposits": pay_svc.reconcile_pending_deposits(db, daraja),
            "withdrawalChecks": pay_svc.check_stale_withdrawals(db, daraja)}


@cron_router.get("/balance", dependencies=[Depends(require_cron)])
def cron_balance(db: Session = Depends(get_db), daraja=Depends(get_daraja)):
    return {"result": pay_svc.request_balance(db, daraja)}