
import httpx
from typing import Dict, Optional, List, Any

from pydantic import BaseModel, Field

from .config_manager import config_manager
from .database_client import DatabaseAgentClient
from .logger import report_logger
from .models import Trade

# --- Pydantic Models for Outgoing API Contract (to Learning Agent) ---

class CurrentPolicyRisk(BaseModel):
    risk_per_trade: float
    max_position_pct: float
    stop_loss_pct: float

class CurrentPolicyStrategyBias(BaseModel):
    # This is a placeholder as the Orchestrator does not yet have a concept
    # of preferred regimes. The Learning Agent is designed to handle this.
    preferred_regime: str = "any"

class CurrentPolicy(BaseModel):
    agent_weights: Dict[str, float]
    risk: CurrentPolicyRisk
    strategy_bias: CurrentPolicyStrategyBias

class LearningRequest(BaseModel):
    """The complete input data structure for the /learn endpoint."""
    learning_mode: str
    window_size: int
    trade_history: List[Trade]
    price_history: Dict[str, List[Dict[str, Any]]]
    current_policy: CurrentPolicy

# --- Pydantic Models for Incoming API Contract (from Learning Agent) ---

class IncomingPolicyDeltas(BaseModel):
    agent_weights: Dict[str, float] = Field(default_factory=dict)
    risk: Dict[str, float] = Field(default_factory=dict)
    strategy_bias: Dict[str, Any] = Field(default_factory=dict)
    guardrails: Dict[str, Any] = Field(default_factory=dict)

class LearningResponse(BaseModel):
    """The complete output data structure from the /learn endpoint."""
    learning_state: str
    policy_deltas: IncomingPolicyDeltas = Field(default_factory=IncomingPolicyDeltas)
    reasoning: List[str] = Field(default_factory=list)

# --- Pydantic Models for Internal Orchestrator Contract ---

class InternalPolicyDeltas(BaseModel):
    """Represents the recommended adjustments to the system's policy."""
    agent_weights: Optional[Dict[str, float]] = None
    risk_per_trade: Optional[float] = None
    # Future-proofing: can add other risk params here as needed
    # e.g., stop_loss_pct: Optional[float] = None

class LearningResponseBody(BaseModel):
    """The expected JSON response for the orchestrator's internal logic."""
    learning_state: str = Field(..., description="e.g., 'warmup', 'learning'")
    version: str
    policy_deltas: InternalPolicyDeltas

# --- Client Logic ---

class LearningAgentClient:
    """
    An adapter client for interacting with the Learning Agent.
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
        self.version = "2.0.0"  # Bumping version for new contract

    async def trigger_learning_cycle(
        self,
        account_id: int,
        symbol: str,
        correlation_id: str,
    ) -> Optional[LearningResponseBody]:
        """
        Gathers all necessary data, calls the learning agent, and translates
        the response into the format expected by the Orchestrator's ConfigManager.
        """
        if not self.base_url:
            report_logger.warning(
                "AUTO_LEARNING_AGENT_URL is not configured. Skipping learning cycle."
            )
            return None

        try:
            # 1. Gather data
            trade_history = await self.db_client.get_trade_history(
                account_id,
                correlation_id,
            )
            price_history_data = await self.db_client.get_price_history(
                symbol,
                correlation_id,
            )
            price_history = {symbol: price_history_data}


            # 2. Get current configuration from ConfigManager
            current_policy = CurrentPolicy(
                agent_weights=config_manager.get("AGENT_WEIGHTS"),
                risk=CurrentPolicyRisk(
                    risk_per_trade=config_manager.get("RISK_PER_TRADE"),
                    max_position_pct=config_manager.get("MAX_POSITION_PERCENTAGE"),
                    stop_loss_pct=config_manager.get("STOP_LOSS_PERCENTAGE"),
                ),
                strategy_bias=CurrentPolicyStrategyBias(),
            )

            # 3. Construct the request payload for the learning agent
            request_payload = LearningRequest(
                learning_mode=config_manager.get("LEARNING_MODE"),
                window_size=config_manager.get("WINDOW_SIZE"),
                trade_history=trade_history,
                price_history=price_history,
                current_policy=current_policy,
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
            internal_deltas = InternalPolicyDeltas(
                agent_weights=learning_response.policy_deltas.agent_weights,
                # Extract the specific risk param the ConfigManager knows how to handle
                risk_per_trade=learning_response.policy_deltas.risk.get("risk_per_trade"),
            )

            return LearningResponseBody(
                learning_state=learning_response.learning_state,
                version=self.version,
                policy_deltas=internal_deltas,
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
