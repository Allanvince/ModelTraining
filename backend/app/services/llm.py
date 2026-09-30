"""Optional LLM question generation for custom categories (any OpenAI-compatible API: Groq, DeepSeek...)."""
import json

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import settings


class GenQuestion(BaseModel):
    text: str = Field(min_length=8, max_length=300)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_idx: int = Field(ge=0, le=3)

    @field_validator("options")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        cleaned = [o.strip() for o in v]
        if any(not o for o in cleaned) or len({o.lower() for o in cleaned}) != 4:
            raise ValueError("options must be 4 distinct non-empty strings")
        return cleaned


class GenSet(BaseModel):
    questions: list[GenQuestion]


PROMPT = ("Write {n} multiple-choice trivia questions about: {topic}. Each question must have exactly 4 short options, "
          "exactly one of them correct, and be answerable in under 5 seconds by a fan. Use only facts you are certain "
          'about. Reply with JSON only: {{"questions":[{{"text":"...","options":["a","b","c","d"],"correct_idx":0}}]}}')


def generate_questions(topic: str, n: int) -> list[dict] | None:
    """Returns validated questions, or None when no LLM key is configured."""
    if not settings.llm_api_key:
        return None
    body = {"model": settings.llm_model, "temperature": 0.6, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "You are a careful trivia writer. Output valid JSON only."},
                         {"role": "user", "content": PROMPT.format(n=n, topic=topic)}]}
    last_err = None
    for _ in range(2):                                              # one retry on bad output
        try:
            r = httpx.post(f"{settings.llm_base_url}/chat/completions", json=body, timeout=30,
                           headers={"Authorization": f"Bearer {settings.llm_api_key}"})
            r.raise_for_status()
            parsed = GenSet.model_validate(json.loads(r.json()["choices"][0]["message"]["content"]))
            if len(parsed.questions) >= n:
                return [{"text": q.text, "options": q.options, "correct_idx": q.correct_idx, "timer_seconds": 4}
                        for q in parsed.questions[:n]]
            last_err = "too few questions"
        except (httpx.HTTPError, ValueError, KeyError, ValidationError) as e:
            last_err = str(e)
    raise RuntimeError(f"LLM generation failed: {last_err}")
