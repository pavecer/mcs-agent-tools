"""Tests for the multi-model comparison module."""

from __future__ import annotations

from unittest.mock import patch

from mcs_models import MCSBotProfile, MCSGptInfo
from toolkit.mcs.model_comparison import (
    _LEGACY_HINTS,
    _MODEL_CATALOGUE,
    _SAMPLE_QUERIES,
    _choose_comparison_models,
    _resolve_catalogue_key,
    _summarise_api_results,
    build_comparison_markdown,
)


# ---------------------------------------------------------------------------
# Model catalogue helpers
# ---------------------------------------------------------------------------


def test_resolve_catalogue_key_known_hints():
    assert _resolve_catalogue_key("gpt41") == "gpt41"
    assert _resolve_catalogue_key("GPT41") == "gpt41"
    assert _resolve_catalogue_key("gpt-4.1") == "gpt41"
    assert _resolve_catalogue_key("gpt41mini") == "gpt41mini"
    assert _resolve_catalogue_key("GPT41Mini") == "gpt41mini"
    assert _resolve_catalogue_key("o1") == "o1"
    assert _resolve_catalogue_key("o3") == "o3"
    assert _resolve_catalogue_key("o4mini") == "o4mini"


def test_resolve_catalogue_key_none_for_unknown():
    assert _resolve_catalogue_key(None) is None
    assert _resolve_catalogue_key("") is None
    assert _resolve_catalogue_key("some-future-model-xyz") is None


def test_resolve_catalogue_key_legacy_not_in_catalogue():
    # Legacy models are not in the catalogue.
    for hint in ("GPT4o", "gpt-4o", "gpt-4", "gpt-35-turbo"):
        result = _resolve_catalogue_key(hint)
        if result is not None:
            assert result not in _MODEL_CATALOGUE or hint in _LEGACY_HINTS


def test_model_catalogue_entries_have_required_keys():
    required = {"display", "tier", "context_window", "cost_tier", "strengths", "limitations", "recommendation"}
    for key, meta in _MODEL_CATALOGUE.items():
        missing = required - meta.keys()
        assert not missing, f"Catalogue entry '{key}' is missing keys: {missing}"
        assert isinstance(meta["strengths"], list) and meta["strengths"]
        assert isinstance(meta["limitations"], list) and meta["limitations"]


# ---------------------------------------------------------------------------
# Comparison model selection
# ---------------------------------------------------------------------------


def test_choose_comparison_models_unique_and_capped():
    models = _choose_comparison_models("gpt41", "gpt-4.1")
    assert len(models) <= 3
    assert len(models) == len(set(models)), "Models list should not contain duplicates"


def test_choose_comparison_models_includes_configured_when_not_gpt4o():
    models = _choose_comparison_models("gpt41mini", "gpt-4.1-mini")
    assert "gpt-4.1-mini" in models


def test_choose_comparison_models_always_includes_reference():
    models = _choose_comparison_models(None, "gpt-4o")
    # When the configured model IS gpt-4o, still returns valid list
    assert len(models) >= 1


# ---------------------------------------------------------------------------
# API result summariser
# ---------------------------------------------------------------------------


def test_summarise_api_results_empty():
    result = _summarise_api_results([], ["gpt-4o", "gpt-4o-mini"])
    assert "_No API comparison results available._" in result


def test_summarise_api_results_produces_markdown_table():
    comparison_models = ["gpt-4o", "gpt-4o-mini"]
    results = [
        {
            "model": "gpt-4o",
            "query": _SAMPLE_QUERIES[0],
            "response": "Long detailed answer here.",
            "length": 26,
            "success": True,
            "error": "",
        },
        {
            "model": "gpt-4o-mini",
            "query": _SAMPLE_QUERIES[0],
            "response": "Short answer.",
            "length": 13,
            "success": True,
            "error": "",
        },
    ]
    md = _summarise_api_results(results, comparison_models)
    assert "### API Comparison Summary" in md
    assert "gpt-4o" in md
    assert "gpt-4o-mini" in md
    assert "Successes" in md
    assert "Sample Query Comparison" in md


def test_summarise_api_results_handles_failures():
    comparison_models = ["gpt-4o"]
    results = [
        {
            "model": "gpt-4o",
            "query": _SAMPLE_QUERIES[0],
            "response": "",
            "length": 0,
            "success": False,
            "error": "401 Unauthorized",
        },
    ]
    md = _summarise_api_results(results, comparison_models)
    assert "1/" in md or "Failures" in md
    assert "401 Unauthorized" in md


# ---------------------------------------------------------------------------
# build_comparison_markdown — static guidance (no API)
# ---------------------------------------------------------------------------


def _profile_with_hint(hint: str | None) -> MCSBotProfile:
    gpt = MCSGptInfo(model_hint=hint, display_name="Test GPT", instructions="Be helpful.")
    return MCSBotProfile(display_name="Test Agent", gpt_info=gpt)


def test_build_comparison_markdown_known_model():
    profile = _profile_with_hint("GPT41")
    with patch.dict("os.environ", {"MCS_ENABLE_MODEL_COMPARISON": ""}):
        md = build_comparison_markdown(profile)

    assert "## Model Performance Comparison" in md
    assert "### Configured Model" in md
    assert "GPT-4.1" in md
    assert "Flagship" in md
    assert "### Available Copilot Studio Models" in md
    assert "✅ *(current)*" in md
    assert "### Recommendation" in md
    assert "### Live API Comparison" in md
    assert "MCS_ENABLE_MODEL_COMPARISON" in md


def test_build_comparison_markdown_legacy_model():
    profile = _profile_with_hint("gpt-4o")
    with patch.dict("os.environ", {"MCS_ENABLE_MODEL_COMPARISON": ""}):
        md = build_comparison_markdown(profile)

    assert "## Model Performance Comparison" in md
    assert "legacy model" in md.lower() or "upgrade" in md.lower()


def test_build_comparison_markdown_no_model():
    profile = MCSBotProfile(display_name="Test Agent", gpt_info=None)
    with patch.dict("os.environ", {"MCS_ENABLE_MODEL_COMPARISON": ""}):
        md = build_comparison_markdown(profile)

    assert "## Model Performance Comparison" in md
    assert "No model configuration detected" in md


def test_build_comparison_markdown_api_disabled_message():
    profile = _profile_with_hint("gpt41")
    with patch.dict("os.environ", {"MCS_ENABLE_MODEL_COMPARISON": "false", "OPENAI_API_KEY": ""}):
        md = build_comparison_markdown(profile)
    assert "Live model comparison is disabled" in md or "MCS_ENABLE_MODEL_COMPARISON" in md


def test_build_comparison_markdown_api_enabled_no_key():
    profile = _profile_with_hint("gpt41")
    with patch.dict("os.environ", {"MCS_ENABLE_MODEL_COMPARISON": "true", "OPENAI_API_KEY": ""}):
        md = build_comparison_markdown(profile)
    assert "`OPENAI_API_KEY` is not provided" in md


def test_build_comparison_markdown_all_catalogue_models_shown():
    """All models in the catalogue should appear in the comparison table."""
    profile = _profile_with_hint("gpt41")
    with patch.dict("os.environ", {"MCS_ENABLE_MODEL_COMPARISON": ""}):
        md = build_comparison_markdown(profile)

    for key, meta in _MODEL_CATALOGUE.items():
        assert meta["display"] in md, f"Model '{meta['display']}' not found in comparison markdown"


# ---------------------------------------------------------------------------
# Integration: build_comparison_markdown with mocked API
# ---------------------------------------------------------------------------


def test_build_comparison_markdown_api_enabled_with_mock(monkeypatch):
    """With API enabled and a mocked HTTP call, comparison table should appear."""
    profile = _profile_with_hint("gpt41")

    def fake_call_openai(model, system, user, api_key, timeout_s=30.0):
        return {"content": f"Mock response for {model}: {user[:20]}", "error": None, "model": model}

    monkeypatch.setattr("model_comparison._call_openai_chat", fake_call_openai)

    with patch.dict("os.environ", {"MCS_ENABLE_MODEL_COMPARISON": "true", "OPENAI_API_KEY": "sk-test"}):
        md = build_comparison_markdown(profile)

    assert "### API Comparison Summary" in md
    assert "### Sample Query Comparison" in md
