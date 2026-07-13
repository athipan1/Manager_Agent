from pathlib import Path


def test_manager_host_port_maps_to_uvicorn_container_port():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    preselection = Path("scripts/run_scanner_preselection.py").read_text(
        encoding="utf-8"
    )

    assert 'EXPOSE 80' in dockerfile
    assert '"--port", "80"' in dockerfile
    assert '- "8000:80"' in compose
    assert '- "8000:8000"' not in compose
    assert "http://localhost:8000/discover-analyze-trade" in preselection
