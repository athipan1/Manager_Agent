
import httpx
from typing import Dict, Optional

from pydantic import BaseModel, Field

from .config_manager import config_manager
from .database_client import DatabaseAgentClient
from .logger import report_logger
from .models import PortfolioMetrics, Trade

# --- Pydantic Models for Outgoing API Contract (to Auto-Learning Agent) ---


class LearningRequestConfig(BaseModel):
    """Represents the current configuration of the trading system."""

    agent_weights: Dict[str, float]
    risk_per_trade: float


class LearningRequest(BaseModel):
    """The complete input data structure for the /learn endpoint."""

    symbol: str
    trade_history: list[Trade]
    portfolio_metrics: PortfolioMetrics
    config: LearningRequestConfig


# --- Pydantic Models for Incoming API Contract (from Auto-Learning Agent) ---


class LearningResponse(BaseModel):
    """The complete output data structure from the /learn endpoint."""

    learning_state: str
    agent_weight_adjustments: Dict[str, float] = Field(default_factory=dict)
    risk_adjustments: Dict[str, float] = Field(default_factory=dict)
    reasoning: list[str] = Field(default_factory=list)


# --- Pydantic Models for Internal Orchestrator Contract ---


class PolicyDeltas(BaseModel):
    """Represents the recommended adjustments to the system's policy."""

    agent_weights: Optional[Dict[str, float]] = None
    risk_per_trade: Optional[float] = None


class AutoLearningResponseBody(BaseModel):
    """The expected JSON response for the orchestrator's internal logic."""

    learning_state: str = Field(..., description="e.g., 'warmup', 'learning'")
    version: str
    policy_deltas: PolicyDeltas


# --- Client Logic ---


class AutoLearningAgentClient:
    """
    An adapter client for interacting with the Auto-Learning Agent.
    It handles the impedance mismatch between the Orchestrator's internal
    data model and the external Learning Agent's API contract.
    """

    def __init__(
        self,
        db_client: DatabaseAgentClient,
        timeout: int = 20,
    ):
        self.base_url = config_manager.get("AUTO_LEARNING_AGENT_URL")
        self.db_client = db_client
        self.timeout = timeout
        self.version = "1.0.0"  # Version of this adapter's contract

    async def trigger_learning_cycle(
        self,
        account_id: int,
        symbol: str,
        correlation_id: str,
    ) -> Optional[AutoLearningResponseBody]:
        """
        Gathers all necessary data, calls the learning agent, and translates
        the response into the format expected by the Orchestrator's ConfigManager.

        Args:
            account_id: The account to analyze.
            symbol: The ticker symbol related to the recent trade.
            correlation_id: The ID for request tracing.

        Returns:
            An AutoLearningResponseBody object if successful, otherwise None.
        """
        if not self.base_url:
            report_logger.warning(
                "AUTO_LEARNING_AGENT_URL is not configured. Skipping learning cycle."
            )
            return None

        try:
            # 1. Gather data from Database Agent
            trade_history = await self.db_client.get_trade_history(
                account_id,
                correlation_id,
            )
            portfolio_metrics = await self.db_client.get_portfolio_metrics(
                account_id,
                correlation_id,
            )

            # 2. Get current configuration from ConfigManager
            current_config = LearningRequestConfig(
                agent_weights=config_manager.get("AGENT_WEIGHTS"),
                risk_per_trade=config_manager.get("RISK_PER_TRADE"),
            )

            # 3. Construct the request payload for the learning agent
            request_payload = LearningRequest(
                symbol=symbol,
                trade_history=trade_history,
                portfolio_metrics=portfolio_metrics,
                config=current_config,
            )

            # 4. Make the API call
            url = f"{self.base_url}/learn"
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=request_payload.model_dump(),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                learning_response = LearningResponse.model_validate(response.json())

            report_logger.info(
                f"Learning agent returned adjustments: {learning_response.reasoning}",
            )

            # 5. Translate the response into the Orchestrator's internal format
            policy_deltas = PolicyDeltas(
                agent_weights=learning_response.agent_weight_adjustments,
                risk_per_trade=learning_response.risk_adjustments.get("risk_per_trade"),
            )

            return AutoLearningResponseBody(
                learning_state=learning_response.learning_state,
                version=self.version,
                policy_deltas=policy_deltas,
            )

        except httpx.TimeoutException:
            report_logger.warning(
                f"Timeout while calling Auto-Learning Agent at {self.base_url}/learn"
            )
            return None
        except httpx.RequestError as e:
            report_logger.warning(
                f"An error occurred while requesting {e.request.url!r}: {e!r}"
            )
            return None
        except Exception as e:
            # Catches validation errors or other unexpected issues
            report_logger.error(
                f"Failed to process response from Auto-Learning Agent: {e}"
            )
            return None
