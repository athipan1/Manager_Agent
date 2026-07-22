from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Literal, Optional, Dict, Any, Union, List
import datetime
import re

# Import other data models for the Union
from .trade import (
    AccountBalance, Position, Order, Trade, PortfolioMetrics, CreateOrderResponse
)
from .learning import LearningResponse, LearningResponseBody
from .scanner import ScannerResponseData
from .manager import OrchestratorResponse, MultiOrchestratorResponse

DEFAULT_SCHEMA_VERSION = "1.0"


class StandardAgentData(BaseModel):
    """Standardized data schema for all agents."""
    action: Literal["buy", "sell", "hold"]
    confidence_score: float = Field(..., ge=0, le=1)
    reason: Optional[str] = None
    current_price: Optional[float] = None
    indicators: Optional[Dict[str, Any]] = Field(default_factory=dict)
    # Allow arbitrary extra fields for agent-specific data
    model_config = ConfigDict(extra="allow")


class StandardAgentResponse(BaseModel):
    """
    The standardized and versioned response schema that all agents
    should conform to.

    `schema_version` and `correlation_id` are optional/defaulted here so legacy
    routes can migrate incrementally without breaking existing response objects.
    The public API contract requires new agent-to-agent calls to include both.
    """
    status: Literal["success", "error"]
    agent_type: str
    version: str
    schema_version: str = DEFAULT_SCHEMA_VERSION
    timestamp: datetime.datetime
    correlation_id: Optional[str] = None
    data: Union[
        StandardAgentData,
        AccountBalance,
        Position,
        Order,
        Trade,
        PortfolioMetrics,
        CreateOrderResponse,
        LearningResponse,
        LearningResponseBody,
        ScannerResponseData,
        OrchestratorResponse,
        MultiOrchestratorResponse,
        Dict[str, Any],
        List[Any],
        None
    ] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)

    @field_validator('version')
    @classmethod
    def version_must_be_semantic(cls, v):
        # A simple check for semantic versioning format (e.g., "1.0", "2.1.3")
        parts = v.split('.')
        if not all(part.isdigit() for part in parts):
            raise ValueError('Version must be in semantic format (e.g., "1.0")')
        return v

    @field_validator('schema_version')
    @classmethod
    def schema_version_must_be_semantic(cls, v):
        parts = v.split('.')
        numeric_version = len(parts) >= 2 and all(part.isdigit() for part in parts)
        named_version = re.fullmatch(r"[a-z][a-z0-9-]*\.v[1-9][0-9]*", v) is not None
        if not numeric_version and not named_version:
            raise ValueError(
                'Schema version must be numeric or a named contract (e.g., "profit-decision.v2")'
            )
        return v

    @field_validator('timestamp', mode='before')
    @classmethod
    def parse_timestamp(cls, v):
        if isinstance(v, str):
            try:
                # Handle ISO format strings, replacing Z with +00:00 for fromisoformat
                return datetime.datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                # Fallback to current time if parsing fails
                return datetime.datetime.now(datetime.timezone.utc)
        return v
