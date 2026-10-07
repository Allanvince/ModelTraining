import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError
from app.models import MpesaBalance, Transaction, User, WebhookEvent
from app.money import cents_to_kes
from app.mpesa.daraja import DarajaError
from app.services import pool as pool_svc
from app.services.ledger import add_entry, lock_user

OPEN_WITHDRAWAL = ("PROCESSING", "NEEDS_REVIEW")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def callback_url(kind: str, suffix: str = "") -> str:
    tail = f"/{suffix}" if suffix else ""
    return f"{settings.public_base_url}/api/v1/payments/{kind}/{settings.callback_secret}{tail}"


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


def _credit_deposit(db: Session, tx: Transaction, receipt: str | None, note: str | None = None) -> None:
    user = lock_user(db, tx.user_id)
    house_cut = tx.amount_cents * settings.entry_house_cut_percent // 100
    collateral = tx.amount_cents - house_cut
    user.nonwithdrawable_cents += collateral
    user.has_paid_entry_fee = True
    tx.status = "COMPLETED"
    tx.mpesa_receipt = str(receipt) if receipt else None
    if note:
        tx.result_desc = note[:300]
    add_entry(db, user, "ENTRY_FEE", "nonwithdrawable", collateral, tx.id)
    tx.house_cut_cents = house_cut         # realized profit, tracked on the transaction itself
    db.commit()


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

    _credit_deposit(db, tx, receipt)
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
    if resp.get("OriginatorConversationID"):      # v1: Safaricom assigns its own; the result callback uses it
        tx.originator_conversation_id = resp["OriginatorConversationID"]
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

# ================================================================ reconciliation & M-Pesa tools =====
def _locked_tx(db: Session, tx_id: str) -> Transaction | None:
    return db.execute(select(Transaction).where(Transaction.id == tx_id).with_for_update()
                      .execution_options(populate_existing=True)).scalar_one_or_none()


def _params(result: dict) -> dict:
    items = (result.get("ResultParameters") or {}).get("ResultParameter") or []
    if isinstance(items, dict):
        items = [items]
    return {i.get("Key"): i.get("Value") for i in items}


def reconcile_pending_deposits(db: Session, daraja, *, min_age_s: int = 90, max_age_h: int = 24, limit: int = 20) -> dict:
    """If an STK callback never reached us, ask Safaricom directly (STK Push Query) and settle the deposit."""
    out = {"checked": 0, "completed": 0, "failed": 0, "still_pending": 0, "errors": 0}
    if settings.mpesa_mode == "mock":
        return {**out, "skipped": "mock mode"}
    now = _utcnow()
    rows = db.scalars(select(Transaction).where(
        Transaction.type == "DEPOSIT", Transaction.status == "PENDING",
        Transaction.created_at <= now - timedelta(seconds=min_age_s),
        Transaction.created_at >= now - timedelta(hours=max_age_h),
        Transaction.checkout_request_id.is_not(None)).order_by(Transaction.created_at).limit(limit)).all()
    for row in rows:
        out["checked"] += 1
        try:
            resp = daraja.stk_query(row.checkout_request_id)
        except DarajaError:
            out["errors"] += 1                     # e.g. "still being processed": try again next run
            continue
        code = str(resp.get("ResultCode", "")).strip()
        if code == "" or code == "4999":
            out["still_pending"] += 1
            continue
        tx = _locked_tx(db, row.id)                # re-check under lock: the real callback may have just landed
        if tx is None or tx.status != "PENDING":
            continue
        if code == "0":
            _credit_deposit(db, tx, None, "Confirmed by STK Push Query (callback never arrived).")
            out["completed"] += 1
        else:
            tx.status, tx.result_desc = "FAILED", f"STK query {code}: {resp.get('ResultDesc', '')}"[:300]
            db.commit()
            out["failed"] += 1
    return out


def request_withdrawal_status_check(db: Session, tx_id: str, daraja, receipt: str | None = None) -> Transaction:
    tx = db.get(Transaction, tx_id)
    if tx is None or tx.type != "WITHDRAWAL":
        raise AppError(404, "NOT_FOUND", "Withdrawal not found.")
    if tx.status not in OPEN_WITHDRAWAL:
        raise AppError(409, "NOT_OPEN", "This withdrawal is already settled.")
    try:
        daraja.transaction_status(receipt=(receipt or tx.mpesa_receipt), originator_conversation_id=tx.originator_conversation_id,
                                  result_url=callback_url("txstatus-result", tx.id),
                                  timeout_url=callback_url("txstatus-timeout", tx.id))
    except DarajaError as e:
        raise AppError(502, "MPESA_UNAVAILABLE", f"Safaricom did not accept the status query: {e}")
    tx.result_desc = f"Status check sent {_utcnow():%Y-%m-%d %H:%M} UTC; waiting for Safaricom's answer."
    db.commit()
    return tx


def handle_txstatus_result(db: Session, tx_id: str, payload: dict) -> str:
    """Safaricom's answer to a status check. We only ever auto-COMPLETE (when Safaricom says it was paid and the
    amount matches). We never auto-refund: a human decides, so a payout can't be paid out twice."""
    try:
        result = payload["Result"]
        code = int(result["ResultCode"])
    except (KeyError, TypeError, ValueError):
        raise AppError(400, "BAD_PAYLOAD", "Not a valid status result.")
    tx = _locked_tx(db, tx_id)
    if tx is None or tx.type != "WITHDRAWAL":
        return "unknown"
    if tx.status not in OPEN_WITHDRAWAL:
        return "duplicate"
    params = _params(result)
    status = str(params.get("TransactionStatus", "")).strip().lower()
    if code == 0 and status == "completed":
        amount = params.get("Amount")
        try:
            amount_ok = amount is None or int(round(float(amount))) == tx.amount_kes
        except (TypeError, ValueError):
            amount_ok = False
        if amount_ok:
            receipt = params.get("ReceiptNo") or params.get("TransactionID")
            return resolve_withdrawal(db, tx.id, ok=True, desc="Confirmed paid by Safaricom status check.",
                                      receipt=str(receipt) if receipt else None)
    tx.result_desc = f"Status check answer: code {code}, status '{status or 'n/a'}': {result.get('ResultDesc', '')}"[:300]
    db.commit()
    return "needs_review"


def handle_txstatus_timeout(db: Session, tx_id: str) -> str:
    tx = _locked_tx(db, tx_id)
    if tx is None or tx.status not in OPEN_WITHDRAWAL:
        return "duplicate"
    tx.result_desc = "Status check timed out at Safaricom. Try again, or verify in the M-Pesa Org Portal."
    db.commit()
    return "timeout"


def manual_resolve_withdrawal(db: Session, tx_id: str, action: str, receipt: str | None) -> str:
    """Admin decision after verifying with Safaricom / the Org Portal statement."""
    if action == "complete":
        if not receipt or not receipt.strip():
            raise AppError(422, "RECEIPT_REQUIRED", "Enter the M-Pesa receipt number to mark this paid.")
        res = resolve_withdrawal(db, tx_id, ok=True, desc="Marked paid by admin after verification.", receipt=receipt.strip())
    elif action == "refund":
        res = resolve_withdrawal(db, tx_id, ok=False, desc="Refunded by admin after verification.")
    else:
        raise AppError(422, "BAD_ACTION", "Action must be 'complete' or 'refund'.")
    if res == "duplicate":
        raise AppError(409, "NOT_OPEN", "This withdrawal is already settled.")
    return res


def check_stale_withdrawals(db: Session, daraja, *, stale_minutes: int = 15, recheck_minutes: int = 30, limit: int = 10) -> int:
    """Withdrawals with no result callback after a while: ask Safaricom (read-only; completes only on a confirmed payout)."""
    if settings.mpesa_mode == "mock":
        return 0
    now = _utcnow()
    rows = db.scalars(select(Transaction).where(
        Transaction.type == "WITHDRAWAL", Transaction.status.in_(OPEN_WITHDRAWAL),
        Transaction.created_at <= now - timedelta(minutes=stale_minutes),
        Transaction.updated_at <= now - timedelta(minutes=recheck_minutes)).limit(limit)).all()
    sent = 0
    for t in rows:
        try:
            request_withdrawal_status_check(db, t.id, daraja)
            sent += 1
        except AppError:
            continue
    return sent


# ---------------------------------------------------------------- account balance ----------
def parse_balance(raw: str) -> list[dict]:
    """'Working Account|KES|700000.00|700000.00|0.00|0.00&Utility Account|KES|228037.00|...'"""
    accounts = []
    for part in str(raw or "").split("&"):
        f = part.split("|")
        if len(f) >= 4:
            try:
                accounts.append({"name": f[0].strip(), "currency": f[1].strip(), "current": float(f[2]), "available": float(f[3])})
            except ValueError:
                continue
    return accounts


def _save_balance(db: Session, accounts: list[dict]) -> MpesaBalance:
    pick = next((a for a in accounts if a["name"].lower().startswith("utility")), None) \
        or next((a for a in accounts if a["name"].lower().startswith("working")), None)
    snap = MpesaBalance(shortcode=settings.mpesa_b2c_shortcode or settings.mpesa_shortcode, accounts=accounts,
                        utility_kes=int(pick["available"]) if pick else 0)
    db.add(snap)
    db.commit()
    return snap


def request_balance(db: Session, daraja) -> str:
    if settings.mpesa_mode == "mock":
        _save_balance(db, [{"name": "Utility Account", "currency": "KES", "current": 250000.0, "available": 250000.0},
                           {"name": "Working Account", "currency": "KES", "current": 0.0, "available": 0.0}])
        return "saved"
    try:
        daraja.account_balance(result_url=callback_url("balance-result"), timeout_url=callback_url("balance-timeout"))
    except DarajaError as e:
        raise AppError(502, "MPESA_UNAVAILABLE", f"Safaricom did not accept the balance request: {e}")
    return "requested"          # the figures arrive on the result callback a few seconds later


def handle_balance_result(db: Session, payload: dict) -> str:
    try:
        result = payload["Result"]
        code = int(result["ResultCode"])
    except (KeyError, TypeError, ValueError):
        raise AppError(400, "BAD_PAYLOAD", "Not a valid balance result.")
    if code != 0:
        return "failed"
    accounts = parse_balance(_params(result).get("AccountBalance"))
    if not accounts:
        return "empty"
    _save_balance(db, accounts)
    return "saved"


def latest_balance(db: Session) -> dict | None:
    snap = db.scalar(select(MpesaBalance).order_by(MpesaBalance.created_at.desc()).limit(1))
    if snap is None:
        return None
    return {"takenAt": snap.created_at.isoformat(), "ageMinutes": int((_utcnow() - snap.created_at).total_seconds() // 60),
            "utilityKes": int(snap.utility_kes), "accounts": snap.accounts}