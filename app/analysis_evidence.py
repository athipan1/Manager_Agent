from __future__ import annotations

from typing import Any, Dict, Mapping


SUPPORTED_EVIDENCE_VERSIONS = {
    "scanner": "scanner-bucket-hints-v2",
    "fundamental": "fundamental-evidence-v1",
    "technical": "technical-evidence-v1",
}

_ALLOWED_EVIDENCE_STATUSES = {
    "complete",
    "partial",
    "insufficient",
    "suggested",
    "review",
    "conflict",
    "insufficient_evidence",
}


def _mapping(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _merge_dicts(*values: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for value in values:
        result.update(_mapping(value))
    return result


def _agent_data(response: Any) -> Dict[str, Any]:
    response = _mapping(response)
    data = response.get("data")
    return _mapping(data)


def _scanner_source(item: Mapping[str, Any]) -> Dict[str, Any]:
    candidate = _mapping(item.get("scanner_candidate"))
    metadata = _mapping(candidate.get("metadata"))
    bucket_hint = _mapping(candidate.get("bucket_hint"))
    hint = _merge_dicts(metadata, bucket_hint)

    version = str(hint.get("bucket_hint_version") or "").strip() or None
    status = str(hint.get("bucket_hint_status") or "").strip() or None
    primary = hint.get("primary_strategy_bucket_hint")
    bucket_scores = _mapping(hint.get("bucket_hint_scores"))
    raw_scores = _merge_dicts(
        candidate.get("raw_scores"),
        metadata.get("raw_scores"),
    )

    versioned = bool(version)
    issues: list[str] = []
    warnings: list[str] = []

    if versioned and version != SUPPORTED_EVIDENCE_VERSIONS["scanner"]:
        issues.append(f"unsupported_scanner_evidence_version:{version}")
    if versioned and hint.get("bucket_hint_is_binding") is not False:
        issues.append("scanner_hint_must_be_non_binding")
    if versioned and hint.get("manager_decision_required") is not True:
        issues.append("scanner_must_require_manager_decision")
    if status and status not in _ALLOWED_EVIDENCE_STATUSES:
        issues.append(f"invalid_scanner_evidence_status:{status}")
    if status == "conflict":
        issues.append("scanner_bucket_hint_conflict")
    elif status in {"review", "insufficient_evidence"}:
        warnings.append(f"scanner_bucket_hint_status:{status}")

    return {
        "present": bool(candidate),
        "versioned": versioned,
        "version": version,
        "supported_version": (
            not versioned
            or version == SUPPORTED_EVIDENCE_VERSIONS["scanner"]
        ),
        "status": status or ("legacy" if candidate else "missing"),
        "authority_valid": not any(
            issue in {
                "scanner_hint_must_be_non_binding",
                "scanner_must_require_manager_decision",
            }
            for issue in issues
        ),
        "primary_hint": primary,
        "primary_confidence": hint.get(
            "primary_strategy_bucket_confidence"
        ) or hint.get("strategy_bucket_confidence"),
        "bucket_scores": bucket_scores,
        "raw_scores": raw_scores,
        "metrics": {},
        "missing_fields": [],
        "provenance": {
            "bucket_hint_is_binding": hint.get("bucket_hint_is_binding"),
            "manager_decision_required": hint.get(
                "manager_decision_required"
            ),
            "bucket_hint_margin": hint.get("bucket_hint_margin"),
            "bucket_hint_reasons": hint.get("bucket_hint_reasons") or [],
        },
        "issues": issues,
        "warnings": warnings,
    }


def _analysis_source(
    analysis: Mapping[str, Any],
    source_name: str,
) -> Dict[str, Any]:
    raw_data = _mapping(analysis.get("raw_data"))
    response = _mapping(raw_data.get(source_name))
    data = _agent_data(response)
    evidence_key = f"{source_name}_evidence"
    evidence = _mapping(data.get(evidence_key))

    version = str(
        evidence.get("evidence_version")
        or data.get("evidence_version")
        or ""
    ).strip() or None
    status = str(
        evidence.get("evidence_status")
        or data.get("evidence_status")
        or ""
    ).strip() or None

    raw_scores = _merge_dicts(
        data.get("raw_scores"),
        evidence.get("raw_scores"),
    )
    metrics = _merge_dicts(
        data.get("key_metrics"),
        evidence.get("metrics"),
    )
    missing_fields = list(
        evidence.get("missing_fields")
        or data.get("missing_fields")
        or []
    )
    missing_critical = list(
        evidence.get("missing_critical_metrics")
        or data.get("missing_critical_metrics")
        or []
    )

    versioned = bool(version)
    expected_version = SUPPORTED_EVIDENCE_VERSIONS[source_name]
    authority = (
        evidence.get("bucket_decision_authority")
        if "bucket_decision_authority" in evidence
        else data.get("bucket_decision_authority")
    )
    manager_required = (
        evidence.get("manager_decision_required")
        if "manager_decision_required" in evidence
        else data.get("manager_decision_required")
    )
    strategy_bucket_hint = (
        evidence.get("strategy_bucket_hint")
        if "strategy_bucket_hint" in evidence
        else data.get("strategy_bucket_hint")
    )

    issues: list[str] = []
    warnings: list[str] = []
    if versioned and version != expected_version:
        issues.append(
            f"unsupported_{source_name}_evidence_version:{version}"
        )
    if versioned and authority != "manager":
        issues.append(
            f"{source_name}_bucket_decision_authority_must_be_manager"
        )
    if versioned and manager_required is not True:
        issues.append(f"{source_name}_must_require_manager_decision")
    if versioned and strategy_bucket_hint not in (None, ""):
        issues.append(f"{source_name}_must_not_assign_strategy_bucket")
    if status and status not in _ALLOWED_EVIDENCE_STATUSES:
        issues.append(f"invalid_{source_name}_evidence_status:{status}")
    if response and response.get("status") not in (None, "success"):
        issues.append(f"{source_name}_agent_response_not_success")
    if versioned and status == "insufficient":
        issues.append(f"{source_name}_evidence_insufficient")
    elif versioned and status == "partial":
        warnings.append(f"{source_name}_evidence_partial")
    if missing_critical:
        warnings.append(
            f"{source_name}_missing_critical_metrics:"
            + ",".join(str(value) for value in missing_critical)
        )

    authority_valid = not any(
        issue.startswith(f"{source_name}_bucket_decision_authority")
        or issue.startswith(f"{source_name}_must_require")
        or issue.startswith(f"{source_name}_must_not_assign")
        for issue in issues
    )

    return {
        "present": bool(response or data),
        "versioned": versioned,
        "version": version,
        "supported_version": not versioned or version == expected_version,
        "status": status or ("legacy" if data else "missing"),
        "authority_valid": authority_valid,
        "raw_scores": raw_scores,
        "metrics": metrics,
        "missing_fields": missing_fields,
        "missing_critical_metrics": missing_critical,
        "provenance": _merge_dicts(
            data.get("provenance"),
            evidence.get("provenance"),
            {
                "agent_response_status": response.get("status"),
                "agent_version": response.get("version"),
                "bucket_decision_authority": authority,
                "manager_decision_required": manager_required,
                "strategy_bucket_hint": strategy_bucket_hint,
            },
        ),
        "issues": issues,
        "warnings": warnings,
    }


def build_analysis_evidence_summary(
    item: Mapping[str, Any],
) -> Dict[str, Any]:
    """Normalize Scanner, Fundamental, and Technical evidence for Manager.

    Legacy payloads remain readable. Once any versioned evidence contract is
    present, Manager requires all three supported contracts and fails closed on
    missing, insufficient, unsupported, or authority-violating evidence.
    """
    item = _mapping(item)
    analysis = _mapping(item.get("analysis"))

    sources = {
        "scanner": _scanner_source(item),
        "fundamental": _analysis_source(analysis, "fundamental"),
        "technical": _analysis_source(analysis, "technical"),
    }

    gate_required = any(source["versioned"] for source in sources.values())
    blocking_issues: list[str] = []
    warnings: list[str] = []
    source_conflicts: list[str] = []

    for source_name, source in sources.items():
        blocking_issues.extend(source["issues"])
        warnings.extend(source["warnings"])
        if gate_required and not source["versioned"]:
            blocking_issues.append(
                f"missing_versioned_{source_name}_evidence"
            )

    scanner_status = sources["scanner"].get("status")
    if scanner_status == "conflict":
        source_conflicts.append("scanner_internal_bucket_conflict")

    evidence_versions = {
        name: source.get("version")
        for name, source in sources.items()
    }
    evidence_statuses = {
        name: source.get("status")
        for name, source in sources.items()
    }
    raw_scores = {
        name: source.get("raw_scores") or {}
        for name, source in sources.items()
    }
    metrics = {
        name: source.get("metrics") or {}
        for name, source in sources.items()
    }

    blocking_issues = list(dict.fromkeys(blocking_issues))
    warnings = list(dict.fromkeys(warnings))
    source_conflicts = list(dict.fromkeys(source_conflicts))

    gate_passed = not blocking_issues and not source_conflicts
    return {
        "contract": "manager-analysis-evidence-v1",
        "mode": "versioned" if gate_required else "legacy",
        "gate_required": gate_required,
        "gate_passed": gate_passed,
        "evidence_versions": evidence_versions,
        "evidence_statuses": evidence_statuses,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "source_conflicts": source_conflicts,
        "sources": sources,
        "raw_scores": raw_scores,
        "metrics": metrics,
        "classification_inputs": {
            "scanner": {
                "primary_hint": sources["scanner"].get("primary_hint"),
                "primary_confidence": sources["scanner"].get(
                    "primary_confidence"
                ),
                "bucket_scores": sources["scanner"].get("bucket_scores")
                or {},
            },
            "fundamental": {
                **raw_scores["fundamental"],
                **metrics["fundamental"],
            },
            "technical": {
                **raw_scores["technical"],
                **metrics["technical"],
            },
        },
    }
