# app/services/game_2.py (or app/services/game.py)
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.errors import AppError
from app.models import GameSession, Question, SessionAnswer, User
from app.services import ledger
from app.services import pool as pool_svc

# The 'Surprise Mix' card (id 'custom') draws from these hidden categories.
MIX_ID = "custom"
MIX_CATEGORIES = ["geography", "sports", "music", "nature", "kenya"]

_lb_version = 0          # bumped whenever a round finishes; the websocket watches it


def lb_version() -> int:
    return _lb_version


def _bump() -> None:
    global _lb_version
    _lb_version += 1


def balances(u: User) -> dict:
    return {"nonWithdrawableCents": u.nonwithdrawable_cents, "withdrawableCents": u.withdrawable_cents,
            "reservedCents": u.reserved_cents, "totalCents": u.total_cents,
            "nonWithdrawable": u.nonwithdrawable_cents / 100, "withdrawable": u.withdrawable_cents / 100,
            "total": u.total_cents / 100}


def _lock_session(db: Session, session_id: str, user_id: str) -> GameSession:
    s = db.execute(select(GameSession).where(GameSession.id == session_id).with_for_update()
                   .execution_options(populate_existing=True)).scalar_one_or_none()
    if s is None or s.user_id != user_id:
        raise AppError(404, "SESSION_NOT_FOUND", "Game session not found.")
    return s


def start_session(db: Session, user_id: str, category: str, generated: list[dict] | None = None) -> GameSession:
    user = ledger.lock_user(db, user_id)
    if not user.has_paid_entry_fee:
        raise AppError(402, "PAYMENT_REQUIRED", "Pay the $3.00 entry fee to start playing.")
    if user.total_cents <= 0:
        raise AppError(403, "ACCOUNT_LOCKED", "Account Balance Depleted ($0.00). Top up $3.00 via M-Pesa to continue.")

    is_test = user.tests_completed < settings.required_test_rounds

    for old in db.scalars(select(GameSession).where(GameSession.user_id == user_id, GameSession.status == "ACTIVE")):
        old.status = "ABANDONED"

    chosen = []
    if generated:
        chosen = [Question(category=category, **q) for q in generated]
        db.add_all(chosen)
        db.flush()
    else:
        # Surprise Mix pulls from several categories; every other card uses just its own.
        pool_cats = MIX_CATEGORIES if category == MIX_ID else [category]
        bank = list(db.scalars(select(Question).where(Question.category.in_(pool_cats))))
        if not bank:
            raise AppError(404, "UNKNOWN_CATEGORY", f"No questions for category '{category}'.")

        # How many times has this player already answered each of these questions (in any round)?
        seen_counts = dict(db.execute(
            select(SessionAnswer.question_id, func.count())
            .join(GameSession, SessionAnswer.session_id == GameSession.id)
            .where(GameSession.user_id == user_id, SessionAnswer.question_id.in_([q.id for q in bank]))
            .group_by(SessionAnswer.question_id)
        ).all())

        # Least-seen first; random shuffle beforehand means ties (and the category mix) are random every time.
        random.shuffle(bank)
        bank.sort(key=lambda q: seen_counts.get(q.id, 0))
        chosen = bank[:settings.questions_per_round]
        random.shuffle(chosen)

    plan = [{"q": q.id, "perm": random.sample(range(4), 4)} for q in chosen]   # shuffle options per player[cite: 15]
    s = GameSession(user_id=user_id, category=category, plan=plan, start_balance_cents=user.total_cents, is_test=is_test)
    db.add(s)
    db.commit()
    return s


def _question_payload(db: Session, s: GameSession, index: int) -> dict:
    step = s.plan[index]
    q = db.get(Question, step["q"])
    return {"sessionId": s.id, "questionId": q.id, "index": index + 1, "total": len(s.plan), "text": q.text,
            "options": [q.options[p] for p in step["perm"]],       # NEVER includes the correct index[cite: 15]
            "timerMs": q.timer_seconds * 1000}


def _record(db: Session, s: GameSession, user: User, pool, *, chosen: int, correct: bool, reason: str,
            delta_ms: int, timer_ms: int) -> tuple[int, int, int]:
    response_ms = min(delta_ms, timer_ms)
    step = s.plan[s.answered_count]
    if correct:
        points, change = settings.points_per_correct, 0
    else:
        points = 0
        change = ledger.apply_penalty(db, user, ref=s.id)
        pool_svc.fund(db, pool, -change, ref=s.id)
    db.add(SessionAnswer(session_id=s.id, question_id=step["q"], chosen_idx=chosen, correct=correct, reason=reason,
                         delta_ms=delta_ms, response_ms=response_ms, cents=change, points=points))
    s.answered_count += 1
    s.correct_count += int(correct)
    s.points_earned += points
    s.total_ms += response_ms
    s.net_cents += change
    s.dispatched_at_ms = None
    user.answers_total += 1
    user.answers_correct += int(correct)
    user.response_ms_total += response_ms
    if correct:
        user.current_streak += 1
        user.best_streak = max(user.best_streak, user.current_streak)
    else:
        user.current_streak = 0
    return change, points, response_ms


def _finish(db, s, user):
    s.status = "FINISHED"
    pool = pool_svc.lock_pool(db)
    if s.is_test:
        target, paid = 0, 0
        user.tests_completed += 1          # only FINISHED rounds count; abandoned ones don't
    else:
        target, paid = pool_svc.settle(db, pool, s.points_earned, ref=s.id)
    s.payout_target_cents = target
    s.payout_cents = paid
    s.pool_balance_after_cents = pool.balance_cents
    s.net_cents += paid
    ledger.credit_payout(db, user, paid, ref=s.id)
    user.games_played += 1
    _bump()


def summary(s: GameSession, user: User) -> dict:
    n = len(s.plan)
    return {"sessionId": s.id, "category": s.category, "correct": s.correct_count, "total": n,
            "accuracyPercent": round(100 * s.correct_count / n) if n else 0, "totalMs": s.total_ms,
            "pointsEarned": s.points_earned, "payoutTargetCents": s.payout_target_cents,
            "payoutCents": s.payout_cents, "payoutTarget": s.payout_target_cents / 100,
            "payout": s.payout_cents / 100, "throttled": s.status == "FINISHED" and s.payout_cents < s.payout_target_cents,
            "poolBalanceAfterCents": s.pool_balance_after_cents,
            "netCents": s.net_cents, "net": s.net_cents / 100, "balances": balances(user),
            "isAccountLocked": user.total_cents <= 0}


def next_question(db: Session, user_id: str, session_id: str) -> dict:
    s = _lock_session(db, session_id, user_id)
    user = ledger.lock_user(db, user_id)
    if s.status != "ACTIVE":
        return {"finished": True, "summary": summary(s, user)}

    if s.dispatched_at_ms is not None:
        step = s.plan[s.answered_count]
        q = db.get(Question, step["q"])
        timer_ms = q.timer_seconds * 1000
        elapsed = clock.now_ms() - s.dispatched_at_ms
        if elapsed <= timer_ms + settings.grace_ms:
            payload = _question_payload(db, s, s.answered_count)
            payload["remainingMs"] = max(0, timer_ms - elapsed)
            return payload
        pool = pool_svc.lock_pool(db)
        _record(db, s, user, pool, chosen=-1, correct=False, reason="TIMEOUT", delta_ms=elapsed, timer_ms=timer_ms)
        if s.answered_count >= len(s.plan):
            _finish(db, s, user)
            db.commit()
            return {"finished": True, "summary": summary(s, user)}

    s.dispatched_at_ms = clock.now_ms()
    db.commit()
    payload = _question_payload(db, s, s.answered_count)
    payload["remainingMs"] = payload["timerMs"]
    return payload


def answer(db: Session, user_id: str, session_id: str, question_id: str, choice: int) -> dict:
    s = _lock_session(db, session_id, user_id)
    user = ledger.lock_user(db, user_id)
    if s.status != "ACTIVE":
        raise AppError(409, "SESSION_CLOSED", "This round is over.")
    if s.dispatched_at_ms is None or s.plan[s.answered_count]["q"] != question_id:
        raise AppError(409, "NOT_CURRENT", "That question is not open (already answered or not sent yet).")
    if not -1 <= choice <= 3:
        raise AppError(422, "BAD_CHOICE", "Choice must be 0-3 (or -1 for a client-side timeout).")

    step = s.plan[s.answered_count]
    q = db.get(Question, question_id)
    timer_ms = q.timer_seconds * 1000
    delta = clock.now_ms() - s.dispatched_at_ms
    correct_display = step["perm"].index(q.correct_idx)

    if choice == -1 or delta > timer_ms + settings.grace_ms:
        correct, reason = False, "TIMEOUT"
    else:
        correct = step["perm"][choice] == q.correct_idx
        reason = "CORRECT" if correct else "WRONG"

    pool = pool_svc.lock_pool(db)
    change, points, response_ms = _record(db, s, user, pool, chosen=choice, correct=correct, reason=reason,
                                          delta_ms=delta, timer_ms=timer_ms)
    finished = s.answered_count >= len(s.plan)
    if finished:
        _finish(db, s, user)
    db.commit()
    return {"correct": correct, "reason": reason, "correctIdx": correct_display, "responseMs": response_ms,
            "pointsEarned": points, "deltaCents": change, "delta": change / 100, "balances": balances(user),
            "streak": user.current_streak, "finished": finished, "summary": summary(s, user) if finished else None}


def review(db: Session, user_id: str, session_id: str) -> dict:
    """Questions the player got wrong (or timed out on) in a finished round."""
    s = _lock_session(db, session_id, user_id)
    if s.status != "FINISHED":
        raise AppError(409, "NOT_FINISHED", "Finish the round to see your review.")
    answers = {a.question_id: a for a in db.scalars(select(SessionAnswer).where(SessionAnswer.session_id == s.id))}
    wrong = []
    for i, step in enumerate(s.plan):
        a = answers.get(step["q"])
        if a is None or a.correct:
            continue
        q = db.get(Question, step["q"])
        perm = step["perm"]
        wrong.append({"number": i + 1, "text": q.text, "options": [q.options[p] for p in perm],
                      "yourIdx": a.chosen_idx if a.chosen_idx >= 0 else None,
                      "correctIdx": perm.index(q.correct_idx), "timedOut": a.reason == "TIMEOUT"})
    return {"total": len(s.plan), "wrong": wrong}


def get_summary(db: Session, user_id: str, session_id: str) -> dict:
    s = _lock_session(db, session_id, user_id)
    return summary(s, db.get(User, user_id))


def leaderboard(db: Session, limit: int = 10) -> list[dict]:
    avg = User.response_ms_total * 1.0 / User.answers_total
    rows = db.scalars(select(User).where(User.answers_total >= 10).order_by(avg.asc()).limit(limit))
    return [{"rank": i + 1, "handle": "@" + u.username, "avgMs": round(u.response_ms_total / u.answers_total),
             "bestStreak": u.best_streak} for i, u in enumerate(rows)]