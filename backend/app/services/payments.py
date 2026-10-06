import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError
from app.models import Transaction, User, WebhookEvent
from app.money import cents_to_kes
from app.mpesa.daraja import DarajaError
from app.services import pool as pool_svc
from app.services.ledger import add_entry, lock_user

OPEN_WITHDRAWAL = ("PROCESSING", "NEEDS_REVIEW")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def callback_url(kind: str) -> str:
    return f"{settings.public_base_url}/api/v1/payments/{kind}/{settings.callback_secret}"


def record_webhook(db: Session, source: str, payload: dict) -> None:
    db.add(WebhookEvent(source=source, payload=json.dumps(payload)))
    db.commit()


# ------------------------------------------------------------------ deposits (STK Push) --
def initiate_deposit(db: Session, user: User, daraja) -> Transaction:
    cutoff = _utcnow() - timedelta(seconds=120)
    recent = db.scalar(select(Transaction).where(
        Transaction.user_id == user.id, Transaction.type == "DEPOSIT",
        Transaction.status == "PENDING", Transaction.created_at >= cutoff))
    if recent:                                   # don't fire a second prompt at the same phone
        return recent
    kes = cents_to_kes(settings.entry_fee_cents)
    try:
        resp = daraja.stk_push(phone=user.phone, amount_kes=kes, account_ref="QuickIQ",
                               description="Entry fee", callback_url=callback_url("stk-callback"))
    except DarajaError as e:
        raise AppError(502, "MPESA_UNAVAILABLE", f"M-Pesa did not accept the request: {e}")
    tx = Transaction(user_id=user.id, type="DEPOSIT", amount_cents=settings.entry_fee_cents, amount_kes=kes,
                     status="PENDING", checkout_request_id=resp["CheckoutRequestID"],
                     merchant_request_id=resp.get("MerchantRequestID"))
    db.add(tx)
    db.commit()
    return tx


def handle_stk_callback(db: Session, payload: dict) -> str:
    try:
        cb = payload["Body"]["stkCallback"]
        checkout_id = cb["CheckoutRequestID"]
        code = int(cb["ResultCode"])
    except (KeyError, TypeError, ValueError):
        raise AppError(400, "BAD_PAYLOAD", "Not a valid STK callback.")

    tx = db.execute(select(Transaction).where(Transaction.checkout_request_id == checkout_id)
                    .with_for_update()).scalar_one_or_none()
    if tx is None:
        return "unknown"
    if tx.status != "PENDING":                   # Idempotency guard: retries land here
        return "duplicate"

    if code != 0:
        tx.status = "FAILED"
        tx.result_desc = str(cb.get("ResultDesc", ""))[:300]
        db.commit()
        return "failed"

    items = (cb.get("CallbackMetadata") or {}).get("Item") or []
    meta = {i.get("Name"): i.get("Value") for i in items}
    receipt = meta.get("MpesaReceiptNumber")
    try:
        paid_kes = int(round(float(meta.get("Amount"))))
    except (TypeError, ValueError):
        paid_kes = -1
    if not receipt or paid_kes != tx.amount_kes:
        tx.status = "REVIEW"
        tx.result_desc = f"Amount/receipt mismatch: expected KES {tx.amount_kes}, got {meta.get('Amount')}"
        db.commit()
        return "review"

    user = lock_user(db, tx.user_id)
    house_cut = tx.amount_cents * settings.entry_house_cut_percent // 100
    collateral = tx.amount_cents - house_cut
    user.nonwithdrawable_cents += collateral
    user.has_paid_entry_fee = True
    tx.status = "COMPLETED"
    tx.mpesa_receipt = str(receipt)
    add_entry(db, user, "ENTRY_FEE", "nonwithdrawable", collateral, tx.id)
    tx.house_cut_cents = house_cut         # realized profit, tracked on the transaction itself
    db.commit()
    return "completed"


# ---------------------------------------------------------------- withdrawals (B2C) -----
def request_withdrawal(db: Session, user_id: str, cents: int, idem_key: str | None, daraja) -> Transaction:
    if cents < settings.min_withdraw_cents:
        raise AppError(400, "BELOW_MINIMUM", f"Minimum withdrawal is ${settings.min_withdraw_cents / 100:.2f}.")
    fee_cents = int(round(cents * settings.withdraw_fee_percent / 100))
    net_cents = cents - fee_cents                  # what the player actually receives
    kes = cents_to_kes(net_cents)
    if kes < 10:                                   # Safaricom B2C minimum
        raise AppError(400, "BELOW_MPESA_MIN", "After the service fee this is below M-Pesa's KES 10 minimum.")
    user = lock_user(db, user_id)

    if idem_key:
        prior = db.scalar(select(Transaction).where(Transaction.user_id == user_id,
                                                    Transaction.idempotency_key == idem_key))
        if prior:
            return prior
    if user.tests_completed < settings.required_test_rounds:
        raise AppError(403, "NOT_ELIGIBLE",
                       f"Finish {settings.required_test_rounds} practice rounds before withdrawing.")
    if user.withdrawable_cents < cents:
        raise AppError(400, "INSUFFICIENT_FUNDS",
                       f"You can withdraw up to ${user.withdrawable_cents / 100:.2f}. Only earnings are withdrawable.")

    user.withdrawable_cents -= cents             # atomic reserve
    user.reserved_cents += cents
    # amount_cents = full amount taken from winnings; amount_kes = net sent to M-Pesa; house_cut_cents = our fee
    tx = Transaction(user_id=user.id, type="WITHDRAWAL", amount_cents=cents, amount_kes=kes, status="PROCESSING",
                     house_cut_cents=fee_cents, originator_conversation_id=uuid.uuid4().hex, idempotency_key=idem_key)
    db.add(tx)
    db.flush()
    add_entry(db, user, "WITHDRAW_RESERVE", "withdrawable", -cents, tx.id)
    db.commit()

    try:
        resp = daraja.b2c(originator_conversation_id=tx.originator_conversation_id, phone=user.phone,
                          amount_kes=kes, remarks="QuickIQ payout",
                          result_url=callback_url("b2c-result"), timeout_url=callback_url("b2c-timeout"))
    except DarajaError as e:
        if e.definitive:
            resolve_withdrawal(db, tx.id, ok=False, desc=str(e)[:300])
        else:                                     # might still be paid: keep funds reserved, flag for a human
            tx.status = "NEEDS_REVIEW"
            tx.result_desc = f"Outcome unknown: {e}"[:300]
            db.commit()
        db.refresh(tx)
        return tx
    tx.conversation_id = resp.get("ConversationID")
    db.commit()
    return tx


def resolve_withdrawal(db: Session, tx_id: str, *, ok: bool, desc: str = "", receipt: str | None = None) -> str:
    """Single place that settles a withdrawal. Safe to call twice: only the first call has any effect."""
    tx = db.execute(select(Transaction).where(Transaction.id == tx_id).with_for_update()
                      .execution_options(populate_existing=True)).scalar_one()
    if tx.type != "WITHDRAWAL" or tx.status not in OPEN_WITHDRAWAL:
        return "duplicate"
    user = lock_user(db, tx.user_id)
    user.reserved_cents -= tx.amount_cents
    if ok:
        tx.status = "COMPLETED"
        tx.mpesa_receipt = receipt
        add_entry(db, user, "WITHDRAW_DONE", "reserved", -tx.amount_cents, tx.id)
    else:
        user.withdrawable_cents += tx.amount_cents
        tx.house_cut_cents = 0                     # failed payout: no fee kept
        tx.status = "FAILED"
        add_entry(db, user, "WITHDRAW_REVERSAL", "withdrawable", tx.amount_cents, tx.id)
    tx.result_desc = desc[:300] or tx.result_desc
    db.commit()
    return "completed" if ok else "failed"


def _find_withdrawal(db: Session, result: dict) -> Transaction | None:
    oid, cid = result.get("OriginatorConversationID"), result.get("ConversationID")
    q = select(Transaction).where(Transaction.type == "WITHDRAWAL")
    tx = db.scalar(q.where(Transaction.originator_conversation_id == oid)) if oid else None
    if tx is None and cid:
        tx = db.scalar(q.where(Transaction.conversation_id == cid))
    return tx


def handle_b2c_result(db: Session, payload: dict) -> str:
    try:
        result = payload["Result"]
        code = int(result["ResultCode"])
    except (KeyError, TypeError, ValueError):
        raise AppError(400, "BAD_PAYLOAD", "Not a valid B2C result.")
    tx = _find_withdrawal(db, result)
    if tx is None:
        return "unknown"
    params = (result.get("ResultParameters") or {}).get("ResultParameter") or []
    receipt = next((p.get("Value") for p in params if p.get("Key") == "TransactionReceipt"), None) \
        or result.get("TransactionID")
    return resolve_withdrawal(db, tx.id, ok=(code == 0), desc=str(result.get("ResultDesc", "")),
                              receipt=str(receipt) if receipt else None)


def handle_b2c_timeout(db: Session, payload: dict) -> str:
    """A queue timeout does NOT mean the money was not sent. Freeze the funds and flag it."""
    result = payload.get("Result") or {}
    tx = _find_withdrawal(db, result)
    if tx is None:
        return "unknown"
    tx = db.execute(select(Transaction).where(Transaction.id == tx.id).with_for_update()
                      .execution_options(populate_existing=True)).scalar_one()
    if tx.status == "PROCESSING":
        tx.status = "NEEDS_REVIEW"
        tx.result_desc = "B2C queue timeout. Verify with Safaricom before refunding."
        db.commit()
        return "needs_review"
    return "duplicate"