"""Execution workflow helpers for Manager_Agent.

This module owns Manager-side execution orchestration after risk approval. It

persists risk approvals, builds order requests, validates batches, and submits

to Execution_Agent through an injected client.

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from .. import config

from ..database_client import DatabaseAgentClient

from ..execution_client import ExecutionAgentClient

from ..logger import report_logger

from ..risk_approval_contract import persist_risk_approval

from ..services.order_builder import order_request_from_decision

from ..services.serialization_service import response_to_dict

def ensure_risk_approval_id(

    trade_decision: Optional[Dict[str, Any]],

    correlation_id: str,

) -> Optional[str]:

    """Ensure a trade decision has a risk approval id.

    The fallback ID mirrors the legacy Manager behavior and is only used when

    Risk_Agent did not provide an explicit approval id.

    """

    if not trade_decision:

        return None

    risk_data = ((trade_decision.get("risk_agent_response") or {}).get("data") or {})

    approval_id = (

        risk_data.get("risk_approval_id")

        or risk_data.get("approval_id")

        or trade_decision.get("risk_approval_id")

    )

    if not approval_id:

        approval_id = f"risk-{correlation_id}-{trade_decision.get('symbol', 'unknown')}"

    trade_decision["risk_approval_id"] = str(approval_id)

    return str(approval_id)

def _validation_errors(validation_data: Dict[str, Any]) -> List[Dict[str, Any]]:

    errors = validation_data.get("errors") or []

    return errors if isinstance(errors, list) else []

def _open_order_conflict_symbols(validation_data: Dict[str, Any]) -> set[str]:

    symbols: set[str] = set()

    for error in _validation_errors(validation_data):

        if not isinstance(error, dict):

            continue

        if error.get("code") == "SYMBOL_ALREADY_HAS_OPEN_ORDER":

            symbols.update(str(symbol).upper() for symbol in (error.get("symbols") or []) if symbol)

    return symbols

def _order_symbol(order_request: Any) -> str:

    return str(getattr(order_request, "symbol", "") or "").upper()

async def execute_trade(

    exec_client: ExecutionAgentClient,

    trade_decision: Dict[str, Any],

    account_id: Union[int, str],

    correlation_id: str,

    db_client: Optional[DatabaseAgentClient] = None,

) -> Dict[str, Any]:

    """Persist risk approval and submit a single order to Execution_Agent."""

    ticker = trade_decision["symbol"]

    try:

        if db_client is not None:

            risk_approval_id = await persist_risk_approval(

                db_client=db_client,

                trade_decision=trade_decision,

                account_id=account_id,

                correlation_id=correlation_id,

            )

        else:

            if config.TRADING_MODE == "LIVE":

                raise RuntimeError(

                    "Database client is required to persist RiskApproval before LIVE execution."

                )

            risk_approval_id = ensure_risk_approval_id(trade_decision, correlation_id)

        trade_decision["risk_approval_id"] = risk_approval_id

        order_request = order_request_from_decision(trade_decision, account_id)

        async with exec_client as client:

            response = await client.create_order(order_request, correlation_id)

        if str(response.status).upper() in ["PENDING", "PLACED", "EXECUTED"]:

            return {

                "status": "submitted",

                "order_id": response.order_id,

                "risk_approval_id": risk_approval_id,

                "details": response.model_dump(),

            }

        return {

            "status": "rejected",

            "risk_approval_id": risk_approval_id,

            "reason": f"Execution Agent returned status: {response.status}",

        }

    except Exception as exc:

        report_logger.exception(

            f"Trade submission failed for {ticker}: {exc}, correlation_id={correlation_id}"

        )

        return {

            "status": "failed",

            "risk_approval_id": trade_decision.get("risk_approval_id"),

            "reason": str(exc),

        }

async def execute_portfolio_batch(

    *,

    exec_client: ExecutionAgentClient,

    decisions: List[Dict[str, Any]],

    account_id: Union[int, str],

    correlation_id: str,

    db_client: DatabaseAgentClient,

) -> Dict[str, Any]:

    """Persist approvals, validate, and submit a batch of approved decisions."""

    order_requests = []

    failed_to_build: List[Dict[str, Any]] = []

    for decision in decisions:

        try:

            decision["risk_approval_id"] = await persist_risk_approval(

                db_client=db_client,

                trade_decision=decision,

                account_id=account_id,

                correlation_id=correlation_id,

            )

            executable_quantity = int(

                decision.get("position_size")

                or decision.get("final_quantity")

                or decision.get("quantity")

                or 0

            )

            if executable_quantity <= 0:

                failed_to_build.append(

                    {

                        "symbol": decision.get("symbol"),

                        "reason": "approved decision has zero executable quantity",

                        "position_size": decision.get("position_size"),

                        "final_quantity": decision.get("final_quantity"),

                        "quantity": decision.get("quantity"),

                    }

                )

                continue

            order_requests.append(order_request_from_decision(decision, account_id))

        except Exception as exc:

            failed_to_build.append({"symbol": decision.get("symbol"), "reason": str(exc)})

    if not order_requests:

        return {

            "status": "not_attempted",

            "reason": "No executable approved portfolio orders.",

            "created": [],

            "failed": failed_to_build,

            "failed_to_build": failed_to_build,

            "skipped_open_order_conflicts": [],

        }

    validation = await exec_client.validate_order_batch(order_requests, correlation_id)

    validation_data = response_to_dict(validation).get("data") or {}

    skipped_open_order_conflicts: List[Dict[str, Any]] = []

    if not validation_data.get("approved", False):

        conflict_symbols = _open_order_conflict_symbols(validation_data)

        if conflict_symbols:

            retry_order_requests = []

            for order_request in order_requests:

                symbol = _order_symbol(order_request)

                if symbol in conflict_symbols:

                    skipped_open_order_conflicts.append(

                        {

                            "symbol": symbol,

                            "reason": "symbol already has an open broker order",

                            "risk_approval_id": getattr(order_request, "risk_approval_id", None),

                            "quantity": getattr(order_request, "quantity", None),

                            "final_quantity": getattr(order_request, "final_quantity", None),

                        }

                    )

                else:

                    retry_order_requests.append(order_request)

            order_requests = retry_order_requests

            if order_requests:

                retry_validation = await exec_client.validate_order_batch(

                    order_requests,

                    correlation_id,

                )

                retry_validation_data = response_to_dict(retry_validation).get("data") or {}

                if retry_validation_data.get("approved", False):

                    validation_data = {

                        **retry_validation_data,

                        "initial_validation": validation_data,

                        "skipped_open_order_conflicts": skipped_open_order_conflicts,

                    }

                else:

                    return {

                        "status": "rejected",

                        "reason": (

                            "Execution batch validation rejected portfolio orders "

                            "after skipping open-order conflicts."

                        ),

                        "validation": {

                            **retry_validation_data,

                            "initial_validation": validation_data,

                            "skipped_open_order_conflicts": skipped_open_order_conflicts,

                        },

                        "created": [],

                        "failed": failed_to_build,

                        "failed_to_build": failed_to_build,

                        "skipped_open_order_conflicts": skipped_open_order_conflicts,

                    }

            else:

                return {

                    "status": "not_attempted",

                    "reason": "All approved portfolio orders already have open broker orders.",

                    "validation": {

                        **validation_data,

                        "skipped_open_order_conflicts": skipped_open_order_conflicts,

                    },

                    "created": [],

                    "failed": failed_to_build,

                    "failed_to_build": failed_to_build,

                    "skipped_open_order_conflicts": skipped_open_order_conflicts,

                }

        else:

            return {

                "status": "rejected",

                "reason": "Execution batch validation rejected portfolio orders.",

                "validation": validation_data,

                "created": [],

                "failed": failed_to_build,

                "failed_to_build": failed_to_build,

                "skipped_open_order_conflicts": [],

            }

    response = await exec_client.execute_order_batch(order_requests, correlation_id)

    response_dict = response_to_dict(response)

    data = response_dict.get("data") or {}

    status_value = "submitted" if data.get("created") else "failed"

    return {

        "status": status_value,

        "validation": validation_data,

        **data,

        "failed_to_build": failed_to_build,

        "skipped_open_order_conflicts": skipped_open_order_conflicts,

    }