from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ScannerCandidate(BaseModel):
    symbol: str
    recommendation: Optional[str] = None
    confidence_score: Optional[float] = None
    fundamental_score: Optional[float] = None
    technical_score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ScannerResponseData(BaseModel):
    candidates: List[ScannerCandidate]
    scan_type: str
    count: int
