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
    review_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    production_candidates: List[Any] = Field(default_factory=list)
    research_candidates: List[Any] = Field(default_factory=list)
    lane_summary: Dict[str, Any] = Field(default_factory=dict)

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

    @staticmethod
    def _candidate_dict(candidate: Any) -> Dict[str, Any]:
        if isinstance(candidate, dict):
            return dict(candidate)
        if hasattr(candidate, "model_dump"):
            dumped = candidate.model_dump(mode="json")
            return dict(dumped) if isinstance(dumped, dict) else {}
        return {}

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

        # Scanner_Agent has a dedicated research_candidates lane. Older Manager
        # versions silently dropped that field and the hourly Shadow workflow only
        # consumed review_candidates, which could reduce Shadow observations to zero.
        # Preserve the native lane and mirror it into controlled REVIEW rows without
        # granting any Risk/Execution authority. This is idempotent across repeated
        # Pydantic model_validate/model_dump round trips in scanner_client.py.
        existing_research_symbols = {
            str(row.get("symbol") or row.get("ticker") or "").strip().upper()
            for row in self.review_candidates
            if isinstance(row, dict) and row.get("research_lane_eligible") is True
        }
        for candidate in self.research_candidates:
            row = self._candidate_dict(candidate)
            symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
            if not symbol or symbol in existing_research_symbols:
                continue
            row["symbol"] = symbol
            row["decision"] = "REVIEW"
            row["allowed"] = False
            row["reason_code"] = "SCANNER_NATIVE_RESEARCH_SHADOW"
            row["reason"] = (
                "Scanner native research candidate is Shadow-only and cannot "
                "proceed to automated entry."
            )
            row["workflow_failure"] = False
            row["research_lane_eligible"] = True
            row["controlled_no_trade"] = True
            row["broker_order_authorized"] = False
            row["risk_approval_allowed"] = False
            row["execution_agent_allowed"] = False
            row["lane_source"] = "scanner_native_research"
            self.review_candidates.append(row)
            existing_research_symbols.add(symbol)
        return self
