import os
import tempfile

# Must be set BEFORE the app is imported.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["MPESA_MODE"] = "mock"
os.environ["CALLBACK_SECRET"] = "test-secret"
os.environ["ADMIN_TOKEN"] = "test-admin"
os.environ["LLM_API_KEY"] = ""

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import clock  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app, seed_questions  # noqa: E402
from app.models import GameSession, Question, User  # noqa: E402
from app.mpesa import fake_payloads as fp  # noqa: E402

CB = "/api/v1/payments"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed_questions()
    clock.reset()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class Player:
    def __init__(self, client):
        self.c = client
        n = uuid.uuid4().hex[:8]
        r = client.post("/api/v1/auth/register", json={"username": f"p_{n}", "email": f"{n}@t.co",
                                                       "phone": "254712345678", "password": "password123"})
        assert r.status_code == 201, r.text
        self.token = r.json()["token"]
        self.id = r.json()["user"]["userId"]
        self.h = {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw): return self.c.get(f"/api/v1{url}", headers=self.h, **kw)
    def post(self, url, json=None, headers=None): return self.c.post(f"/api/v1{url}", json=json, headers={**self.h, **(headers or {})})
    def me(self): return self.get("/me").json()

    def pay_entry_fee(self):
        d = self.post("/payments/deposit").json()
        r = self.c.post(f"{CB}/stk-callback/test-secret", json=fp.stk_success(d["checkoutRequestId"], d["amountKes"]))
        assert r.status_code == 200
        return d

    def set_balances(self, n=None, w=None):
        with SessionLocal() as db:
            u = db.get(User, self.id)
            if n is not None: u.nonwithdrawable_cents = n
            if w is not None: u.withdrawable_cents = w
            db.commit()


@pytest.fixture
def player(client):
    return Player(client)


@pytest.fixture
def paid(player):
    player.pay_entry_fee()
    return player


def fund_pool(client, usd):
    r = client.post("/api/v1/admin/pool/fund", json={"amount_usd": usd}, headers={"X-Admin-Token": "test-admin"})
    assert r.status_code == 200, r.text
    return r.json()


def pool_balance_cents():
    from app.models import Pool
    with SessionLocal() as db:
        p = db.get(Pool, 1)
        return p.balance_cents if p else 0


def correct_display_idx(session_id, question_id):
    """Test-only peek at the DB to find the right answer (the API never reveals it before answering)."""
    with SessionLocal() as db:
        s = db.get(GameSession, session_id)
        step = next(p for p in s.plan if p["q"] == question_id)
        return step["perm"].index(db.get(Question, question_id).correct_idx)
