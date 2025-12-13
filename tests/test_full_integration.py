
import pytest
import httpx
import subprocess
import time
import os
import sys
import shutil

# --- Configuration ---
MANAGER_AGENT_URL = "http://localhost:8080/analyze"
TECHNICAL_AGENT_URL = "http://localhost:8000/"
FUNDAMENTAL_AGENT_URL = "http://localhost:8001/"

# --- Patched Code for Fundamental Agent ---
# This code will be written to the submodule's files at test time.

PATCHED_ANALYZER_PY = """
from typing import Optional
import os
import json

def analyze_financials(ticker: str, data: dict) -> dict:
    \"\"\"
    A patched version of the analyzer that returns a mock response
    for testing purposes when a dummy API key is detected.
    \"\"\"
    if os.getenv("GEMINI_API_KEY") == "DUMMY_KEY_FOR_TESTING":
        return {
            "strength": "พื้นฐานปานกลาง",
            "reasoning": "โหมดทดสอบ: ข้ามการเรียก API ภายนอก",
            "score": 0.5
        }
    # In a real scenario, the original logic would be here.
    # For this test, we only need the mocked path.
    return None
"""

PATCHED_FUNDAMENTAL_AGENT_PY = """
import argparse
import json
from analyzer import analyze_financials

def determine_action(score: float) -> str:
    if score >= 0.7:
        return "buy"
    if score >= 0.4:
        return "hold"
    return "sell"

def run_analysis(ticker: str):
    \"\"\"
    A patched version of the main analysis function that formats the
    mocked response to match the Manager_Agent's expected schema.
    \"\"\"
    print(f"--- (Patched) Starting fundamental analysis for {ticker} ---")

    # In this patched version, we bypass the data fetcher and go straight to the analyzer
    # with dummy data, as the analyzer is also patched to return a mock result.
    analysis_result = analyze_financials(ticker, {})

    if not analysis_result:
        return None

    confidence_score = analysis_result["score"]
    action = determine_action(confidence_score)

    formatted_response = {
        "status": "success", "agent_type": "fundamental", "ticker": ticker,
        "data": {
            "action": action,
            "confidence_score": confidence_score,
            "analysis_summary": analysis_result["reasoning"],
            "metrics": {"strength": analysis_result["strength"]}
        }
    }
    return formatted_response
"""

def wait_for_service(url: str, timeout: int = 30):
    """Polls a service's health check endpoint until it is ready."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with httpx.Client() as client:
                if client.get(url).status_code == 200:
                    print(f"Service at {url} is ready.")
                    return
        except httpx.ConnectError:
            time.sleep(0.5)
    raise RuntimeError(f"Service at {url} did not become available in {timeout}s.")

@pytest.fixture(scope="module")
def live_agent_services():
    """
    Starts all agent services, patching the Fundamental_Agent on the fly
    to ensure a reproducible and self-contained test environment.
    """
    fund_agent_dir = "Fundamental_Agent"
    analyzer_path = os.path.join(fund_agent_dir, "analyzer.py")
    agent_path = os.path.join(fund_agent_dir, "fundamental_agent.py")

    # Backup original files
    shutil.move(analyzer_path, analyzer_path + ".bak")
    shutil.move(agent_path, agent_path + ".bak")

    try:
        # Write the patched files
        with open(analyzer_path, "w") as f:
            f.write(PATCHED_ANALYZER_PY)
        with open(agent_path, "w") as f:
            f.write(PATCHED_FUNDAMENTAL_AGENT_PY)

        # Set up the environment for the patched agent
        fund_agent_env = os.environ.copy()
        fund_agent_env["GEMINI_API_KEY"] = "DUMMY_KEY_FOR_TESTING"

        # --- Start All Services ---
        processes = {
            "manager": subprocess.Popen(["uvicorn", "app.main:app", "--port", "8080"], stdout=sys.stdout, stderr=sys.stderr),
            "technical": subprocess.Popen(["uvicorn", "main:app", "--port", "8000"], cwd="Technical_Agent/technical_agent", stdout=sys.stdout, stderr=sys.stderr),
            "fundamental": subprocess.Popen(["uvicorn", "main:app", "--port", "8001"], cwd=fund_agent_dir, env=fund_agent_env, stdout=sys.stdout, stderr=sys.stderr)
        }

        # --- Wait for Services to be Ready ---
        wait_for_service(TECHNICAL_AGENT_URL)
        wait_for_service(FUNDAMENTAL_AGENT_URL)

        yield
    finally:
        # --- Teardown: Stop all services ---
        for process in processes.values():
            process.terminate()
            process.wait()
        print("All services shut down.")

        # Restore original files
        shutil.move(analyzer_path + ".bak", analyzer_path)
        shutil.move(agent_path + ".bak", agent_path)
        print("Original Fundamental_Agent files restored.")


def test_full_end_to_end_communication(live_agent_services):
    """Full Integration Test for all three agent services."""
    response = httpx.post(MANAGER_AGENT_URL, json={"ticker": "MSFT"}, timeout=40.0)
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["ticker"] == "MSFT"
    assert response_data["final_verdict"] in ["buy", "sell", "hold"]
    assert "Technical analysis suggests" in response_data["details"]["technical"]["reason"]
    assert "Fundamental analysis suggests" in response_data["details"]["fundamental"]["reason"]
