# Manager_Agent

**Manager_Agent** is a FastAPI-based orchestrator service that analyzes stock tickers by querying specialized agents for technical and fundamental analysis. It synthesizes their responses into a single, actionable investment report.

## How It Works

1.  **Receives Request**: An API endpoint `/analyze` accepts a stock ticker.
2.  **Delegates to Agents**: It concurrently calls two external services:
    *   **Technical Agent**: Performs technical analysis (e.g., RSI, MACD).
    *   **Fundamental Agent**: Performs fundamental analysis (e.g., P/E ratio, news sentiment).
3.  **Synthesizes Results**: It combines the "buy/sell/hold" recommendations and confidence scores from both agents.
4.  **Returns Report**: It generates a detailed JSON report with a final verdict (e.g., "Strong Buy", "Hold").

## Getting Started

### Prerequisites

*   Python 3.8+
*   pip

### Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd Manager_Agent
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

### Configuration

The application uses environment variables to configure the URLs of the technical and fundamental agents. To get started, create a `.env` file in the root directory. You can copy the example file if one is provided, or create a new file with the following content:

```
TECHNICAL_AGENT_URL=http://localhost:8000/analyze
FUNDAMENTAL_AGENT_URL=http://localhost:8001/analyze
```

### Running the Application

To run the full system, you need to start the two mock agents and the main orchestrator application.

1.  **Start the Technical Agent Mock:**
    Open a terminal and run:
    ```bash
    python mock_agents/technical_agent_mock.py
    ```
    The agent will be available at `http://localhost:8000`.

2.  **Start the Fundamental Agent Mock:**
    Open a *second* terminal and run:
    ```bash
    python mock_agents/fundamental_agent_mock.py
    ```
    The agent will be available at `http://localhost:8001`.

3.  **Start the Manager_Agent Orchestrator:**
    Open a *third* terminal and run the main application. To avoid port conflicts with the agents, run it on a different port, such as 8002.
    ```bash
    uvicorn app.main:app --reload --port 8002
    ```
    The main application will be available at `http://localhost:8002`.

## API Usage

You can interact with the API using tools like `curl` or any API client.

### Endpoint: `POST /analyze`

*   **Request Body:**
    ```json
    {
      "ticker": "AAPL"
    }
    ```

*   **Example `curl` command:**
    ```bash
    curl -X POST "http://localhost:8002/analyze" \
         -H "Content-Type: application/json" \
         -d '{"ticker": "AAPL"}'
    ```

*   **Success Response (`200 OK`):**
    ```json
    {
      "report_id": "...",
      "ticker": "AAPL",
      "timestamp": "...",
      "final_verdict": "Buy",
      "details": {
        "technical": {
          "action": "buy",
          "score": 0.85,
          "reason": "RSI indicates oversold conditions and buying momentum is increasing."
        },
        "fundamental": {
          "action": "hold",
          "score": 0.6,
          "reason": "Solid fundamentals but the current price is fair; limited upside."
        }
      }
    }
    ```

## Running Tests

To run the automated tests, use `pytest`:
```bash
pytest
```
