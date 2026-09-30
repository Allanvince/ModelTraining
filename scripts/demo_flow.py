"""End-to-end walkthrough against a RUNNING server in mock mode.

    terminal 1:  uvicorn app.main:app --reload
    terminal 2:  python -m scripts.demo_flow

It plays the part of the phone, of Safaricom (posting callbacks) and of the player.
"""
import os
import random
import sys
import time
import uuid

import httpx

from app.config import settings
from app.mpesa import fake_payloads as fp

BASE = os.getenv("BASE_URL", "http://localhost:8000")
API = f"{BASE}/api/v1"
c = httpx.Client(timeout=15)


def step(title): print(f"\n=== {title}")
def money(cents): return f"{'-' if cents < 0 else ''}${abs(cents) / 100:.2f}"


SKILL = float(os.getenv("SKILL", "0.75"))      # chance this demo player "knows" the answer


def pick_choice(session_id, question_id):
    """Demo shortcut: the API never reveals answers, so we peek in the local DB to simulate a player
    who knows ~SKILL of the answers. A real client obviously cannot do this."""
    from app.db import SessionLocal
    from app.models import GameSession, Question
    with SessionLocal() as db:
        s = db.get(GameSession, session_id)
        step_ = next(p for p in s.plan if p["q"] == question_id)
        right = step_["perm"].index(db.get(Question, question_id).correct_idx)
    return right if random.random() < SKILL else (right + random.randint(1, 3)) % 4


def call(method, path, token=None, headers=None, **kw):
    headers = {**({"Authorization": f"Bearer {token}"} if token else {}), **(headers or {})}
    r = c.request(method, f"{API}{path}", headers=headers, **kw)
    return r.status_code, r.json()


try:
    print("health:", c.get(f"{API}/health").json())
except httpx.HTTPError:
    sys.exit("Server not reachable. Start it first:  uvicorn app.main:app --reload")

n = uuid.uuid4().hex[:6]
step("1. Register (account exists, but is locked behind the entry fee)")
_, r = call("POST", "/auth/register", json={"username": f"demo_{n}", "email": f"demo_{n}@example.com",
                                            "phone": "254712345678", "password": "password123"})
token = r["token"]
print("hasPaidEntryFee:", r["user"]["hasPaidEntryFee"])
code, r = call("POST", "/game/start", token, json={"category": "tech"})
print("try to play before paying ->", code, r["error"]["code"])

step("2. Pay $3.00 (KES 390) via STK Push (30% kept by the house, 70% becomes at-risk collateral)")
_, dep = call("POST", "/payments/deposit", token)
print("prompt sent:", dep["message"], "| checkoutRequestId:", dep["checkoutRequestId"])
print("status right after prompt:", call("GET", f"/payments/status/{dep['checkoutRequestId']}", token)[1]["status"])
print("...user enters PIN, Safaricom calls our webhook (posting exactly what Daraja would)...")
cb = f"{API}/payments/stk-callback/{settings.callback_secret}"
body = fp.stk_success(dep["checkoutRequestId"], dep["amountKes"])
c.post(cb, json=body)
c.post(cb, json=body)                       # Safaricom retry: must NOT double-credit
print("status after callback:", call("GET", f"/payments/status/{dep['checkoutRequestId']}", token)[1]["status"])
_, me = call("GET", "/me", token)
print("balance after TWO identical callbacks:", money(me["balances"]["totalCents"]), "(should be $3.00)")

step("2b. Seed the prize pool (admin only - real launches need working capital up front)")
_, p0 = call("POST", "/admin/pool/fund", json={"amount_usd": 20.00}, headers={"X-Admin-Token": settings.admin_token})
print("pool balance:", money(p0["balanceCents"]))

step("3. Play a round (correct = points now, not instant cash; wrong = instant cost, funds the pool)")
_, g = call("POST", "/game/start", token, json={"category": "tech"})
sid = g["sessionId"]
while True:
    _, q = call("POST", f"/game/{sid}/next", token)
    if q.get("finished"):
        break
    print(f"Q{q['index']}/{q['total']} ({q['timerMs'] // 1000}s) {q['text']}")
    time.sleep(random.uniform(0.3, 1.2))
    _, a = call("POST", f"/game/{sid}/answer", token,
                json={"question_id": q["questionId"], "choice": pick_choice(sid, q["questionId"])})
    tag = f"+{a['pointsEarned']}pts" if a["correct"] else f"{a['deltaCents']:+d}c"
    print(f"    -> {a['reason']:7} {a['responseMs']}ms  {tag:8} balance {money(a['balances']['totalCents'])}")
    if a["finished"]:
        s = a["summary"]
        print(f"\nRound over: {s['correct']}/{s['total']} correct, {s['accuracyPercent']}%, {s['totalMs']} ms | "
              f"{s['pointsEarned']} pts -> pool paid {money(s['payoutCents'])} of a possible {money(s['payoutTargetCents'])}"
              f"{' (throttled - pool was thin)' if s['throttled'] else ''} | net {money(s['netCents'])}")
        break

_, pf = call("GET", "/pool")
print("pool balance after the round:", money(pf["balanceCents"]))

step("4. Anti-cheat: answer a question after its deadline")
_, g = call("POST", "/game/start", token, json={"category": "science"}) if call("GET", "/me", token)[1]["balances"]["totalCents"] > 0 else (0, None)
if g:
    _, q = call("POST", f"/game/{g['sessionId']}/next", token)
    wait = q["timerMs"] / 1000 + settings.grace_ms / 1000 + 0.3
    print(f"sleeping {wait:.1f}s (timer {q['timerMs']}ms + {settings.grace_ms}ms grace) then answering...")
    time.sleep(wait)
    _, a = call("POST", f"/game/{g['sessionId']}/answer", token, json={"question_id": q["questionId"], "choice": 0})
    print("result:", a["reason"], a["deltaCents"], "cents")

step("5. Withdraw earnings via M-Pesa B2C")
_, me = call("GET", "/me", token)
w = me["balances"]["withdrawableCents"]
print("withdrawable:", money(w))
if w >= settings.min_withdraw_cents:
    amt = min(w, 100) / 100
    code, wd = call("POST", "/payments/withdraw", token, json={"amount_usd": amt},
                    headers={"Idempotency-Key": uuid.uuid4().hex})
    print(f"withdraw ${amt:.2f} ->", wd["status"], "| reserved:", money(wd["balances"]["reservedCents"]))
    print("...Safaricom finishes the payout and posts the B2C result...")
    from app.db import SessionLocal
    from app.models import Transaction
    with SessionLocal() as db:                       # demo shortcut: read ids our server generated
        tx = db.get(Transaction, wd["id"])
        oid, cid, kes = tx.originator_conversation_id, tx.conversation_id, tx.amount_kes
    c.post(f"{API}/payments/b2c-result/{settings.callback_secret}", json=fp.b2c_result(oid, cid, kes, ok=True))
    _, txs = call("GET", "/payments/transactions", token)
    print("transactions:", [(t["type"], t["status"], money(t["amountCents"])) for t in txs])
    _, me = call("GET", "/me", token)
    print("final balances:", {k: money(v) for k, v in me["balances"].items() if k.endswith("Cents")})
else:
    print("Not enough earnings to withdraw this time. Run again, or raise SKILL (e.g. SKILL=0.9).")
