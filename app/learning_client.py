import asyncio
from typing import Dict, Optional, List, Any
from decimal import Decimal
import uuid

from .config_manager import config_manager
from .logger import report_logger
from .contracts import (
    Trade,
    PricePoint,
    CurrentPolicy,
    CurrentPolicyRisk,
    CurrentPolicyStrategyBias,
    LearningRequest,
    LearningResponse,
    IncomingPolicyDeltas,
    InternalPolicyDeltas,
    LearningResponseBody,
    LearningEndpoints,
    StandardAgentResponse
)
from .database_client import DatabaseAgentClient
from .resilient_client import ResilientAgentClient

class LearningAgentClient(ResilientAgentClient):
    """
    An adapter client for interacting with the Learning Agent.
    """

    def __init__(
        self,
        db_client: DatabaseAgentClient,
    ):
        base_url = config_manager.get("AUTO_LEARNING_AGENT_URL")
        super().__init__(base_url=base_url)
        self.db_client = db_client
        self.version = "2.0.0"

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

            trade_history = []
            for t in trade_history_raw:
                t_data = t.model_dump() if hasattr(t, "model_dump") else t
                trade_history.append(Trade(
                    trade_id=t_data.get("trade_id") or str(uuid.uuid4()),
                    account_id=str(account_id),
                    asset_id=t_data.get("symbol") or t_data.get("asset_id", "unknown"),
                    symbol=t_data.get("symbol", "unknown"),
                    side=t_data.get("side", t_data.get("action", "buy")).lower(),
                    quantity=Decimal(str(t_data.get("quantity", 0))),
                    price=Decimal(str(t_data.get("price") or t_data.get("entry_price", 0))),
                    executed_at=t_data.get("executed_at") or t_data.get("timestamp", ""),
                    agents=t_data.get("agents", {}),
                    pnl_pct=t_data.get("pnl_pct"),
                    entry_price=t_data.get("entry_price"),
                    exit_price=t_data.get("exit_price"),
                ))

            price_history_data = await self.db_client.get_price_history(
                symbol,
                correlation_id,
            )
            price_history = {
                symbol: [
                    PricePoint.model_validate(p) if hasattr(p, "model_validate") else PricePoint(**p)
                    for p in price_history_data
                ]
            }

            # 2. Get current configuration
            current_policy = CurrentPolicy(
                agent_weights=config_manager.get("AGENT_WEIGHTS"),
                risk=CurrentPolicyRisk(
                    risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")),
                    max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")),
                    stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")),
                ),
                strategy_bias=CurrentPolicyStrategyBias(),
            )

            # 3. Construct payload
            request_payload = LearningRequest(
                learning_mode=config_manager.get("LEARNING_MODE"),
                window_size=config_manager.get("WINDOW_SIZE"),
                trade_history=trade_history,
                price_history=price_history,
                current_policy=current_policy,
                execution_result=execution_result,
            )

            # 4. Make the call
            response_data = await self._post(
                url=LearningEndpoints.LEARN,
                correlation_id=correlation_id,
                json_data=request_payload.model_dump(mode='json')
            )

            standard_resp = self.validate_standard_response(response_data)
            learning_response = LearningResponse.model_validate(standard_resp.data)

            report_logger.info(
                f"Learning agent returned adjustments: {learning_response.reasoning}",
            )

            # 5. Translate response
            internal_deltas = InternalPolicyDeltas(
                agent_weights=learning_response.policy_deltas.agent_weights,
                risk_per_trade=learning_response.policy_deltas.risk.get("risk_per_trade"),
                asset_biases=learning_response.policy_deltas.asset_biases,
            )

            return LearningResponseBody(
                learning_state=learning_response.learning_state,
                version=self.version,
                policy_deltas=internal_deltas,
            )

        except Exception as e:
            report_logger.error(
                f"Failed to process response from Auto-Learning Agent: {e}"
            )
            return None
