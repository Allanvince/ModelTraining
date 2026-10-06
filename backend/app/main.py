import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.errors import AppError
from app.models import Question
from app.routers import admin, auth, game, misc, payments


def seed_questions() -> None:
    """Runs on every startup. questions.json is the source of truth:
    new questions are added, and existing ones (matched by text) get their timer/options updated."""
    data = json.loads((Path(__file__).parent / "data" / "questions.json").read_text(encoding="utf-8"))
    with SessionLocal() as db:
        existing = {q.text: q for q in db.scalars(select(Question))}
        for q in data:
            row = existing.get(q["text"])
            if row is None:
                db.add(Question(**q))
            else:
                row.timer_seconds = q["timer_seconds"]
                row.category = q["category"]
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    seed_questions()
    yield


app = FastAPI(title="QuickIQ API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(AppError)
async def app_error_handler(_: Request, e: AppError):
    return JSONResponse(status_code=e.status, content={"error": {"code": e.code, "message": e.message}})


for r in (auth.router, payments.router, game.router, misc.router, admin.router):
    app.include_router(r, prefix="/api/v1")