class DatabaseEndpoints:
    HEALTH = "/health"
    BALANCE = "/accounts/{account_id}/balance"
    POSITIONS = "/accounts/{account_id}/positions"
    ORDERS = "/accounts/{account_id}/orders"
    EXECUTE_ORDER = "/accounts/{account_id}/orders/{order_id}/execute"
    TRADE_HISTORY = "/accounts/{account_id}/trades"
    SESSION_RISK = "/accounts/{account_id}/risk/session"
    RISK_APPROVALS = "/risk-approvals"
    BROKER_SYNC_STATUS = "/broker-sync/status"
    BROKER_SYNC_SNAPSHOT = "/broker-sync/snapshot"
    PORTFOLIO_METRICS = "/accounts/{account_id}/portfolio/metrics"
    PRICE_HISTORY = "/prices/{symbol}/history"
    SIGNALS = "/history/signals"
    PERFORMANCE_METRICS = "/history/performance"
    CURATOR_OBSERVATIONS_BATCH = "/curator/observations/batch"
    CURATOR_OBSERVATION_READINESS = "/curator/observations/readiness"


class ExecutionEndpoints:
    HEALTH = "/health"
    EXECUTE = "/execute"
    BATCH_VALIDATE = "/execute/batch/validate"
    BATCH_EXECUTE = "/execute/batch"
    BROKER_STATE = "/broker/state"
    BROKER_RECONCILE = "/broker/reconcile"


class AnalysisEndpoints:
    ANALYZE = "/analyze"


class ScannerEndpoints:
    SCAN = "/scan"
    SCAN_FUNDAMENTAL = "/scan/fundamental"
    DISCOVER_BEST_FUNDAMENTALS = "/discover-best-fundamentals"
    HEALTH = "/health"


class LearningEndpoints:
    LEARN = "/learn"
