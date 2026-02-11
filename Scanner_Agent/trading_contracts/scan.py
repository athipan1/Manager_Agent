from typing import List, Optional
from pydantic import BaseModel

class CandidateResult(BaseModel):
    symbol: str
    confidence_score: Optional[float] = None
    recommendation: Optional[str] = None

class ScannerResult(BaseModel):
    scan_type: str
    count: int
    candidates: List[CandidateResult]
