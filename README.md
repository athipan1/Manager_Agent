# Financial AI Agent Orchestrator

This project implements a FastAPI-based orchestrator that acts as a central intelligence for a financial AI agent system. It receives a stock ticker, queries two specialized agents (Technical and Fundamental), and synthesizes their analyses into a single, actionable investment report.

## Features

- **Centralized Orchestration:** A single endpoint to get a holistic view of a stock.
- **Parallel Processing:** Queries downstream agents concurrently for a fast response.
- **Decision Matrix:** Implements a sophisticated logic to synthesize conflicting signals into a final verdict.
- **Asynchronous:** Built with FastAPI and `httpx` for high performance.
- **Pydantic Models:** Ensures data integrity and provides clear API contracts.

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── agent_client.py   # Client to call downstream agents
│   ├── main.py           # Main FastAPI application and endpoint
│   ├── models.py         # Pydantic models for data validation
│   └── synthesis.py      # Core decision matrix logic
├── mock_agents/
│   ├── fundamental_agent_mock.py  # Mock server for the Fundamental Agent
│   └── technical_agent_mock.py    # Mock server for the Technical Agent
├── tests/
│   └── test_synthesis.py # Unit tests for the synthesis logic
└── requirements.txt      # Project dependencies
```

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_name>
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## How to Run

1.  **Start the mock agents:**
    Open two separate terminal windows.

    In the first terminal, run the technical agent mock:
    ```bash
    python3 mock_agents/technical_agent_mock.py
    ```
    This will start the server on `http://localhost:8000`.

    In the second terminal, run the fundamental agent mock:
    ```bash
    python3 mock_agents/fundamental_agent_mock.py
    ```
    This will start the server on `http://localhost:8001`.

2.  **Start the main orchestrator application:**
    In a third terminal, run the orchestrator:
    ```bash
    uvicorn app.main:app --reload
    ```
    The orchestrator will be available at `http://localhost:8000`, but this conflicts with the mock agent. You can run it on a different port:
    ```bash
    uvicorn app.main:app --port 8080 --reload
    ```

3.  **Send a request to the orchestrator:**
    Use a tool like `curl` or an API client (like Postman or Insomnia) to send a POST request to the `/analyze` endpoint.

    **Example using `curl`:**
    ```bash
    curl -X 'POST' \
      'http://localhost:8080/analyze' \
      -H 'accept: application/json' \
      -H 'Content-Type: application/json' \
      -d '{
        "ticker": "AAPL"
      }'
    ```

    **Example tickers for mock agents:** `AAPL`, `GOOG`

## Running Tests

To run the unit tests, execute the following command from the root directory:
```bash
python3 -m pytest
```
