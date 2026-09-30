from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    dev_mode: bool = False

    database_url: str = "sqlite:///./quickiq.db"
    jwt_secret: str = "dev-only-secret-change-me-in-production-0123456789"
    jwt_ttl_hours: int = 168
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Public URL Safaricom can reach (ngrok URL while developing).
    public_base_url: str = "http://localhost:8000"
    callback_secret: str = "dev-callback-secret"      # secret path segment on webhooks
    callback_ip_allowlist: str = ""                   # comma separated; empty = off
    admin_token: str = "dev-admin-token"

    # M-Pesa / Daraja
    mpesa_mode: str = "mock"                          # "mock" | "sandbox"
    mpesa_base_url: str = "https://sandbox.safaricom.co.ke"
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_shortcode: str = "174379"
    mpesa_passkey: str = ""
    mpesa_initiator_name: str = "testapi"
    mpesa_initiator_password: str = ""
    mpesa_cert_path: str = ""
    mpesa_security_credential: str = ""       # optional: paste Safaricom's ready-made sandbox value directly,
                                               # skipping the .cer download + local RSA encryption entirely
    mpesa_b2c_command: str = "BusinessPayment"

    # Game economics (all money is stored as integer USD cents)
    kes_per_usd: int = 130
    entry_fee_cents: int = 300
    reward_cents: int = 50
    penalty_cents: int = 50
    min_withdraw_cents: int = 50
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


settings = Settings()
