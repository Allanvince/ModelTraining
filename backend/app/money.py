from app.config import settings


def cents_to_kes(cents: int) -> int:
    """USD cents -> whole KES (M-Pesa only accepts whole shillings). Rounds down."""
    return cents * settings.kes_per_usd // 100


def usd(cents: int) -> float:
    return round(cents / 100, 2)
