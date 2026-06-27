import subprocess
import sys
from pathlib import Path


def test_patch_curator_discovery_workflow_script_applies_to_fixture(tmp_path):
    repo = tmp_path
    workflow = repo / "app" / "workflows" / "discovery_workflow.py"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "from ..services.context_service import fetch_context_value, fetch_session_risk_contexts\n"
        "\n"
        "async def run():\n"
        "            position_analysis_payloads = allocation_report.get(\"position_analysis_payloads\") or []\n"
        "            await persist_signal(\n"
        "                extra_metadata={\n"
        "                        \"skipped_existing_protected_position\": item[\"symbol\"] in {row[\"symbol\"] for row in skipped_existing_protected_positions},\n"
        "                }\n"
        "            )\n"
        "            data = {\n"
        "            \"skipped_existing_protected_positions\": skipped_existing_protected_positions,\n"
        "            }\n"
        "            summary = {\n"
        "                \"skipped_existing_protected_positions\": len(skipped_existing_protected_positions),\n"
        "            }\n",
        encoding="utf-8",
    )

    script_source = Path(__file__).parents[2] / "scripts" / "patch_curator_discovery_workflow.py"
    script_target = repo / "scripts" / "patch_curator_discovery_workflow.py"
    script_target.parent.mkdir(parents=True)
    script_target.write_text(script_source.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/patch_curator_discovery_workflow.py"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    patched = workflow.read_text(encoding="utf-8")
    assert "enrich_payloads_with_curator_signals" in patched
    assert "curator_signals = await" in patched
    assert '"curator_signal"' in patched
    assert '"curator_signals": curator_signals' in patched
    assert '"curator_signals": len(curator_signals)' in patched
    assert "Applied Curator advisory wiring patch" in result.stdout


def test_patch_curator_discovery_workflow_script_is_idempotent(tmp_path):
    repo = tmp_path
    workflow = repo / "app" / "workflows" / "discovery_workflow.py"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "from ..services.context_service import fetch_context_value, fetch_session_risk_contexts\n"
        "\n"
        "async def run():\n"
        "            position_analysis_payloads = allocation_report.get(\"position_analysis_payloads\") or []\n"
        "            await persist_signal(\n"
        "                extra_metadata={\n"
        "                        \"skipped_existing_protected_position\": item[\"symbol\"] in {row[\"symbol\"] for row in skipped_existing_protected_positions},\n"
        "                }\n"
        "            )\n"
        "            data = {\n"
        "            \"skipped_existing_protected_positions\": skipped_existing_protected_positions,\n"
        "            }\n"
        "            summary = {\n"
        "                \"skipped_existing_protected_positions\": len(skipped_existing_protected_positions),\n"
        "            }\n",
        encoding="utf-8",
    )

    script_source = Path(__file__).parents[2] / "scripts" / "patch_curator_discovery_workflow.py"
    script_target = repo / "scripts" / "patch_curator_discovery_workflow.py"
    script_target.parent.mkdir(parents=True)
    script_target.write_text(script_source.read_text(encoding="utf-8"), encoding="utf-8")

    subprocess.run([sys.executable, "scripts/patch_curator_discovery_workflow.py"], cwd=repo, check=True)
    first = workflow.read_text(encoding="utf-8")
    subprocess.run([sys.executable, "scripts/patch_curator_discovery_workflow.py"], cwd=repo, check=True)
    second = workflow.read_text(encoding="utf-8")

    assert second == first
