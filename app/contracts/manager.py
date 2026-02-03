from pydantic import BaseModel
from typing import Optional, List
import datetime

class ReportDetail(BaseModel):
    action: str
    score: float
    reason: str

class ReportDetails(BaseModel):
    technical: Optional[ReportDetail] = None
    fundamental: Optional[ReportDetail] = None

class OrchestratorResponse(BaseModel):
    report_id: str
    ticker: str
    timestamp: datetime.datetime
    final_verdict: str
    status: str
    details: ReportDetails

class AnalysisResult(BaseModel):
    """The outcome of the analysis phase for a single asset."""
    ticker: str
    final_verdict: str
    status: str
    details: ReportDetails

class ExecutionResult(BaseModel):
    """The outcome of the execution phase for a single asset."""
    status: str
    reason: Optional[str] = None
    details: Optional[dict] = None

class AssetResult(BaseModel):
    """Combines the analysis and execution results for a single asset."""
    analysis: AnalysisResult
    execution: ExecutionResult

class ExecutionSummary(BaseModel):
    """Summarizes the overall execution status."""
    total_trades_approved: int
    total_trades_executed: int
    total_trades_failed: int

class MultiOrchestratorResponse(BaseModel):
    """Response model for the multi-asset analysis endpoint."""
    multi_report_id: str
    timestamp: datetime.datetime
    execution_summary: ExecutionSummary
    results: List[AssetResult]
