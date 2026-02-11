from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ScanRequest(BaseModel):
    symbols: Optional[List[str]] = Field(default=None, description="A list of stock symbols to scan. Defaults to a predefined list if empty.")

class Candidate(BaseModel):
    symbol: str
    recommendation: str
    details: Dict[str, Any]

class ErrorDetail(BaseModel):
    symbol: str
    error: str

# Internal models for Fundamental analysis results
class QualityMetrics(BaseModel):
    roe: Optional[float]
    roa: Optional[float]
    debt_to_equity: Optional[float]
    free_cash_flow: Optional[float]
    profit_margins: Optional[float]
    score: Optional[float]

class GrowthMetrics(BaseModel):
    revenue_cagr: Optional[float]
    eps_growth: Optional[float]
    score: Optional[float]

class ValuationMetrics(BaseModel):
    pe_ratio: Optional[float]
    peg_ratio: Optional[float]
    pb_ratio: Optional[float]
    score: Optional[float]

class FundamentalCandidate(BaseModel):
    symbol: str
    grade: str
    fundamental_score: float
    quality: QualityMetrics
    growth: GrowthMetrics
    valuation: ValuationMetrics
    thesis: str
