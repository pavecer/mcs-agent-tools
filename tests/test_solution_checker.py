"""Unit tests for solution_checker YAML-driven configuration and rule lookup."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path


import solution_checker
from solution_checker import (
    _CHECKS_CONFIG,
    _INJECTION_PATTERNS,
    _PARAMS,
    _REQUIRED_SYSTEM_TOPICS,
    _RULES,
    _SECRET_PATTERNS,
    _SYSTEM_TOPIC_TRIGGERS,
    _load_checks_config,
    _rule,
    check_solution_zip,
)


# ── YAML config loading ───────────────────────────────────────────────────────


def test_checks_config_file_exists():
    """solution_checks.yaml must exist alongside solution_checker.py."""
    config_path = Path(solution_checker.__file__).parent / "solution_checks.yaml"
    assert config_path.exists(), f"solution_checks.yaml not found at {config_path}"


def test_checks_config_loads_as_dict():
    """The loaded config must be a non-empty dict."""
    assert isinstance(_CHECKS_CONFIG, dict)
    assert _CHECKS_CONFIG  # non-empty


def test_checks_config_has_required_top_level_keys():
    """The YAML must contain the expected top-level sections."""
    for key in (
        "parameters",
        "required_system_topics",
        "system_topic_triggers",
        "injection_patterns",
        "secret_patterns",
        "rules",
    ):
        assert key in _CHECKS_CONFIG, f"Missing top-level key '{key}' in solution_checks.yaml"


def test_load_checks_config_returns_same_as_module_global():
    """_load_checks_config() must return the same data as the module-level global."""
    fresh = _load_checks_config()
    assert fresh == _CHECKS_CONFIG


# ── Parameters ────────────────────────────────────────────────────────────────


def test_params_max_knowledge_file_mb():
    assert "max_knowledge_file_mb" in _PARAMS
    assert int(_PARAMS["max_knowledge_file_mb"]) > 0


def test_params_topic_thresholds():
    high = int(_PARAMS.get("topic_high_count_threshold", 0))
    very_high = int(_PARAMS.get("topic_very_high_count_threshold", 0))
    assert high > 0
    assert very_high > high, "very_high threshold must exceed high threshold"


# ── Required system topics ────────────────────────────────────────────────────


def test_required_system_topics_is_non_empty_dict():
    assert isinstance(_REQUIRED_SYSTEM_TOPICS, dict)
    assert len(_REQUIRED_SYSTEM_TOPICS) > 0


def test_required_system_topics_on_error_present():
    assert "OnError" in _REQUIRED_SYSTEM_TOPICS


def test_required_system_topics_on_error_is_fail():
    cfg = _REQUIRED_SYSTEM_TOPICS["OnError"]
    assert cfg.get("missing_outcome") == "fail"


def test_required_system_topics_have_label_and_rule_id():
    for trigger, cfg in _REQUIRED_SYSTEM_TOPICS.items():
        assert "label" in cfg, f"Missing 'label' for {trigger}"
        assert "rule_id" in cfg, f"Missing 'rule_id' for {trigger}"
        assert "missing_outcome" in cfg, f"Missing 'missing_outcome' for {trigger}"


# ── System topic triggers ─────────────────────────────────────────────────────


def test_system_topic_triggers_is_non_empty_set():
    assert isinstance(_SYSTEM_TOPIC_TRIGGERS, set)
    assert len(_SYSTEM_TOPIC_TRIGGERS) > 0


def test_system_topic_triggers_contains_on_error():
    assert "OnError" in _SYSTEM_TOPIC_TRIGGERS


# ── Compiled patterns ─────────────────────────────────────────────────────────


def test_injection_patterns_compiled_and_non_empty():
    assert len(_INJECTION_PATTERNS) > 0
    for p in _INJECTION_PATTERNS:
        assert hasattr(p, "search"), "Each injection pattern must be a compiled re.Pattern"


def test_injection_patterns_detect_jailbreak():
    matches = any(p.search("jailbreak the agent") for p in _INJECTION_PATTERNS)
    assert matches, "injection patterns must detect 'jailbreak'"


def test_injection_patterns_detect_ignore_instructions():
    matches = any(p.search("ignore previous instructions") for p in _INJECTION_PATTERNS)
    assert matches, "injection patterns must detect 'ignore previous instructions'"


def test_secret_patterns_compiled_and_non_empty():
    assert len(_SECRET_PATTERNS) > 0
    for p in _SECRET_PATTERNS:
        assert hasattr(p, "search"), "Each secret pattern must be a compiled re.Pattern"


def test_secret_patterns_detect_password():
    matches = any(p.search("password=s3cr3t") for p in _SECRET_PATTERNS)
    assert matches, "secret patterns must detect 'password=...'"


def test_secret_patterns_detect_api_key():
    matches = any(p.search("api_key=ABCDEF123456") for p in _SECRET_PATTERNS)
    assert matches, "secret patterns must detect 'api_key=...'"


# ── Rule definitions ──────────────────────────────────────────────────────────


def test_rules_dict_is_non_empty():
    assert isinstance(_RULES, dict)
    assert len(_RULES) > 0


def test_rules_contain_all_expected_ids():
    expected = {
        "SOL001",
        "SOL002",
        "SOL003",
        "SOL004",
        "SOL005",
        "AGT000",
        "AGT001",
        "AGT002",
        "AGT003",
        "AGT004",
        "AGT005",
        "AGT006",
        "AGT007",
        "AGT008",
        "TOP000",
        "TOP001",
        "TOP002",
        "TOP003",
        "TOP004",
        "TOP005",
        "KNO001",
        "KNO002",
        "KNO003",
        "KNO004",
        "SEC001",
        "SEC002",
        "SEC003",
        "DEP001",
        "DEP002",
        "DEP003",
        "DEP004",
    }
    for rule_id in expected:
        assert rule_id in _RULES, f"Rule '{rule_id}' missing from solution_checks.yaml"


def test_each_rule_has_category_and_outcomes():
    for rule_id, rule_def in _RULES.items():
        assert "category" in rule_def, f"Rule '{rule_id}' missing 'category'"
        assert "outcomes" in rule_def, f"Rule '{rule_id}' missing 'outcomes'"
        assert isinstance(rule_def["outcomes"], dict), f"Rule '{rule_id}' outcomes must be a dict"
        assert len(rule_def["outcomes"]) > 0, f"Rule '{rule_id}' has no outcomes"


def test_each_outcome_has_severity_title_detail():
    valid_severities = {"pass", "warning", "fail", "info"}
    for rule_id, rule_def in _RULES.items():
        for outcome_name, outcome_def in rule_def["outcomes"].items():
            loc = f"{rule_id}.{outcome_name}"
            assert "severity" in outcome_def, f"{loc}: missing 'severity'"
            assert outcome_def["severity"] in valid_severities, f"{loc}: invalid severity '{outcome_def['severity']}'"
            assert "title" in outcome_def, f"{loc}: missing 'title'"
            assert "detail" in outcome_def, f"{loc}: missing 'detail'"


# ── _rule() helper ────────────────────────────────────────────────────────────


def test_rule_returns_correct_dict_structure():
    result = _rule("SOL001", "pass")
    assert result["rule_id"] == "SOL001"
    assert result["category"] == "Solution"
    assert result["severity"] == "pass"
    assert isinstance(result["title"], str)
    assert isinstance(result["detail"], str)
    assert result["title"]  # non-empty


def test_rule_formats_title_placeholder():
    result = _rule("SOL002", "warn", prefix="new")
    assert "new" in result["title"]


def test_rule_formats_detail_placeholder():
    result = _rule("SOL003", "pass", version="2.0.0.0")
    assert "2.0.0.0" in result["detail"]


def test_rule_handles_missing_placeholder_gracefully():
    # Calling without required placeholder should not raise
    result = _rule("SOL002", "warn")
    assert result["rule_id"] == "SOL002"
    assert isinstance(result["title"], str)


def test_rule_unknown_rule_id_returns_fallback():
    result = _rule("UNKNOWN999", "someoutcome")
    assert result["rule_id"] == "UNKNOWN999"
    assert result["severity"] == "info"  # default when outcome not found
    assert result["category"] == ""


def test_rule_unknown_outcome_returns_fallback():
    result = _rule("SOL001", "nonexistent_outcome")
    assert result["rule_id"] == "SOL001"
    assert result["severity"] == "info"  # default


def test_rule_sol001_missing_is_fail():
    r = _rule("SOL001", "missing")
    assert r["severity"] == "fail"
    assert r["category"] == "Solution"


def test_rule_agt002_fail_formats_moderation():
    r = _rule("AGT002", "fail", moderation="none")
    assert "none" in r["title"]


def test_rule_top003_warn_formats_count_and_names():
    r = _rule("TOP003", "warn", count=3, names="Topic A, Topic B, Topic C")
    assert "3" in r["title"]
    assert "Topic A" in r["detail"]


def test_rule_kno002_pass_formats_max_mb():
    r = _rule("KNO002", "pass", max_mb=20)
    assert "20" in r["detail"]


def test_rule_sec001_fail_formats_count_and_details():
    r = _rule("SEC001", "fail", count=2, details="'Topic X' (matched: \"jailbreak\")")
    assert "2" in r["title"]
    assert "Topic X" in r["detail"]


# ── check_solution_zip integration ────────────────────────────────────────────


def _make_minimal_zip(files: dict[str, str]) -> bytes:
    """Build an in-memory ZIP from a dict of path → content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_check_solution_zip_rejects_non_solution_zip():
    data = _make_minimal_zip({"readme.txt": "hello"})
    result = check_solution_zip(data)
    assert result["error"]
    assert not result["results"]


def test_check_solution_zip_rejects_bad_zip():
    result = check_solution_zip(b"not a zip")
    assert result["error"]
    assert "Invalid ZIP" in result["error"]


def _make_solution_zip(schema: str = "mybot", managed: str = "0") -> bytes:
    """Build a minimal but valid-structure solution ZIP."""
    solution_xml = f"""<ImportExportXml>
  <SolutionManifest>
    <UniqueName>TestSolution</UniqueName>
    <Version>2.0.0.0</Version>
    <Managed>{managed}</Managed>
    <Publisher>
      <CustomizationPrefix>myorg</CustomizationPrefix>
    </Publisher>
    <Descriptions>
      <Description description="Test solution" />
    </Descriptions>
  </SolutionManifest>
</ImportExportXml>"""
    config = json.dumps(
        {
            "aISettings": {
                "contentModeration": "Medium",
                "useModelKnowledge": False,
                "isSemanticSearchEnabled": True,
                "isFileAnalysisEnabled": False,
            },
            "isAgentConnectable": False,
            "publishOnImport": False,
        }
    )
    return _make_minimal_zip(
        {
            "solution.xml": solution_xml,
            f"bots/{schema}/configuration.json": config,
        }
    )


def test_check_solution_zip_returns_all_required_keys():
    result = check_solution_zip(_make_solution_zip())
    for key in (
        "results",
        "agent_name",
        "solution_name",
        "pass_count",
        "warn_count",
        "fail_count",
        "info_count",
        "error",
    ):
        assert key in result, f"Missing key '{key}' in check_solution_zip result"


def test_check_solution_zip_no_error_on_valid_zip():
    result = check_solution_zip(_make_solution_zip())
    assert result["error"] == ""


def test_check_solution_zip_results_have_correct_shape():
    result = check_solution_zip(_make_solution_zip())
    for r in result["results"]:
        assert "rule_id" in r
        assert "category" in r
        assert "severity" in r
        assert "title" in r
        assert "detail" in r
        assert r["severity"] in ("pass", "warning", "fail", "info")


def test_check_solution_zip_categories_come_from_yaml():
    """Every category in the results must come from a YAML rule definition."""
    result = check_solution_zip(_make_solution_zip())
    yaml_categories = {rule_def["category"] for rule_def in _RULES.values()}
    for r in result["results"]:
        assert r["category"] in yaml_categories, f"Unexpected category '{r['category']}' — not defined in YAML"


def test_check_solution_zip_detects_managed_solution():
    result = check_solution_zip(_make_solution_zip(managed="1"))
    sol005 = next((r for r in result["results"] if r["rule_id"] == "SOL005"), None)
    assert sol005 is not None
    assert sol005["severity"] == "info"
    assert "managed" in sol005["title"].lower()


def test_check_solution_zip_detects_unmanaged_solution():
    result = check_solution_zip(_make_solution_zip(managed="0"))
    sol005 = next((r for r in result["results"] if r["rule_id"] == "SOL005"), None)
    assert sol005 is not None
    assert sol005["severity"] == "info"
    assert "unmanaged" in sol005["title"].lower()


def test_check_solution_zip_missing_solution_xml_is_fail():
    data = _make_minimal_zip({"bots/mybot/configuration.json": "{}"})
    result = check_solution_zip(data)
    sol001 = next((r for r in result["results"] if r["rule_id"] == "SOL001"), None)
    assert sol001 is not None
    assert sol001["severity"] == "fail"


def test_check_solution_zip_custom_publisher_prefix_passes():
    result = check_solution_zip(_make_solution_zip())
    sol002 = next((r for r in result["results"] if r["rule_id"] == "SOL002"), None)
    assert sol002 is not None
    assert sol002["severity"] == "pass"
    assert "myorg" in sol002["title"]


def test_check_solution_zip_count_consistency():
    result = check_solution_zip(_make_solution_zip())
    results = result["results"]
    assert result["pass_count"] == sum(1 for r in results if r["severity"] == "pass")
    assert result["warn_count"] == sum(1 for r in results if r["severity"] == "warning")
    assert result["fail_count"] == sum(1 for r in results if r["severity"] == "fail")
    assert result["info_count"] == sum(1 for r in results if r["severity"] == "info")


# ── _check_dependencies tests ─────────────────────────────────────────────────


def _make_zip_with_deps(
    cr_schemas: list[str] | None = None,
    ev_schemas: list[str] | None = None,
    missing_xml: str = "",
    flow_names: list[str] | None = None,
) -> bytes:
    """Build a minimal solution ZIP with configurable dependency artefacts."""
    files: dict[str, str] = {
        "solution.xml": f"""<ImportExportXml>
  <SolutionManifest>
    <UniqueName>TestSolution</UniqueName>
    <Version>1.0.0.0</Version>
    <Managed>0</Managed>
    <Publisher><CustomizationPrefix>myorg</CustomizationPrefix></Publisher>
    <Descriptions><Description description="test" /></Descriptions>
    <RootComponents />
    {missing_xml}
  </SolutionManifest>
</ImportExportXml>""",
        "bots/mybot/configuration.json": "{}",
    }
    for schema in (cr_schemas or []):
        files[f"connectionreferences/{schema}/.placeholder"] = ""
    for schema in (ev_schemas or []):
        files[f"environmentvariabledefinitions/{schema}/.placeholder"] = ""
    for name in (flow_names or []):
        import json as _json
        files[f"Workflows/{name}.json"] = _json.dumps(
            {"properties": {"displayName": name}, "name": name}
        )
    return _make_minimal_zip(files)


def test_dep001_reports_connection_references_present():
    data = _make_zip_with_deps(cr_schemas=["cr_sharepoint_abc", "cr_office365_xyz"])
    result = check_solution_zip(data)
    dep001 = next((r for r in result["results"] if r["rule_id"] == "DEP001"), None)
    assert dep001 is not None
    assert dep001["severity"] == "info"
    assert "2" in dep001["title"]


def test_dep001_pass_when_no_connection_references():
    data = _make_zip_with_deps()
    result = check_solution_zip(data)
    dep001 = next((r for r in result["results"] if r["rule_id"] == "DEP001"), None)
    assert dep001 is not None
    assert dep001["severity"] == "pass"


def test_dep002_reports_environment_variables_present():
    data = _make_zip_with_deps(ev_schemas=["myapp_baseurl"])
    result = check_solution_zip(data)
    dep002 = next((r for r in result["results"] if r["rule_id"] == "DEP002"), None)
    assert dep002 is not None
    assert dep002["severity"] == "info"
    assert "1" in dep002["title"]


def test_dep002_pass_when_no_environment_variables():
    data = _make_zip_with_deps()
    result = check_solution_zip(data)
    dep002 = next((r for r in result["results"] if r["rule_id"] == "DEP002"), None)
    assert dep002 is not None
    assert dep002["severity"] == "pass"


def test_dep003_fails_when_missing_dependencies_present():
    missing_xml = """<MissingDependencies>
      <MissingDependency>
        <Required type="30" schemaName="MyFlow" displayName="My Flow" />
        <Dependent type="431" id="{00000000-0000-0000-0000-000000000001}" />
      </MissingDependency>
    </MissingDependencies>"""
    data = _make_zip_with_deps(missing_xml=missing_xml)
    result = check_solution_zip(data)
    dep003 = next((r for r in result["results"] if r["rule_id"] == "DEP003"), None)
    assert dep003 is not None
    assert dep003["severity"] == "fail"
    # displayName takes precedence over schemaName in the detail
    assert "Flow" in dep003["detail"]


def test_dep003_pass_when_no_missing_dependencies():
    data = _make_zip_with_deps()
    result = check_solution_zip(data)
    dep003 = next((r for r in result["results"] if r["rule_id"] == "DEP003"), None)
    assert dep003 is not None
    assert dep003["severity"] == "pass"


def test_dep004_reports_cloud_flows_present():
    data = _make_zip_with_deps(flow_names=["My Approval Flow"])
    result = check_solution_zip(data)
    dep004 = next((r for r in result["results"] if r["rule_id"] == "DEP004"), None)
    assert dep004 is not None
    assert dep004["severity"] == "info"
    assert "1" in dep004["title"]


def test_dep004_pass_when_no_flows():
    data = _make_zip_with_deps()
    result = check_solution_zip(data)
    dep004 = next((r for r in result["results"] if r["rule_id"] == "DEP004"), None)
    assert dep004 is not None
    assert dep004["severity"] == "pass"


def test_agt007_no_auth_when_auth_settings_absent():
    data = _make_solution_zip()  # config has no authSettings
    result = check_solution_zip(data)
    agt007 = next((r for r in result["results"] if r["rule_id"] == "AGT007"), None)
    assert agt007 is not None
    assert agt007["severity"] == "info"


def test_agt007_aad_pass():
    config = json.dumps(
        {
            "aISettings": {"contentModeration": "Medium"},
            "authSettings": {"authMode": "AAD"},
        }
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "solution.xml",
            """<ImportExportXml>
  <SolutionManifest>
    <UniqueName>TestSolution</UniqueName>
    <Version>2.0.0.0</Version>
    <Managed>0</Managed>
    <Publisher><CustomizationPrefix>myorg</CustomizationPrefix></Publisher>
    <Descriptions><Description description="test" /></Descriptions>
  </SolutionManifest>
</ImportExportXml>""",
        )
        zf.writestr("bots/mybot/configuration.json", config)
    result = check_solution_zip(buf.getvalue())
    agt007 = next((r for r in result["results"] if r["rule_id"] == "AGT007"), None)
    assert agt007 is not None
    assert agt007["severity"] == "pass"
    assert "AAD" in agt007["title"] or "Azure" in agt007["title"] or "aad" in agt007["title"].lower()


# ── _build_prereqs tests (via analyze_deps_zip_bytes_report) ──────────────────


def test_deps_analyzer_prereqs_returned_by_report():
    """analyze_deps_zip_bytes_report returns a 'prereqs' dict with expected keys."""
    from deps_analyzer import analyze_deps_zip_bytes_report

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "solution.xml",
            """<ImportExportXml>
  <SolutionManifest>
    <UniqueName>TestSolution</UniqueName>
    <Version>1.0.0.0</Version>
    <Managed>0</Managed>
    <Publisher><CustomizationPrefix>myorg</CustomizationPrefix></Publisher>
    <Descriptions><Description description="test" /></Descriptions>
    <RootComponents />
  </SolutionManifest>
</ImportExportXml>""",
        )
        zf.writestr("bots/mybot/configuration.json", "{}")
        zf.writestr("connectionreferences/cr_sharepoint_abc/.placeholder", "")
        zf.writestr("environmentvariabledefinitions/myapp_baseurl/.placeholder", "")

    report = analyze_deps_zip_bytes_report(buf.getvalue())
    assert "prereqs" in report
    prereqs = report["prereqs"]
    for key in ("connection_references", "environment_variables", "custom_connectors", "ai_models", "cloud_flows", "missing_dependencies"):
        assert key in prereqs, f"prereqs missing key '{key}'"
    cr_schemas = [c["schema"] for c in prereqs["connection_references"]]
    assert "cr_sharepoint_abc" in cr_schemas
    ev_schemas = [e["schema"] for e in prereqs["environment_variables"]]
    assert "myapp_baseurl" in ev_schemas


def test_deps_analyzer_prereqs_empty_for_minimal_solution():
    """prereqs contains all keys but empty lists when no dependencies exist."""
    from deps_analyzer import analyze_deps_zip_bytes_report

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "solution.xml",
            """<ImportExportXml>
  <SolutionManifest>
    <UniqueName>TestSolution</UniqueName>
    <Version>1.0.0.0</Version>
    <Managed>0</Managed>
    <Publisher><CustomizationPrefix>myorg</CustomizationPrefix></Publisher>
    <Descriptions><Description description="test" /></Descriptions>
    <RootComponents />
  </SolutionManifest>
</ImportExportXml>""",
        )
        zf.writestr("bots/mybot/configuration.json", "{}")

    report = analyze_deps_zip_bytes_report(buf.getvalue())
    prereqs = report["prereqs"]
    assert prereqs["connection_references"] == []
    assert prereqs["environment_variables"] == []
    assert prereqs["missing_dependencies"] == []
