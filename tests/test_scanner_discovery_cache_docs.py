from pathlib import Path


def test_scanner_preselection_cache_docs_cover_safety_and_diagnostics():
    text = Path("docs/scanner-preselection-cache.md").read_text(encoding="utf-8")

    assert "one-shot" in text
    assert "SCANNER_DISCOVERY_CACHE_TTL_SECONDS" in text
    assert "exact Backtest execution gate" in text
    assert "scanner_discovery_cache_hit" in text
