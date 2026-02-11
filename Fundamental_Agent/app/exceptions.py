class TickerNotFound(Exception):
    """Raised when the ticker symbol is not found or is invalid."""
    pass


class InsufficientData(Exception):
    """Raised when there is not enough financial data to perform an analysis."""
    pass


class ModelError(Exception):
    """Raised when the generative AI model fails to produce a result."""
    pass
