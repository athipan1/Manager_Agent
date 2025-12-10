# API Documentation

This document provides a detailed overview of the API endpoints for the Financial AI Agent Orchestrator.

## Inbound API

The orchestrator exposes a single endpoint to receive analysis requests.

### `POST /analyze`

This is the main endpoint to trigger a financial analysis of a given stock ticker.

**Request Body:**

The request body must be a JSON object containing the stock ticker.

```json
{
  "ticker": "AAPL"
}
```

**Response Body:**

The endpoint returns a detailed investment report in JSON format.

*   **`report_id`** (string): A unique identifier for the report.
*   **`ticker`** (string): The stock ticker that was analyzed.
*   **`timestamp`** (string): The UTC timestamp of when the report was generated (ISO 8601 format).
*   **`final_verdict`** (string): The final investment recommendation. Can be one of `BUY`, `SELL`, or `HOLD`.
*   **`details`** (object): An object containing the detailed analysis from the individual agents.
    *   **`technical`** (object): The report from the Technical Analysis Agent.
        *   **`action`** (string): The recommendation from the agent (`buy`, `sell`, or `hold`).
        *   **`score`** (float): The confidence score of the recommendation (from 0.0 to 1.0).
        *   **`reason`** (string): A brief explanation for the recommendation.
    *   **`fundamental`** (object): The report from the Fundamental Analysis Agent.
        *   **`action`** (string): The recommendation from the agent (`buy`, `sell`, or `hold`).
        *   **`score`** (float): The confidence score of the recommendation (from 0.0 to 1.0).
        *   **`reason`** (string): A brief explanation for the recommendation.

**Example Response:**

```json
{
  "report_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
  "ticker": "AAPL",
  "timestamp": "2023-10-27T10:00:00.000Z",
  "final_verdict": "BUY",
  "details": {
    "technical": {
      "action": "buy",
      "score": 0.85,
      "reason": "Technical indicators suggest a strong upward trend."
    },
    "fundamental": {
      "action": "buy",
      "score": 0.75,
      "reason": "Fundamental analysis shows strong company financials and growth prospects."
    }
  }
}
```

## Outbound Connections

The orchestrator communicates with two external analysis agents to gather intelligence.

### Technical Analysis Agent

*   **URL:** `http://localhost:8000/analyze`
*   **Purpose:** Provides a technical analysis of the stock based on price trends, chart patterns, and market indicators.
*   **Request:** The orchestrator sends a `POST` request with the same JSON body it received: `{"ticker": "TICKER"}`.

### Fundamental Analysis Agent

*   **URL:** `http://localhost:8001/analyze`
*   **Purpose:** Provides a fundamental analysis of the stock based on financial statements, industry trends, and economic factors.
*   **Request:** The orchestrator sends a `POST` request with the same JSON body it received: `{"ticker": "TICKER"}`.

## Configuration

The URLs for the outbound agent connections are configurable.

The system first checks for environment variables. If they are not set, it falls back to the default values specified above.

*   **Technical Agent URL:**
    *   Environment Variable: `TECHNICAL_AGENT_URL`
    *   Default: `http://localhost:8000/analyze`
*   **Fundamental Agent URL:**
    *   Environment Variable: `FUNDAMENTAL_AGENT_URL`
    *   Default: `http://localhost:8001/analyze`

### How to Configure

#### Using Environment Variables

You can set these variables in your shell before running the application:

```bash
export TECHNICAL_AGENT_URL="http://new-technical-agent.com/api"
export FUNDAMENTAL_AGENT_URL="http://new-fundamental-agent.com/v2/analyze"
uvicorn app.main:app --reload
```

#### Using a `.env` file

Alternatively, you can create a `.env` file in the root directory of the project and define the variables there:

```
TECHNICAL_AGENT_URL="http://new-technical-agent.com/api"
FUNDAMENTAL_AGENT_URL="http://new-fundamental-agent.com/v2/analyze"
```

The application will automatically load these variables when it starts.
