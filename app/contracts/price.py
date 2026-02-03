from pydantic import BaseModel
import datetime

class PricePoint(BaseModel):
    """Represents a single price point in history."""
    timestamp: datetime.datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
