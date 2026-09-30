from concurrent.futures import ThreadPoolExecutor

from app.db import SessionLocal
from app.models import Transaction, User
from app.mpesa import fake_payloads as fp
from app.mpesa.daraja import DarajaError, MockDaraja
from app.services import payments
from tests.conftest import CB


def _tx(tx_id):
    with SessionLocal() as db:
        t = db.get(Transaction, tx_id)
        return t.status, t.originator_conversation_id, t.conversation_id, t.amount_kes


def _bal(user_id):
    with SessionLocal() as db:
        u = db.get(User, user_id)
        return u.nonwithdrawable_cents, u.withdrawable_cents, u.reserved_cents


def test_withdraw_reserves_then_completes(client, paid):
    paid.set_balances(w=350)
    r = paid.post("/payments/withdraw", {"amount_usd": 1.00}).json()
    assert r["status"] == "PROCESSING" and r["amountKes"] == 130
    assert _bal(paid.id) == (210, 250, 100)              # moved into reserved, not lost

    status, oid, cid, kes = _tx(r["id"])
    client.post(f"{CB}/b2c-result/test-secret", json=fp.b2c_result(oid, cid, kes, ok=True))
    assert _tx(r["id"])[0] == "COMPLETED" and _bal(paid.id) == (210, 250, 0)
    client.post(f"{CB}/b2c-result/test-secret", json=fp.b2c_result(oid, cid, kes, ok=True))   # duplicate
    assert _bal(paid.id) == (210, 250, 0)


def test_failed_payout_returns_money(client, paid):
    paid.set_balances(w=200)
    r = paid.post("/payments/withdraw", {"amount_usd": 2.00}).json()
    _, oid, cid, kes = _tx(r["id"])
    client.post(f"{CB}/b2c-result/test-secret", json=fp.b2c_result(oid, cid, kes, ok=False))
    assert _tx(r["id"])[0] == "FAILED" and _bal(paid.id) == (210, 200, 0)


def test_timeout_freezes_funds_until_admin_decides(client, paid):
    paid.set_balances(w=200)
    r = paid.post("/payments/withdraw", {"amount_usd": 1.00}).json()
    _, oid, cid, _ = _tx(r["id"])
    client.post(f"{CB}/b2c-timeout/test-secret", json=fp.b2c_timeout(oid, cid))
    assert _tx(r["id"])[0] == "NEEDS_REVIEW" and _bal(paid.id) == (210, 100, 100)   # NOT auto-refunded

    assert client.post(f"/api/v1/admin/transactions/{r['id']}/resolve", json={"outcome": "FAILED"}).status_code == 403
    ok = client.post(f"/api/v1/admin/transactions/{r['id']}/resolve", json={"outcome": "FAILED"},
                     headers={"X-Admin-Token": "test-admin"})
    assert ok.json()["result"] == "failed" and _bal(paid.id) == (210, 200, 0)


def test_late_success_after_timeout_still_settles(client, paid):
    paid.set_balances(w=100)
    r = paid.post("/payments/withdraw", {"amount_usd": 1.00}).json()
    _, oid, cid, kes = _tx(r["id"])
    client.post(f"{CB}/b2c-timeout/test-secret", json=fp.b2c_timeout(oid, cid))
    client.post(f"{CB}/b2c-result/test-secret", json=fp.b2c_result(oid, cid, kes, ok=True))
    assert _tx(r["id"])[0] == "COMPLETED" and _bal(paid.id) == (210, 0, 0)


def test_minimum_and_insufficient_funds(paid):
    paid.set_balances(w=100)
    assert paid.post("/payments/withdraw", {"amount_usd": 0.10}).json()["error"]["code"] == "BELOW_MINIMUM"
    assert paid.post("/payments/withdraw", {"amount_usd": 5.00}).json()["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert _bal(paid.id) == (210, 100, 0)


def test_idempotency_key_prevents_double_withdrawal(paid):
    paid.set_balances(w=300)
    h = {"Idempotency-Key": "abc-123"}
    a = paid.post("/payments/withdraw", {"amount_usd": 1.00}, headers=h).json()
    b = paid.post("/payments/withdraw", {"amount_usd": 1.00}, headers=h).json()
    assert a["id"] == b["id"] and _bal(paid.id) == (210, 200, 100)


def test_immediate_rejection_reverses_but_unknown_outcome_does_not(paid):
    class Rejects(MockDaraja):
        def b2c(self, **kw): raise DarajaError("rejected", definitive=True)

    class Unknown(MockDaraja):
        def b2c(self, **kw): raise DarajaError("read timeout", definitive=False)

    paid.set_balances(w=300)
    with SessionLocal() as db:
        t1 = payments.request_withdrawal(db, paid.id, 100, None, Rejects())
        assert t1.status == "FAILED"
    assert _bal(paid.id) == (210, 300, 0)
    with SessionLocal() as db:
        t2 = payments.request_withdrawal(db, paid.id, 100, None, Unknown())
        assert t2.status == "NEEDS_REVIEW"
    assert _bal(paid.id) == (210, 200, 100)


def test_concurrent_withdrawals_never_overspend(paid):
    paid.set_balances(w=300)                             # enough for exactly three $1.00 payouts

    def attempt(_):
        with SessionLocal() as db:
            try:
                payments.request_withdrawal(db, paid.id, 100, None, MockDaraja())
                return True
            except Exception:
                return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(attempt, range(10)))
    assert sum(results) == 3
    assert _bal(paid.id) == (210, 0, 300)
