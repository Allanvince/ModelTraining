from app.mpesa import fake_payloads as fp
from tests.conftest import CB


def test_deposit_success_credits_once(client, player):
    d = player.post("/payments/deposit").json()
    assert d["status"] == "PENDING" and d["amountKes"] == 390
    assert player.get(f"/payments/status/{d['checkoutRequestId']}").json()["status"] == "PENDING"

    body = fp.stk_success(d["checkoutRequestId"], 390)
    assert client.post(f"{CB}/stk-callback/test-secret", json=body).status_code == 200
    me = player.me()
    # $3.00 entry fee splits into a 30% house cut (kept, never at risk) and 70% collateral the
    # player can actually lose/play with.
    assert me["hasPaidEntryFee"] and me["balances"]["nonWithdrawableCents"] == 210
    assert player.get(f"/payments/status/{d['checkoutRequestId']}").json()["status"] == "SUCCESS"

    for _ in range(3):                                   # Safaricom retries / duplicates
        assert client.post(f"{CB}/stk-callback/test-secret", json=body).status_code == 200
    assert player.me()["balances"]["nonWithdrawableCents"] == 210      # still $2.10, not $8.40


def test_second_deposit_request_reuses_pending_prompt(player):
    a = player.post("/payments/deposit").json()
    b = player.post("/payments/deposit").json()
    assert a["checkoutRequestId"] == b["checkoutRequestId"]


def test_user_cancelled_prompt_fails_without_credit(client, player):
    d = player.post("/payments/deposit").json()
    client.post(f"{CB}/stk-callback/test-secret", json=fp.stk_failure(d["checkoutRequestId"]))
    assert player.get(f"/payments/status/{d['checkoutRequestId']}").json()["status"] == "FAILED"
    me = player.me()
    assert not me["hasPaidEntryFee"] and me["balances"]["totalCents"] == 0


def test_amount_mismatch_is_held_for_review_not_credited(client, player):
    d = player.post("/payments/deposit").json()
    client.post(f"{CB}/stk-callback/test-secret", json=fp.stk_success(d["checkoutRequestId"], 10))
    assert player.get(f"/payments/status/{d['checkoutRequestId']}").json()["status"] == "REVIEW"
    assert player.me()["balances"]["totalCents"] == 0


def test_bad_secret_rejected_and_unknown_id_acknowledged(client):
    assert client.post(f"{CB}/stk-callback/wrong", json=fp.stk_failure("x")).status_code == 403
    assert client.post(f"{CB}/stk-callback/test-secret", json=fp.stk_failure("ws_CO_nope")).status_code == 200


def test_malformed_callback_is_400(client):
    assert client.post(f"{CB}/stk-callback/test-secret", json={"hello": "world"}).status_code == 400


def test_cannot_read_someone_elses_payment(client, player):
    from tests.conftest import Player
    d = player.post("/payments/deposit").json()
    other = Player(client)
    assert other.get(f"/payments/status/{d['checkoutRequestId']}").status_code == 404


def test_sandbox_style_repeated_receipt_still_credits_every_player(client):
    """Safaricom's sandbox reuses the same fixed example receipt (NLJ7RT61SV) across unrelated
    transactions - unlike production, which guarantees uniqueness. A second, unrelated player's
    deposit must still be credited even though the receipt number collides with someone else's."""
    from tests.conftest import Player

    a, b = Player(client), Player(client)
    for pl in (a, b):
        d = pl.post("/payments/deposit").json()
        r = client.post(f"{CB}/stk-callback/test-secret", json=fp.stk_success(d["checkoutRequestId"], d["amountKes"]))
        assert r.status_code == 200

    assert a.me()["hasPaidEntryFee"] and a.me()["balances"]["nonWithdrawableCents"] == 210
    assert b.me()["hasPaidEntryFee"] and b.me()["balances"]["nonWithdrawableCents"] == 210