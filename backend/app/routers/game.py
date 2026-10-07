from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import Question, User
from app.security import current_user
from app.config import settings
from app.services import game, ledger

router = APIRouter(tags=["game"])


class StartBody(BaseModel):
    category: str
    topic: str | None = None      # no longer used; kept so older clients don't break.


class AnswerBody(BaseModel):
    question_id: str
    choice: int


CATEGORY_META = {
    "tech": {"name": "Technology", "description": "Internet basics, software, gadgets and how computers work.",
             "difficulty": "Medium", "sample": "What does HTTP status code 404 signify?"},
    "science": {"name": "Science", "description": "Space, the human body, chemistry and everyday physics.",
                "difficulty": "Hard", "sample": "What is the chemical symbol for gold?"},
    "pop": {"name": "Pop Culture", "description": "Movies, music, games and the people everyone is talking about.",
            "difficulty": "Easy", "sample": "Which artist released the album 'Renaissance' in 2022?"},
    "history": {"name": "History", "description": "Big events, ancient civilizations, and leaders who changed the world.",
                "difficulty": "Medium", "sample": "In which year did Kenya gain independence?"},
    "anime": {"name": "Anime", "description": "Heroes, studios and classic series from the world of anime.",
              "difficulty": "Medium", "sample": "Who is the main hero of Dragon Ball Z?"},
    game.MIX_ID: {"name": "Surprise Mix", "description": "A random mix from geography, sports, music, nature and Kenya.",
                  "difficulty": "Mixed", "sample": "Every round is a different mix."},
}


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = dict(db.execute(select(Question.category, func.count()).group_by(Question.category)).all())
    result = []
    for cat_id, count in rows.items():
        if cat_id in game.MIX_CATEGORIES or cat_id == game.MIX_ID:
            continue                          # pool categories are only reachable through Surprise Mix
        meta = CATEGORY_META.get(cat_id, {"name": cat_id.title(), "description": "Test your knowledge in this category.",
                                          "difficulty": "Medium", "sample": "Quick questions to test your knowledge."})
        result.append({"id": cat_id, "questions": count, **meta})
    mix_count = sum(rows.get(c, 0) for c in game.MIX_CATEGORIES)
    if mix_count:
        result.append({"id": game.MIX_ID, "questions": mix_count, **CATEGORY_META[game.MIX_ID]})
    return result


@router.post("/game/start")
def start(body: StartBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = game.start_session(db, user.id, body.category)
    return {"sessionId": s.id}


@router.post("/game/{session_id}/next")
def next_question(session_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return game.next_question(db, user.id, session_id)


@router.post("/game/{session_id}/answer")
def answer(session_id: str, body: AnswerBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return game.answer(db, user.id, session_id, body.question_id, body.choice)


@router.get("/game/{session_id}/summary")
def get_summary(session_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return game.get_summary(db, user.id, session_id)


@router.get("/game/{session_id}/review")
def get_review(session_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return game.review(db, user.id, session_id)


@router.post("/dev/topup")
def dev_topup(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not settings.dev_mode:
        raise AppError(404, "NOT_FOUND", "Not found.")
    u = ledger.lock_user(db, user.id)
    house_cut = settings.entry_fee_cents * settings.entry_house_cut_percent // 100
    collateral = settings.entry_fee_cents - house_cut
    u.nonwithdrawable_cents += collateral
    u.has_paid_entry_fee = True
    ledger.add_entry(db, u, "ENTRY_FEE", "nonwithdrawable", collateral, ref="dev-topup")
    db.commit()
    return {"ok": True}