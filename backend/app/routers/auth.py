from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import User
from app.schemas import LoginIn, RegisterIn
from app.security import create_token, current_user, hash_password, verify_password
from app.services.game import balances

router = APIRouter(tags=["auth"])


def serialize_user(u: User) -> dict:
    n = u.answers_total
    return {"userId": u.id, "username": u.username, "handle": "@" + u.username, "email": u.email, "phone": u.phone,
            "hasPaidEntryFee": u.has_paid_entry_fee, "isAccountLocked": u.has_paid_entry_fee and u.total_cents <= 0,
            "balances": balances(u),
            "stats": {"gamesPlayed": u.games_played, "passRatePercent": round(100 * u.answers_correct / n, 1) if n else 0,
                      "avgResponseMs": round(u.response_ms_total / n) if n else 0,
                      "currentStreak": u.current_streak, "bestStreak": u.best_streak}}


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    taken = db.scalar(select(User).where(or_(User.email == body.email.lower(), User.username == body.username)))
    if taken:
        raise AppError(409, "ALREADY_EXISTS", "That email or username is already registered.")
    u = User(username=body.username, email=body.email.lower(), phone=body.phone,
             password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    return {"token": create_token(u.id), "user": serialize_user(u)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if not u or not verify_password(body.password, u.password_hash):
        raise AppError(401, "BAD_CREDENTIALS", "Email or password is incorrect.")
    return {"token": create_token(u.id), "user": serialize_user(u)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return serialize_user(user)
