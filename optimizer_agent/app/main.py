from fastapi import FastAPI, HTTPException
from .models import OptimizerRequest
from .database_client import DatabaseClient
from .analysis import run_analysis

app = FastAPI()
db_client = DatabaseClient()

@app.post("/optimize")
async def optimize_strategy(config: OptimizerRequest):
    """
    Analyzes trading performance and returns recommended adjustments.
    """
    try:
        trade_history = await db_client.get_trade_history()
        portfolio_metrics = await db_client.get_portfolio_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch data from Database Agent: {e}")

    recommendation = run_analysis(trade_history, portfolio_metrics, config)

    return recommendation

@app.get("/")
def read_root():
    return {"message": "Optimizer Agent is running"}
