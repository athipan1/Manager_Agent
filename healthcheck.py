"""
Healthcheck script for the Docker container.

This script makes a GET request to the /health endpoint and exits with a status
code of 0 if the response is successful (200 OK), and 1 otherwise.
"""
import sys
import httpx

try:
    # Use httpx, which is already a project dependency.
    response = httpx.get("http://localhost:80/health", timeout=3.0)

    # Exit with a success code if the health check passes.
    if response.status_code == 200:
        print("Healthcheck passed.")
        sys.exit(0)
    else:
        print(f"Healthcheck failed with status code: {response.status_code}")
        sys.exit(1)

except httpx.RequestError as e:
    # Exit with a failure code if the request fails.
    print(f"Healthcheck failed with error: {e}")
    sys.exit(1)
