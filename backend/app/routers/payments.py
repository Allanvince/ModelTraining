import hmac

from fastapi import APIRouter, Body, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.models import Transaction, User
from app.mpesa.daraja import get_daraja
from app.schemas import WithdrawIn
from app.security import current_user
from app.services import payments
from app.services.game import balances

router = APIRouter(prefix="/payments", tags=["payments"])
ACK = {"ResultCode": 0, "ResultDesc": "Accepted"}


def _guard_callback(secret: str, request: Request) -> None:
    if not hmac.compare_digest(secret, settings.callback_secret):
        raise AppError(403, "FORBIDDEN", "Bad callback secret.")
    allow = [ip.strip() for ip in settings.callback_ip_allowlist.split(",") if ip.strip()]
    if allow and (request.client.host if request.client else "") not in allow:
        raise AppError(403, "FORBIDDEN", "Callback source not allowed.")


def _tx_out(tx: Transaction) -> dict:
    status = {"COMPLETED": "SUCCESS"}.get(tx.status, tx.status)
    return {"id": tx.id, "type": tx.type, "status": status, "amountCents": tx.amount_cents, "amountKes": tx.amount_kes,
            "checkoutRequestId": tx.checkout_request_id, "receipt": tx.mpesa_receipt, "resultDesc": tx.result_desc,
            "createdAt": tx.created_at.isoformat()}


@router.post("/deposit")
def deposit(user: User = Depends(current_user), db: Session = Depends(get_db), daraja=Depends(get_daraja)):
    tx = payments.initiate_deposit(db, user, daraja)
    return {**_tx_out(tx), "message": "Check your phone and enter M-Pesa PIN"}


@router.get("/status/{checkout_request_id}")
def status(checkout_request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    tx = db.scalar(select(Transaction).where(Transaction.checkout_request_id == checkout_request_id,
                                             Transaction.user_id == user.id))
    if tx is None:
        raise AppError(404, "NOT_FOUND", "Unknown payment.")
    return _tx_out(tx)


@router.post("/withdraw")
def withdraw(body: WithdrawIn, user: User = Depends(current_user), db: Session = Depends(get_db),
             daraja=Depends(get_daraja), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    cents = int(round(body.amount_usd * 100))
    tx = payments.request_withdrawal(db, user.id, cents, idempotency_key, daraja)
    u = db.get(User, user.id)
    db.refresh(u)
    return {**_tx_out(tx), "balances": balances(u)}


@router.get("/transactions")
def transactions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Transaction).where(Transaction.user_id == user.id)
                      .order_by(Transaction.created_at.desc()).limit(50))
    return [_tx_out(t) for t in rows]


# ---- Safaricom -> us (no auth header exists, so the URL carries a secret) -------------------
@router.post("/stk-callback/{secret}")
def stk_callback(secret: str, request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    _guard_callback(secret, request)
    payments.record_webhook(db, "stk", payload)
    payments.handle_stk_callback(db, payload)
    return ACK


@router.post("/b2c-result/{secret}")
def b2c_result(secret: str, request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    _guard_callback(secret, request)
    payments.record_webhook(db, "b2c-result", payload)
    payments.handle_b2c_result(db, payload)
    return ACK


@router.post("/b2c-timeout/{secret}")
def b2c_timeout(secret: str, request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    _guard_callback(secret, request)
    payments.record_webhook(db, "b2c-timeout", payload)
    payments.handle_b2c_timeout(db, payload)
    return ACK
