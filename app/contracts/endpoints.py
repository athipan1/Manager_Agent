class DatabaseEndpoints:
    HEALTH = "/health"
    BALANCE = "/accounts/{account_id}/balance"
    POSITIONS = "/accounts/{account_id}/positions"
    ORDERS = "/accounts/{account_id}/orders"
    EXECUTE_ORDER = "/accounts/{account_id}/orders/{order_id}/execute"
    TRADE_HISTORY = "/accounts/{account_id}/trades"
    SESSION_RISK = "/accounts/{account_id}/risk/session"
    RISK_APPROVALS = "/risk-approvals"
    PORTFOLIO_METRICS = "/accounts/{account_id}/portfolio_metrics"
    PRICE_HISTORY = "/accounts/{account_id}/prices/{symbol}"
    SIGNALS = "/signals"
    PERFORMANCE_METRICS = "/performance_metrics"

class ExecutionEndpoints:
    HEALTH = "/health"
    EXECUTE = "/execute"

class AnalysisEndpoints:
    ANALYZE = "/analyze"

class ScannerEndpoints:
    SCAN = "/scan"
    SCAN_FUNDAMENTAL = "/scan/fundamental"
    DISCOVER_BEST_FUNDAMENTALS = "/discover-best-fundamentals"
    HEALTH = "/health"

class LearningEndpoints:
    LEARN = "/learn"
