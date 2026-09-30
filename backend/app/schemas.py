from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_]+$")
    email: EmailStr
    phone: str = Field(pattern=r"^254[17]\d{8}$")          # 2547XXXXXXXX / 2541XXXXXXXX
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class StartGameIn(BaseModel):
    category: str = Field(min_length=2, max_length=60)      # tech | science | pop | history | custom
    topic: str | None = Field(default=None, max_length=60)  # only used when category == "custom"


class AnswerIn(BaseModel):
    question_id: str
    choice: int = Field(ge=-1, le=3)                        # -1 = client-side timeout


class WithdrawIn(BaseModel):
    amount_usd: float = Field(gt=0, le=1000)


class ResolveIn(BaseModel):
    outcome: str = Field(pattern="^(COMPLETED|FAILED)$")


class FundPoolIn(BaseModel):
    amount_usd: float = Field(gt=0, le=100000)
