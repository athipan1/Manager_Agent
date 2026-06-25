from pathlib import Path


def test_dockerfile_uses_modular_entrypoint():
    text = Path("Dockerfile").read_text(encoding="utf-8")

    assert "app.main_modular:app" in text
    assert "app.main:app", "--host" not in text


def test_start_script_uses_modular_manager_entrypoint():
    text = Path("start_agents.sh").read_text(encoding="utf-8")

    assert "uvicorn app.main_modular:app --port 8000" in text
    assert "uvicorn app.main:app --port 8000" not in text
