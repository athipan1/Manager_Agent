from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any


class ScannerCandidate(BaseModel):
    symbol: str
    recommendation: Optional[str] = None
    confidence_score: Optional[float] = None
    fundamental_score: Optional[float] = None
    technical_score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ScannerCandidateContract(BaseModel):
    symbol: str
    source_agent: str = "Scanner_Agent"
    candidate_score: Optional[float] = None
    discovery_rank: Optional[int] = None
    recommendation_hint: str = "WATCHLIST"
    exchange: Optional[str] = None
    screener: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    raw_scores: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_legacy_candidate(self) -> ScannerCandidate:
        return ScannerCandidate(
            symbol=self.symbol,
            recommendation=self.recommendation_hint,
            confidence_score=self.candidate_score,
            metadata={
                "source_agent": self.source_agent,
                "discovery_rank": self.discovery_rank,
                "exchange": self.exchange,
                "screener": self.screener,
                "tags": self.tags,
                "reasons": self.reasons,
                "raw_scores": self.raw_scores,
                **self.metadata,
            },
        )


class ScannerResponseData(BaseModel):
    candidates: List[Any]
    scan_type: str
    count: int
    metadata: Dict[str, Any] = Field(default_factory=dict)
    errors: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def validate_required_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            required_fields = ["candidates", "scan_type", "count"]
            missing_fields = [
                field for field in required_fields if field not in data
            ]
            if missing_fields:
                raise ValueError(
                    "Scanner response missing required fields: "
                    + ", ".join(missing_fields)
                )
        return data

    @model_validator(mode="after")
    def normalize_candidates(self):
        normalized = []
        for candidate in self.candidates:
            if isinstance(candidate, ScannerCandidate):
                normalized.append(candidate)
                continue
            if isinstance(candidate, ScannerCandidateContract):
                normalized.append(candidate.to_legacy_candidate())
                continue
            if isinstance(candidate, dict):
                if (
                    "candidate_score" in candidate
                    or "recommendation_hint" in candidate
                ):
                    normalized.append(
                        ScannerCandidateContract.model_validate(
                            candidate
                        ).to_legacy_candidate()
                    )
                else:
                    normalized.append(
                        ScannerCandidate.model_validate(candidate)
                    )
                continue
            normalized.append(candidate)
        self.candidates = normalized
        return self
