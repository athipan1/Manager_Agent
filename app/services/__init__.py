"""Service/helper layer for Manager_Agent.

Services should contain reusable logic that is independent from FastAPI route
handlers and can be unit tested directly.
"""

from __future__ import annotations

import sys

from . import backtest_gate_facade as _backtest_gate_facade

# Preserve the established import path while routing production execution
# through the promotion-authority façade. The original module is loaded under a
# private compatibility name by backtest_gate_facade.
sys.modules[f"{__name__}.backtest_execution_gate"] = _backtest_gate_facade
