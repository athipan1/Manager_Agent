from typing import Optional, Dict, Any
import pandas as pd

def calculate_roe(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculates Return on Equity (ROE)."""
    try:
        balance_sheet = financial_data["balance_sheet"]
        income_statement = financial_data["income_statement"]

        net_income = income_statement.loc['Net Income'].iloc[0]
        shareholder_equity = balance_sheet.loc['Stockholders Equity'].iloc[0]

        if shareholder_equity == 0:
            return None
        return (net_income / shareholder_equity) * 100
    except (KeyError, IndexError):
        return None

def calculate_roa(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculates Return on Assets (ROA)."""
    try:
        balance_sheet = financial_data["balance_sheet"]
        income_statement = financial_data["income_statement"]

        net_income = income_statement.loc['Net Income'].iloc[0]
        total_assets = balance_sheet.loc['Total Assets'].iloc[0]

        if total_assets == 0:
            return None
        return (net_income / total_assets) * 100
    except (KeyError, IndexError):
        return None

def calculate_debt_to_equity(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculates Debt-to-Equity ratio."""
    try:
        balance_sheet = financial_data["balance_sheet"]

        total_debt = balance_sheet.loc['Total Debt'].iloc[0]
        shareholder_equity = balance_sheet.loc['Stockholders Equity'].iloc[0]

        if shareholder_equity == 0:
            return None
        return total_debt / shareholder_equity
    except (KeyError, IndexError):
        return None

def calculate_free_cash_flow(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculates Free Cash Flow."""
    try:
        cash_flow = financial_data["cash_flow"]

        operating_cash_flow = cash_flow.loc['Operating Cash Flow'].iloc[0]
        capital_expenditure = cash_flow.loc['Capital Expenditure'].iloc[0]

        return operating_cash_flow + capital_expenditure # Capex is usually negative
    except (KeyError, IndexError):
        return None

def calculate_profit_margins(financial_data: Dict[str, Any]) -> Optional[float]:
    """Calculates Net Profit Margins."""
    try:
        income_statement = financial_data["income_statement"]

        net_income = income_statement.loc['Net Income'].iloc[0]
        total_revenue = income_statement.loc['Total Revenue'].iloc[0]

        if total_revenue == 0:
            return None
        return (net_income / total_revenue) * 100
    except (KeyError, IndexError):
        return None
