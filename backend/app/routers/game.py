from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Question
from app.services import game
from pydantic import BaseModel

from pydantic import BaseModel

from app.errors import AppError
from app.models import User
from app.security import current_user
from app.config import settings
from app.services import ledger


router = APIRouter(tags=["game"])

class StartBody(BaseModel):
    category: str
    topic: str | None = None


class AnswerBody(BaseModel):
    question_id: str
    choice: int

CATEGORY_META = {
    "tech": {
        "name": "Technology",
        "description": "Networking protocols, software engineering, systems architecture, and core algorithms.",
        "difficulty": "Medium",
        "sample": "What does HTTP status code 404 signify?"
    },
    "science": {
        "name": "Science",
        "description": "Physics, cell biology, astronomical phenomena, and chemical interactions.",
        "difficulty": "Hard",
        "sample": "What is the chemical symbol for gold?"
    },
    "pop": {
        "name": "Pop Culture",
        "description": "Blockbuster cinema, chart-topping albums, gaming lore, and iconic media.",
        "difficulty": "Easy",
        "sample": "Which artist released the album 'Renaissance' in 2022?"
    },
    "history": {
        "name": "History",
        "description": "Pivotal revolutions, ancient civilizations, global conflicts, and historic leaders.",
        "difficulty": "Medium",
        "sample": "In which year did Kenya gain independence?"
    },
    "custom": {
        "name": "AI Custom Topic",
        "description": "Generate on-demand custom topic rounds using artificial intelligence.",
        "difficulty": "Adaptive",
        "sample": "Prompt-tailored questions tailored to your custom input."
    }
}

@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = db.execute(select(Question.category, func.count()).group_by(Question.category)).all()
    
    result = []
    for cat_id, count in rows:
        meta = CATEGORY_META.get(cat_id, {
            "name": cat_id.title(),
            "description": "Test your knowledge in this category.",
            "difficulty": "Medium",
            "sample": "Trivia question teaser."
        })
        result.append({
            "id": cat_id,
            "questions": count,
            **meta
        })

    # Include AI custom category option if not already generated from DB
    if not any(item["id"] == "custom" for item in result):
        result.append({
            "id": "custom",
            "questions": 10,
            **CATEGORY_META["custom"]
        })

    return result

@router.post("/game/start")
def start(body: StartBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.category == "custom":
        raise AppError(501, "CUSTOM_NOT_AVAILABLE", "Custom topics are not available yet.")
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

@router.post("/dev/topup")
def dev_topup(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not settings.dev_mode:                      # add `dev_mode: bool = False` to Settings
        raise AppError(404, "NOT_FOUND", "Not found.")
    u = ledger.lock_user(db, user.id)
    house_cut = settings.entry_fee_cents * settings.entry_house_cut_percent // 100
    collateral = settings.entry_fee_cents - house_cut
    u.nonwithdrawable_cents += collateral
    u.has_paid_entry_fee = True
    ledger.add_entry(db, u, "ENTRY_FEE", "nonwithdrawable", collateral, ref="dev-topup")
    db.commit()
    return {"ok": True}