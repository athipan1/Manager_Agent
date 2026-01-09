
import httpx
import asyncio
from typing import Dict, Optional, List, Any
from decimal import Decimal
from pydantic import BaseModel, Field
import uuid

from .config_manager import config_manager
from .database_client import DatabaseAgentClient
from .logger import report_logger
from .models import Trade, PricePoint # Import Trade และ PricePoint จาก common models

# --- Pydantic Models for Outgoing API Contract (to Learning Agent) ---
# ลบ LearningTrade ออกไป เพราะจะใช้ Trade จาก app.models แทน

class CurrentPolicyRisk(BaseModel):
    risk_per_trade: Decimal
    max_position_pct: Decimal
    stop_loss_pct: Decimal

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
    trade_history: List[Trade] # ใช้ Trade model ที่ import มา
    price_history: Dict[str, List[PricePoint]] # ใช้ PricePoint model ที่ import มา
    current_policy: CurrentPolicy
    execution_result: Optional[dict] = None

# --- Pydantic Models for Incoming API Contract (from Learning Agent) ---

class IncomingPolicyDeltas(BaseModel):
    agent_weights: Dict[str, float] = Field(default_factory=dict)
    risk: Dict[str, float] = Field(default_factory=dict)
    strategy_bias: Dict[str, Any] = Field(default_factory=dict)
    guardrails: Dict[str, Any] = Field(default_factory=dict)
    asset_biases: Dict[str, float] = Field(default_factory=dict) # เพิ่ม asset_biases

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
    asset_biases: Optional[Dict[str, float]] = None # เพิ่ม asset_biases

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
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> Optional[LearningResponseBody]:
        if not self.base_url:
            report_logger.warning(
                "AUTO_LEARNING_AGENT_URL is not configured. Skipping learning cycle."
            )
            return None

        try:
            # 1. Gather data
            trade_history_raw = await self.db_client.get_trade_history(
                account_id,
                correlation_id,
            )

            # ไม่ต้องแปลงเป็น LearningTrade แล้ว ใช้ Trade model โดยตรง
            trade_history = [
                Trade(
                    trade_id=str(uuid.uuid4()), # ต้องสร้าง trade_id ถ้า Database Agent ไม่ได้ให้มา
                    account_id=str(account_id),
                    asset_id=t.symbol, # ใช้ symbol เป็น asset_id
                    symbol=t.symbol,
                    side=t.action.lower(), # แปลง BUY/SELL เป็น buy/sell
                    quantity=Decimal(t.quantity),
                    price=t.entry_price, # ใช้ entry_price
                    executed_at=t.timestamp,
                    agents=t.agents, # เพิ่ม agents field
                    pnl_pct=t.pnl_pct, # เพิ่ม pnl_pct
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                )
                for t in trade_history_raw
            ]

            price_history_data = await self.db_client.get_price_history(
                symbol,
                correlation_id,
            )
            # แปลง price_history_data ให้อยู่ในรูปแบบ List[PricePoint]
            price_history = {symbol: [PricePoint(**p) for p in price_history_data]}

            # 2. Get current configuration from ConfigManager
            current_policy = CurrentPolicy(
                agent_weights=config_manager.get("AGENT_WEIGHTS"),
                risk=CurrentPolicyRisk(
                    risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")),
                    max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")),
                    stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")),
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
                execution_result=execution_result,
            )

            # 4. Make the API call
            url = f"{self.base_url}/learn"
            headers = {"X-Correlation-ID": correlation_id}
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=request_payload.model_dump(mode='json'),
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
                risk_per_trade=learning_response.policy_deltas.risk.get("risk_per_trade"),
                asset_biases=learning_response.policy_deltas.asset_biases, # เพิ่ม asset_biases
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
            report_logger.error(
                f"Failed to process response from Auto-Learning Agent: {e}"
            )
            return None
