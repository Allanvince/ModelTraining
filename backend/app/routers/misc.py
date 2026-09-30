import asyncio
import hmac

from fastapi import APIRouter, Depends, Header, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.errors import AppError
from app.schemas import FundPoolIn, ResolveIn
from app.services import game, payments
from app.services import pool as pool_svc
from app.models import Transaction

router = APIRouter(tags=["misc"])


@router.get("/health")
def health():
    return {"ok": True, "mpesaMode": settings.mpesa_mode}


@router.get("/pool")
def pool_status(db: Session = Depends(get_db)):
    """Public, read-only. Shown in the UI as the prize pool - also lets you see at a glance whether
    it needs a top-up before payouts start throttling."""
    p = pool_svc.lock_pool(db)
    db.commit()
    return {"balanceCents": p.balance_cents, "balance": p.balance_cents / 100,
            "lifetimeFundedCents": p.lifetime_funded_cents, "lifetimePaidCents": p.lifetime_paid_cents}


@router.post("/admin/pool/fund")
def admin_fund_pool(body: FundPoolIn, x_admin_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Seed the pool with working capital (e.g. at launch, before enough penalties have funded it)."""
    if not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise AppError(403, "FORBIDDEN", "Admin token required.")
    p = pool_svc.lock_pool(db)
    pool_svc.fund(db, p, int(round(body.amount_usd * 100)), ref="admin-seed", kind="ADMIN_TOPUP")
    db.commit()
    return {"balanceCents": p.balance_cents, "balance": p.balance_cents / 100}


def _top10() -> list[dict]:
    with SessionLocal() as db:
        return game.leaderboard(db, 10)


@router.websocket("/ws/leaderboard")
async def ws_leaderboard(ws: WebSocket):
    """Pushes the top 10 whenever a round finishes. (In-process for the MVP; swap for Redis Pub/Sub
    when you run more than one server instance.)"""
    await ws.accept()
    seen = -1
    try:
        while True:
            if game.lb_version() != seen:
                seen = game.lb_version()
                await ws.send_json({"type": "leaderboard", "top": await run_in_threadpool(_top10)})
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=1.0)   # also detects disconnects
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        return


@router.post("/admin/transactions/{tx_id}/resolve")
def admin_resolve(tx_id: str, body: ResolveIn, x_admin_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Human decision for withdrawals stuck in NEEDS_REVIEW (after checking the M-Pesa portal)."""
    if not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise AppError(403, "FORBIDDEN", "Admin token required.")
    if db.get(Transaction, tx_id) is None:
        raise AppError(404, "NOT_FOUND", "Unknown transaction.")
    outcome = payments.resolve_withdrawal(db, tx_id, ok=(body.outcome == "COMPLETED"), desc="Resolved by admin")
    return {"result": outcome}
