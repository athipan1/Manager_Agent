from pydantic import BaseModel, Field, model_validator
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

    @model_validator(mode='before')
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            required_fields = ["candidates", "scan_type", "count"]
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                raise ValueError(f"Scanner response missing required fields: {', '.join(missing_fields)}")
        return data
