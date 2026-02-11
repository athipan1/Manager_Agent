from typing import Optional, Dict, Any

def get_pe_ratio(market_data: Dict[str, Any]) -> Optional[float]:
    """Extracts the Price-to-Earnings (P/E) ratio."""
    return market_data.get("trailingPE")

def get_peg_ratio(market_data: Dict[str, Any]) -> Optional[float]:
    """Extracts the Price/Earnings-to-Growth (PEG) ratio."""
    return market_data.get("pegRatio")

def get_pb_ratio(market_data: Dict[str, Any]) -> Optional[float]:
    """Extracts the Price-to-Book (P/B) ratio."""
    return market_data.get("priceToBook")
