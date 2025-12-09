# Financial AI Agent Orchestrator

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/athipan1/Manager_Agent/blob/main/Test_AI_Agents_Integration.ipynb)

This project implements a FastAPI-based orchestrator that acts as a central intelligence for a financial AI agent system. It receives a stock ticker, queries two specialized agents (Technical and Fundamental), and synthesizes their analyses into a single, actionable investment report.

## Features

- **Centralized Orchestration:** A single endpoint to get a holistic view of a stock.
- **Parallel Processing:** Queries downstream agents concurrently for a fast response.
- **Decision Matrix:** Implements a sophisticated logic to synthesize conflicting signals into a final verdict.
- **Asynchronous:** Built with FastAPI and `httpx` for high performance.
- **Pydantic Models:** Ensures data integrity and provides clear API contracts.
- **Production Ready:** Containerized with Docker and ready for deployment.

## Getting Started

There are three ways to run and test this project:

1.  **Google Colab (Easiest):** Test the full integration with the real agents in a live environment by clicking the "Open in Colab" button above.
2.  **Docker (Recommended for local setup):** Run the entire system, including the real agents, on your local machine using Docker Compose.
3.  **Local Development (For contributors):** Run the orchestrator and mock agents directly on your machine for development and testing.

---

## 🚀 Quick Start with Google Colab

Click the "Open in Colab" button at the top of this README to launch an interactive notebook. It will automatically set up the environment, run all three services, and allow you to send test requests to the live system.

## 🐳 Running with Docker

This is the recommended way to run the full system on your local machine.

**Prerequisites:**
- Docker and Docker Compose installed.

**Instructions:**
1.  Make sure Docker is running.
2.  From the root directory of this project, run the following command:
    ```bash
    docker-compose up --build
    ```
3.  This command will:
    -   Clone the repositories for the Technical and Fundamental agents.
    -   Build Docker images for all three services.
    -   Start the containers and connect them.
4.  The orchestrator will be available at `http://localhost:8080`. You can now send requests to it.

### Sending a Request

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

---

## 💻 Running Locally for Development (with Mocks)

This setup is intended for development and for running the orchestrator in isolation using mock agents.

### Setup and Installation

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

### How to Run

1.  **Start the mock agents:**
    Open two separate terminal windows.

    In the first terminal, run the technical agent mock:
    ```bash
    uvicorn mock_agents.technical_agent_mock:app --port 8000
    ```

    In the second terminal, run the fundamental agent mock:
    ```bash
    uvicorn mock_agents.fundamental_agent_mock:app --port 8001
    ```

2.  **Start the main orchestrator application:**
    In a third terminal, run the orchestrator:
    ```bash
    uvicorn app.main:app --port 8080 --reload
    ```

3.  **Send a request** to `http://localhost:8080/analyze` as shown in the Docker section.

## Project Structure

```
.
├── app/
│   ├── __init__.py
│   ├── agent_client.py   # Client to call downstream agents
│   ├── config.py         # Configuration management
│   ├── main.py           # Main FastAPI application and endpoint
│   ├── models.py         # Pydantic models for data validation
│   └── synthesis.py      # Core decision matrix logic
├── mock_agents/
│   ├── fundamental_agent_mock.py
│   └── technical_agent_mock.py
├── tests/
│   └── test_synthesis.py
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── README.md
├── requirements.txt
└── Test_AI_Agents_Integration.ipynb
```

## Running Tests

To run the unit tests, execute the following command from the root directory:
```bash
python3 -m pytest
```
