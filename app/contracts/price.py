from pydantic import BaseModel

class PricePoint(BaseModel):
    """Represents a single price point in history."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
