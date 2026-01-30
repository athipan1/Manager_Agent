class DatabaseEndpoints:
    HEALTH = "/health"
    BALANCE = "/accounts/{account_id}/balance"
    POSITIONS = "/accounts/{account_id}/positions"
    ORDERS = "/accounts/{account_id}/orders"
    EXECUTE_ORDER = "/orders/{order_id}/execute"
    TRADE_HISTORY = "/accounts/{account_id}/trade_history"
    PORTFOLIO_METRICS = "/accounts/{account_id}/portfolio_metrics"
    PRICE_HISTORY = "/prices/{symbol}"

class ExecutionEndpoints:
    EXECUTE = "/execute"

class AnalysisEndpoints:
    ANALYZE = "/analyze"

class ScannerEndpoints:
    SCAN = "/scan"
    SCAN_FUNDAMENTAL = "/scan/fundamental"
    HEALTH = "/health"

class LearningEndpoints:
    LEARN = "/learn"
