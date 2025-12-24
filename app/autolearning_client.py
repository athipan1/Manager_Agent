import httpx
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

# Assuming the Orchestrator's config_manager provides the agent URL
from .config_manager import config_manager

# --- Pydantic Models for API Contract ---

class AgentSignal(BaseModel):
    """Represents the signal from a single analysis agent."""
    agent_name: str
    signal: str
    confidence: float

class AutoLearningRequestBody(BaseModel):
    """The JSON payload sent to the auto-learning agent's /learn endpoint."""
    trade_id: str
    symbol: str
    decision: str
    pnl_percentage: float
    agent_signals: List[AgentSignal]

class PolicyDeltas(BaseModel):
    """Represents the recommended adjustments to the system's policy."""
    agent_weights: Optional[Dict[str, float]] = None
    risk_per_trade: Optional[float] = None

class AutoLearningResponseBody(BaseModel):
    """The expected JSON response from the auto-learning agent."""
    learning_state: str = Field(..., description="e.g., 'warmup', 'learning'")
    version: str
    policy_deltas: PolicyDeltas


# --- Client Logic ---

class AutoLearningAgentClient:
    """A client for interacting with the Auto-Learning Agent."""

    def __init__(self, timeout: int = 10):
        self.base_url = config_manager.get("AUTO_LEARNING_AGENT_URL")
        self.timeout = timeout

    async def trigger_learning_cycle(self, trade_data: AutoLearningRequestBody) -> Optional[AutoLearningResponseBody]:
        """
        Sends post-trade data to the auto-learning agent and gets policy updates.

        Args:
            trade_data: The data related to the completed trade.

        Returns:
            An AutoLearningResponseBody object if the call is successful,
            otherwise None.
        """
        if not self.base_url:
            print("Warning: AUTO_LEARNING_AGENT_URL is not configured. Skipping learning cycle.")
            return None

        url = f"{self.base_url}/learn"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=trade_data.model_dump(),
                    timeout=self.timeout
                )
                response.raise_for_status()  # Raise an exception for 4xx or 5xx status codes

                # Parse and return the response
                return AutoLearningResponseBody.model_validate(response.json())

        except httpx.TimeoutException:
            print(f"Warning: Timeout while calling Auto-Learning Agent at {url}")
            return None
        except httpx.RequestError as e:
            print(f"Warning: An error occurred while requesting {e.request.url!r}: {e!r}")
            return None
        except Exception as e:
            # Catches validation errors or other unexpected issues
            print(f"Warning: Failed to process response from Auto-Learning Agent: {e}")
            return None

# Note: The plan is to instantiate this client where needed in main.py,
# rather than creating a global singleton instance here.
