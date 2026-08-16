from pathlib import Path

from scripts.run_profitability_funnel_audit import build_upstream_failure_funnel, run_audit


def test_upstream_failure_is_reported_without_fake_scanner_metrics(tmp_path: Path):
    funnel = build_upstream_failure_funnel(upstream_report={"cycleStatus": "failure"}, source_run_id="31942008720", source_run_conclusion="failure")
    assert funnel["source_status"] == "upstream_failed_before_scanner"
    assert funnel["primary_bottleneck"]["stage"] == "upstream_runtime"
    assert funnel["health"]["scanner_not_run"] is True
    assert funnel["health"]["backtest_symbols"] == []
    assert "hourly_workflow_failure" in funnel["primary_bottleneck"]["reason_codes"]
    assert funnel["safety"]["risk_thresholds_relaxed"] is False
    assert funnel["safety"]["investability_thresholds_relaxed"] is False


def test_runner_writes_audit_artifact_when_discovery_is_missing(tmp_path: Path):
    upstream = tmp_path / "hourly-auto-trading-report.json"
    upstream.write_text('{"cycleStatus":"failure"}', encoding="utf-8")
    output = tmp_path / "out" / "funnel.json"
    markdown = tmp_path / "out" / "funnel.md"
    funnel = run_audit(discovery_path=tmp_path / "missing-discovery.json", upstream_report_path=upstream, output_path=output, markdown_path=markdown, source_run_id="843", source_run_conclusion="failure")
    assert output.exists()
    assert markdown.exists()
    assert funnel["primary_bottleneck"]["stage"] == "upstream_runtime"
    assert "Scanner preselection was not reached" in markdown.read_text(encoding="utf-8")


def test_runner_uses_normal_funnel_when_discovery_exists(tmp_path: Path):
    discovery = tmp_path / "hourly-pre-backtest-discovery.json"
    discovery.write_text('{"status":"success","request":{"max_universe":100},"backtest_symbols":["AAPL"],"response":{"data":{"scanner_metadata":{"attempted_count":100,"analyzed_count":95},"scanner_count":1,"deep_analysis_count":1,"ranked_candidates":[{"symbol":"AAPL","strategy_bucket":"core_dividend","evidence_gate_passed":true}],"bucket_selection":{"summary":{"selected_before_investability":1,"selected_after_investability":1}},"allocation_plan":{"investability_gate":{"rejected":[]}},"exposure_gate":{"summary":{"allowed_count":1}}}}}', encoding="utf-8")
    output = tmp_path / "funnel.json"
    funnel = run_audit(discovery_path=discovery, upstream_report_path=None, output_path=output, markdown_path=None, source_run_id="844", source_run_conclusion="success")
    assert funnel["source_status"] == "success"
    assert funnel["health"]["scanner_success_rate"] == 0.95
    assert funnel["health"]["backtest_symbols"] == ["AAPL"]
    assert funnel["source_run_id"] == "844"
