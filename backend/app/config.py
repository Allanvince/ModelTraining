from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    dev_mode: bool = False

    database_url: str = "sqlite:///./quickiq.db"
    jwt_secret: str = "dev-only-secret-change-me-in-production-0123456789"
    jwt_ttl_hours: int = 168
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Public URL Safaricom can reach (ngrok URL while developing)
    public_base_url: str = "http://localhost:8000"
    callback_secret: str = "dev-callback-secret"      # secret path segment on webhooks
    callback_ip_allowlist: str = ""                   # comma separated; empty = off
    admin_token: str = "dev-admin-token"
    cron_secret: str = ""                             # Vercel Cron sends "Authorization: Bearer <CRON_SECRET>"

    # M-Pesa / Daraja
    mpesa_mode: str = "mock"                          # "mock" | "sandbox" | "production"
    mpesa_base_url: str = "https://sandbox.safaricom.co.ke"
    mpesa_consumer_key: str = "1wVmcuSXqlss88GYASdsSt68ziQva7FQb8Kk5ak5S4w5F6he"
    mpesa_consumer_secret: str = "RwIM019uDXPl7HS22X6ZDwLZlCTrcZUIYZ7LDrHuAppaDGt4r77eXGLqmjxGlJgQ"
    mpesa_shortcode: str = "7113627"                   # STK push BusinessShortCode. Buy Goods: your Head Office / store number
    mpesa_transaction_type: str = "CustomerBuyGoodsOnline"   # Buy Goods till: "CustomerBuyGoodsOnline"
    mpesa_party_b: str = "5074393"                           # Buy Goods: your TILL number. Empty = same as mpesa_shortcode
    mpesa_b2c_shortcode: str = ""                     # B2C payouts come from this shortcode. Empty = mpesa_shortcode
    mpesa_passkey: str = "32c11fc99ab90c7560b12b882fbaf7be189708917c571a40fbb3ad9cc0fad0f7"
    mpesa_initiator_name: str = "testapi"
    mpesa_initiator_password: str = ""
    mpesa_cert_path: str = ""
    mpesa_security_credential: str = ""       # optional: paste Safaricom's ready-made sandbox value directly,
                                               # skipping the .cer download + local RSA encryption entirely
    mpesa_b2c_command: str = "BusinessPayment"
    mpesa_b2c_path: str = "/mpesa/b2c/v1/paymentrequest"   # your production approval lists v1; use /v3/ only if Safaricom enabled it

    # Game economics (all money is stored as integer USD cents)
    kes_per_usd: int = 130
    entry_fee_cents: int = 300
    reward_cents: int = 50
    penalty_cents: int = 50
    min_withdraw_cents: int = 50
    withdraw_fee_percent: float = 3.0 
    questions_per_round: int = 10
    grace_ms: int = 1200

    # Pooled payouts: correct answers earn points; points convert to cash from a shared pool at
    # round end, capped by what the pool can afford. Wrong answers still cost real money instantly
    # and that money funds the pool. Structurally the pool can never go negative.
    points_per_correct: int = 10
    point_value_cents: int = 5                        # 10 pts * 5c = 50c/correct at full pool health
    entry_house_cut_percent: int = 30                 # kept as realized profit, not put at risk
    pool_settlement_fraction_percent: int = 50         # never pay out more than this % of the pool at once

    # LLM (optional)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"
    required_test_rounds: int = 3

    @model_validator(mode="after")
    def _safety_checks(self):
        if self.mpesa_mode not in ("mock", "sandbox", "production"):
            raise ValueError("MPESA_MODE must be mock, sandbox or production")
        live_url = "api.safaricom.co.ke" in self.mpesa_base_url
        if self.mpesa_mode == "sandbox" and live_url:
            raise ValueError("MPESA_MODE=sandbox but MPESA_BASE_URL is the LIVE API")
        if self.mpesa_mode == "production" and not live_url:
            raise ValueError("MPESA_MODE=production but MPESA_BASE_URL is not https://api.safaricom.co.ke")
        if self.dev_mode:
            return self
        # ---- DEV_MODE=false means "production rules": refuse to boot with anything unsafe
        problems = [n for n, v in {"JWT_SECRET": self.jwt_secret, "ADMIN_TOKEN": self.admin_token,
                                   "CALLBACK_SECRET": self.callback_secret}.items() if v.startswith("dev")]
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL is SQLite")
        if self.mpesa_mode == "mock":
            problems.append("MPESA_MODE=mock")
        if self.mpesa_mode == "production":
            if not (self.mpesa_consumer_key and self.mpesa_consumer_secret and self.mpesa_passkey):
                problems.append("missing M-Pesa consumer key/secret/passkey")
            if self.mpesa_shortcode == "174379":
                problems.append("MPESA_SHORTCODE is still the sandbox test shortcode")
            if self.mpesa_transaction_type == "CustomerBuyGoodsOnline" and not self.mpesa_party_b:
                problems.append("MPESA_PARTY_B (till number) is required for Buy Goods")
            if self.mpesa_initiator_name == "testapi":
                problems.append("MPESA_INITIATOR_NAME is still the sandbox value")
            if not (self.mpesa_security_credential or (self.mpesa_cert_path and self.mpesa_initiator_password)):
                problems.append("no B2C security credential configured")
            if not self.cron_secret:
                problems.append("CRON_SECRET is not set (needed for payment reconciliation)")
            if not self.public_base_url.startswith("https://"):
                problems.append("PUBLIC_BASE_URL must be https")
        if problems:
            raise ValueError("Unsafe production config: " + "; ".join(problems))
        return self


settings = Settings()