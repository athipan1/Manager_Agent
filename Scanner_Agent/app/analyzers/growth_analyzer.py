from typing import Optional, Dict, Any
import pandas as pd
import numpy as np

def calculate_revenue_cagr(financial_data: Dict[str, Any], years: int = 3) -> Optional[float]:
    """Calculates the Compound Annual Growth Rate (CAGR) of revenue over a specified period."""
    try:
        income_statement = financial_data["income_statement"]

        # Ensure we have enough data points
        if len(income_statement.columns) < (years * 4): # Quarterly data
            return None

        # Get the total revenue for the last 12 months (LTM) and N years ago
        ltm_revenue = income_statement.iloc[income_statement.index.get_loc('Total Revenue'), :4].sum()
        nyears_ago_revenue = income_statement.iloc[income_statement.index.get_loc('Total Revenue'), (years*4 - 4):(years*4)].sum()

        if nyears_ago_revenue <= 0 or ltm_revenue <= 0:
            return None

        # Calculate CAGR
        cagr = ((ltm_revenue / nyears_ago_revenue) ** (1/years)) - 1
        return cagr * 100
    except (KeyError, IndexError):
        return None

def calculate_eps_growth(financial_data: Dict[str, Any], years: int = 3) -> Optional[float]:
    """Calculates the EPS growth over a specified period."""
    try:
        income_statement = financial_data["income_statement"]

        # Ensure we have enough data points
        if len(income_statement.columns) < (years * 4):
            return None

        ltm_eps = income_statement.loc['Basic EPS'].iloc[:4].sum()
        nyears_ago_eps = income_statement.loc['Basic EPS'].iloc[(years*4 - 4):(years*4)].sum()

        if nyears_ago_eps == 0:
            return None

        eps_growth = (ltm_eps - nyears_ago_eps) / abs(nyears_ago_eps)
        return eps_growth * 100
    except (KeyError, IndexError):
        return None
