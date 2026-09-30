from app import clock
from tests.conftest import CB, Player, correct_display_idx, fund_pool, pool_balance_cents


def start(p, category="tech"):
    r = p.post("/game/start", {"category": category})
    assert r.status_code == 201, r.text
    return r.json()["sessionId"]


def play_one(p, sid, want_correct=True):
    q = p.post(f"/game/{sid}/next").json()
    idx = correct_display_idx(sid, q["questionId"])
    choice = idx if want_correct else (idx + 1) % 4
    return q, p.post(f"/game/{sid}/answer", {"question_id": q["questionId"], "choice": choice}).json()


def test_must_pay_before_playing(player):
    r = player.post("/game/start", {"category": "tech"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "PAYMENT_REQUIRED"


def test_question_payload_never_leaks_the_answer(paid):
    sid = start(paid)
    q = paid.post(f"/game/{sid}/next").json()
    assert set(q) >= {"questionId", "text", "options", "timerMs"} and len(q["options"]) == 4
    assert not any("correct" in k.lower() for k in q)


def test_perfect_round_earns_points_and_pool_pays_out(client, paid):
    fund_pool(client, 10.00)                              # pool healthy: full rate is payable
    sid = start(paid)
    for _ in range(10):
        q, a = play_one(paid, sid, True)
        assert a["correct"] and a["pointsEarned"] == 10 and a["deltaCents"] == 0   # no instant cash
    s = a["summary"]
    assert s["correct"] == 10 and s["pointsEarned"] == 100
    assert s["payoutTargetCents"] == 500 and s["payoutCents"] == 500 and not s["throttled"]
    b = paid.me()["balances"]
    assert (b["nonWithdrawableCents"], b["withdrawableCents"]) == (210, 500)


def test_payout_is_throttled_when_the_pool_is_thin(client, paid):
    fund_pool(client, 1.00)                               # only $1.00 in the pool; 50% settlement -> $0.50 budget
    sid = start(paid)
    for _ in range(10):
        _, a = play_one(paid, sid, True)
    s = a["summary"]
    assert s["payoutTargetCents"] == 500 and s["payoutCents"] == 50 and s["throttled"]
    assert paid.me()["balances"]["withdrawableCents"] == 50
    assert pool_balance_cents() == 50                      # $1.00 - $0.50 paid out


def test_wrong_answer_drains_collateral_and_funds_the_pool(paid):
    assert pool_balance_cents() == 0
    sid = start(paid)
    _, a = play_one(paid, sid, False)
    assert a["reason"] == "WRONG" and a["deltaCents"] == -50 and a["pointsEarned"] == 0
    b = paid.me()["balances"]
    assert (b["nonWithdrawableCents"], b["withdrawableCents"]) == (160, 0)   # 210 - 50
    assert pool_balance_cents() == 50                       # the penalty funded the pool


def test_late_answer_is_rejected_even_if_correct(paid):
    sid = start(paid)
    q = paid.post(f"/game/{sid}/next").json()
    clock.advance(q["timerMs"] + 1300)                  # past timer + 1200 ms grace
    idx = correct_display_idx(sid, q["questionId"])
    a = paid.post(f"/game/{sid}/answer", {"question_id": q["questionId"], "choice": idx}).json()
    assert a["correct"] is False and a["reason"] == "TIMEOUT" and a["deltaCents"] == -50 and a["pointsEarned"] == 0


def test_answer_inside_grace_window_counts(paid):
    sid = start(paid)
    q = paid.post(f"/game/{sid}/next").json()
    clock.advance(q["timerMs"] + 800)                   # network lag, still inside grace
    idx = correct_display_idx(sid, q["questionId"])
    a = paid.post(f"/game/{sid}/answer", {"question_id": q["questionId"], "choice": idx}).json()
    assert a["correct"] is True and a["pointsEarned"] == 10 and a["deltaCents"] == 0


def test_refreshing_does_not_reset_the_timer(paid):
    sid = start(paid)
    q1 = paid.post(f"/game/{sid}/next").json()
    clock.advance(2000)
    q2 = paid.post(f"/game/{sid}/next").json()          # player "refreshes"
    assert q2["questionId"] == q1["questionId"]
    assert 0 < q1["timerMs"] - 2000 - q2["remainingMs"] + 200 < 400      # ~1s left, not a fresh timer
    clock.advance(q1["timerMs"] + 1500)                 # walks away past the deadline
    q3 = paid.post(f"/game/{sid}/next").json()
    assert q3["questionId"] != q1["questionId"] and q3["index"] == 2
    assert paid.me()["balances"]["totalCents"] == 160   # 210 collateral - the skipped question's $0.50


def test_cannot_answer_twice_or_out_of_order(paid):
    sid = start(paid)
    q, _ = play_one(paid, sid, True)
    again = paid.post(f"/game/{sid}/answer", {"question_id": q["questionId"], "choice": 0})
    assert again.status_code == 409


def test_other_player_cannot_touch_my_session(client, paid):
    sid = start(paid)
    other = Player(client)
    assert other.post(f"/game/{sid}/next").status_code == 404


def test_zero_balance_locks_account_until_top_up(client, paid):
    paid.set_balances(n=50, w=0)
    sid = start(paid)
    play_one(paid, sid, False)
    me = paid.me()
    assert me["balances"]["totalCents"] == 0 and me["isAccountLocked"]
    assert paid.post("/game/start", {"category": "tech"}).json()["error"]["code"] == "ACCOUNT_LOCKED"

    d = paid.post("/payments/deposit").json()
    from app.mpesa import fake_payloads as fp
    client.post(f"{CB}/stk-callback/test-secret", json=fp.stk_success(d["checkoutRequestId"], d["amountKes"]))
    me = paid.me()
    assert me["balances"]["totalCents"] == 210 and not me["isAccountLocked"]
    assert paid.post("/game/start", {"category": "tech"}).status_code == 201


def test_custom_category_falls_back_to_sample_bank_without_llm_key(paid):
    r = paid.post("/game/start", {"category": "custom", "topic": "1990s Anime Trivia"}).json()
    assert r["questionSource"] == "sample_bank" and r["total"] == 10


def test_leaderboard_appears_after_a_full_round(paid, client):
    sid = start(paid)
    for _ in range(10):
        play_one(paid, sid, True)
    top = client.get("/api/v1/leaderboard").json()
    assert top and top[0]["handle"].startswith("@")


def test_websocket_leaderboard_pushes_initial_state(client):
    with client.websocket_connect("/api/v1/ws/leaderboard") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "leaderboard" and isinstance(msg["top"], list)


def test_admin_pool_fund_requires_admin_token(client):
    r = client.post("/api/v1/admin/pool/fund", json={"amount_usd": 5.00})
    assert r.status_code == 403
    ok = client.post("/api/v1/admin/pool/fund", json={"amount_usd": 5.00}, headers={"X-Admin-Token": "test-admin"})
    assert ok.status_code == 200 and ok.json()["balanceCents"] == 500


def test_public_pool_endpoint_reflects_funding_and_payouts(client, paid):
    assert client.get("/api/v1/pool").json()["balanceCents"] == 0
    fund_pool(client, 2.00)
    assert client.get("/api/v1/pool").json()["balanceCents"] == 200
    sid = start(paid)
    for _ in range(10):
        play_one(paid, sid, True)
    p = client.get("/api/v1/pool").json()
    assert p["balanceCents"] == 100 and p["lifetimeFundedCents"] == 200 and p["lifetimePaidCents"] == 100


def test_pool_never_goes_negative_under_adversarial_play(client):
    """The core guarantee: however many skilled players grind however many rounds, the pool can never
    be asked to pay out more than it holds. No admin funding here - only wrong-answer penalties feed it,
    so this also proves the pool can't be forced negative by correct-answer payouts alone."""
    import random as _random

    players = [Player(client) for _ in range(8)]
    for pl in players:
        pl.pay_entry_fee()

    for _ in range(15):
        for pl in players:
            sid = start(pl, category=_random.choice(["tech", "science", "pop", "history"]))
            for _ in range(10):
                q = pl.post(f"/game/{sid}/next").json()
                if q.get("finished"):
                    break
                idx = correct_display_idx(sid, q["questionId"])
                # adversarially skilled: right 92% of the time
                choice = idx if _random.random() < 0.92 else (idx + 1) % 4
                pl.post(f"/game/{sid}/answer", {"question_id": q["questionId"], "choice": choice})
            assert pool_balance_cents() >= 0        # checked after every single round settles
            if pl.me()["balances"]["totalCents"] <= 0:
                pl.pay_entry_fee()                   # keep grinding instead of stopping

    assert pool_balance_cents() >= 0
