
import pytest
import httpx
import subprocess
import time
import os
import sys

# Define the URLs for the services
MANAGER_AGENT_URL = "http://localhost:8080/analyze"

@pytest.fixture(scope="module")
def live_agent_services():
    """
    A pytest fixture that starts and stops all three agent services
    (Manager, Technical, and Fundamental) to create a live environment
    for end-to-end integration testing.
    """
    # Create a modified environment for the Fundamental_Agent to enable test mode
    fund_agent_env = os.environ.copy()
    fund_agent_env["GEMINI_API_KEY"] = "DUMMY_KEY_FOR_TESTING"

    # --- Start Technical_Agent ---
    tech_agent_process = subprocess.Popen(
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd="Technical_Agent/technical_agent",
        stdout=sys.stdout, stderr=sys.stderr
    )

    # --- Start Fundamental_Agent ---
    # Note: The default port in its main.py is 8001
    fund_agent_process = subprocess.Popen(
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"],
        cwd="Fundamental_Agent",
        stdout=sys.stdout, stderr=sys.stderr,
        env=fund_agent_env
    )

    # --- Start Manager_Agent ---
    manager_agent_process = subprocess.Popen(
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"],
        stdout=sys.stdout, stderr=sys.stderr
    )

    # Give all servers a generous amount of time to start up
    time.sleep(10)

    # Yield control to the tests
    yield

    # --- Teardown: Stop all services ---
    tech_agent_process.terminate()
    fund_agent_process.terminate()
    manager_agent_process.terminate()
    tech_agent_process.wait()
    fund_agent_process.wait()
    manager_agent_process.wait()


def test_full_end_to_end_communication(live_agent_services):
    """
    Full Integration Test: Verifies that the Manager_Agent can successfully
    communicate with live instances of both the Technical_Agent and the
    Fundamental_Agent.

    - Starts all three services in a live environment.
    - Sends a request to the Manager_Agent for a common stock ticker.
    - Asserts that a valid, 200 OK response is received.
    - Verifies the response payload is well-formed and contains data from
      both child agents, confirming the entire system is communicating correctly.
    """
    # Arrange
    request_payload = {"ticker": "MSFT"} # Using a different ticker like MSFT

    # Act
    # Make a real HTTP request to the live Manager_Agent service
    with httpx.Client() as client:
        response = client.post(MANAGER_AGENT_URL, json=request_payload, timeout=40.0)

    # Assert
    # Check that the end-to-end communication was successful
    assert response.status_code == 200
    response_data = response.json()

    # Verify the integrity of the synthesized report
    assert response_data["report_id"] is not None
    assert response_data["ticker"] == "MSFT"
    assert response_data["final_verdict"] in ["buy", "sell", "hold"]

    # Verify that the technical analysis details are present
    tech_details = response_data["details"]["technical"]
    assert tech_details["action"] in ["buy", "sell", "hold"]
    assert 0 <= tech_details["score"] <= 1
    assert "Technical analysis suggests" in tech_details["reason"]

    # Verify that the fundamental analysis details are present
    fund_details = response_data["details"]["fundamental"]
    assert fund_details["action"] in ["buy", "sell", "hold"]
    assert 0 <= fund_details["score"] <= 1
    assert "Fundamental analysis suggests a" in fund_details["reason"]
