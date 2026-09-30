# QuickIQ backend (MVP)

FastAPI + SQLAlchemy. Runs on SQLite with **no accounts and no keys** (M-Pesa is mocked), so you can verify
the whole system locally, then switch on the real Daraja sandbox.

Needs Python 3.10+.

## 1. Set up (VS Code terminal)

```bash
python -m venv .venv
# macOS/Linux:  source .venv/bin/activate      Windows:  .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

## 2. Verify it works

```bash
python -m pytest -q                # 32 tests: idempotent callbacks, refunds, races, anti-cheat timing,
                                     # a 32-round adversarial stress test proving the pool never goes negative
python -m scripts.pool_economics    # the CURRENT model: pooled, delayed-cashout payouts (read this one)
python -m scripts.economics         # kept for comparison: the earlier "instant $0.50/$0.50" model, which loses money
```

```bash
uvicorn app.main:app --reload            # terminal 1  -> http://localhost:8000/docs
python -m scripts.demo_flow              # terminal 2  -> register, pay, play, withdraw
```

`/docs` is an interactive API page. Register, click **Authorize** with the token, and try the endpoints.

## 3. Endpoints (all under /api/v1)

| Area | Endpoint |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /me` |
| Deposit | `POST /payments/deposit` (STK Push), `GET /payments/status/{checkoutRequestId}` (poll every 2s) |
| Webhooks | `POST /payments/stk-callback/{secret}`, `/b2c-result/{secret}`, `/b2c-timeout/{secret}` |
| Withdraw | `POST /payments/withdraw` (send an `Idempotency-Key` header), `GET /payments/transactions` |
| Game | `POST /game/start`, `POST /game/{id}/next`, `POST /game/{id}/answer`, `GET /game/{id}/summary` |
| Pool | `GET /pool` (public), `POST /admin/pool/fund` (seed with working capital) |
| Other | `GET /categories`, `GET /leaderboard`, `WS /ws/leaderboard`, `GET /health` |

Game loop the frontend follows: `start` -> (`next` -> show question -> `answer`) x 10.
Call `next` only after your feedback animation, because the server clock starts when `next` is served.
**Correct answers earn points only** (`pointsEarned` in the `answer` response) - no cash moves yet.
**Wrong/timeout answers cost real cash immediately** (`deltaCents`), taken from withdrawable first, then
collateral, and that cash funds the shared pool right away. Only when the round finishes does `summary`
report `payoutCents` - what the pool actually paid for those points, which may be less than
`payoutTarget` if the pool is thin (`throttled: true`).

## 4. Real Daraja sandbox (when you are ready)

1. Create an app at developer.safaricom.co.ke and copy the Consumer Key/Secret, the test Passkey and the Sandbox certificate.
2. `ngrok http 8000`, then set `PUBLIC_BASE_URL` in `.env` to the https ngrok URL.
3. Set `MPESA_MODE=sandbox` plus the `MPESA_*` values in `.env`, and restart the server.
4. `POST /payments/deposit` now sends a real sandbox prompt, and Safaricom posts to your ngrok URL.

## 5. The reward model: pooled payouts, delayed cash-out

The $3.00 unlock splits into a **house cut** (kept immediately, `ENTRY_HOUSE_CUT_PERCENT`, default 30%)
and **collateral** (the rest, non-withdrawable, at risk). Correct answers earn **points**
(`POINTS_PER_CORRECT`), shown live in the UI, but no cash moves yet. Wrong/timeout answers cost real
cash immediately (withdrawable first, then collateral) and that cash funds a shared **pool**. At the
end of each round, a player's points convert to cash out of the pool at up to `POINT_VALUE_CENTS` per
point, capped at `POOL_SETTLEMENT_FRACTION_PERCENT` of whatever the pool currently holds - so payouts
throttle down automatically when the pool is thin, instead of the house ever owing more than it has.

This is the standard mechanic behind pooled/parimutuel prize games, and it's what makes the model safe
regardless of how skilled players get: `python -m scripts.pool_economics` shows the house staying
solidly profitable from 50% up to a brutal 99% average accuracy, and `tests/test_game.py::test_pool_never_goes_negative_under_adversarial_play`
proves it under a stress test of 8 players deliberately playing at 92% accuracy for 15 rounds each.

**Cold-start note:** the pool starts at $0.00. Your first good players won't get much until enough other
players have lost money into it. Seed it with working capital via `POST /admin/pool/fund` at launch.

## 6. Where this differs from the blueprint (and why)

- **No Redis for now.** The dispatch timestamp lives on the game-session row. One server instance doesn't need Redis;
  add it when you run several instances or need pub/sub at scale. The leaderboard websocket is in-process.
- **Money is integer USD cents**, never floats. Every change is also written to an append-only `ledger_entries`
  table (and the pool's own inflows/outflows to `pool_ledger_entries`).
- **Callback URLs contain a secret** (Safaricom does not sign callbacks), plus an optional IP allowlist. Raw callbacks are stored.
- **B2C timeout does not auto-refund.** A queue timeout can still end in a payout, so funds stay reserved as
  `NEEDS_REVIEW` until the real result arrives or an admin resolves it.
- **Options are shuffled per player**, and refreshing never restarts a question's timer.

## 7. Before real money (not covered by code)

- Legal: Kenya's Gambling Control Act 2025 and the 2026 licensing regulations. Get a Kenyan lawyer's read on whether a paid-entry cash-reward quiz needs a licence.
- Economics: run `scripts.pool_economics` with your real `.env` values before launch, and re-run it whenever you change
  `POINT_VALUE_CENTS`, `ENTRY_HOUSE_CUT_PERCENT`, or `POOL_SETTLEMENT_FRACTION_PERCENT`.
- Safaricom production: a live paybill/B2C shortcode, Go-Live approval, and the production certificate.
- LLM questions: never pay out on unverified AI-written answers. Curate the bank, or add a second-model check.
- Postgres: set `DATABASE_URL=postgresql://...` and `pip install psycopg2-binary`. Row locks (`FOR UPDATE`) then apply.
