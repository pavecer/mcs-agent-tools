"""Tests for Dynamic Planner Trace Analysis — extraction, scoring, and rendering."""

from __future__ import annotations

import pytest

from toolkit.mcs.models import (
    MCSConversationTimeline,
    MCSPlannerAnalysis,
    MCSPlannerStepTrace,
    MCSSearchResultItem,
)
from toolkit.mcs.planner_analysis import (
    _extract_terms,
    _normalize,
    _parse_execution_time,
    _score_item,
    _score_step,
    build_planner_analysis,
)
from toolkit.mcs.renderer import render_planner_analysis


# ── Normalisation helpers ──────────────────────────────────────────────────────


def test_normalize_strips_diacritics():
    assert _normalize("Croí Cónaithe") == "croi conaithe"


def test_normalize_lowercases_and_removes_punctuation():
    assert _normalize("Affordable-Housing, Scheme!") == "affordable housing  scheme "


def test_extract_terms_removes_stop_words():
    terms = _extract_terms("Can you tell me about the housing scheme")
    assert "housing" in terms
    assert "scheme" in terms
    assert "can" not in terms
    assert "the" not in terms
    assert "you" not in terms


def test_extract_terms_deduplicates():
    terms = _extract_terms("housing housing scheme")
    assert terms.count("housing") == 1


def test_extract_terms_filters_short_words():
    terms = _extract_terms("go to a big house")
    assert "go" not in terms
    # 'big' has 3 chars → included
    assert "big" in terms


# ── Execution time parser ──────────────────────────────────────────────────────


def test_parse_execution_time_standard():
    ms = _parse_execution_time("00:00:01.989")
    assert ms == pytest.approx(1989.0)


def test_parse_execution_time_with_long_fraction():
    ms = _parse_execution_time("00:00:01.9891474")
    assert ms == pytest.approx(1989.1474)


def test_parse_execution_time_none_returns_zero():
    assert _parse_execution_time(None) == 0.0


def test_parse_execution_time_empty_returns_zero():
    assert _parse_execution_time("") == 0.0


# ── Item scoring ──────────────────────────────────────────────────────────────


def test_score_item_full_match():
    item = MCSSearchResultItem(name="Affordable Housing Scheme Overview.pdf")
    score = _score_item(item, ["affordable", "housing", "scheme"])
    assert score == pytest.approx(1.0)


def test_score_item_no_match():
    item = MCSSearchResultItem(name="Joint Account Disputes Note.pdf")
    score = _score_item(item, ["affordable", "housing", "scheme"])
    assert score == 0.0


def test_score_item_partial_match():
    item = MCSSearchResultItem(name="Housing Act Overview.pdf")
    score = _score_item(item, ["affordable", "housing", "scheme"])
    # only 'housing' matches → 1/3
    assert score == pytest.approx(1 / 3)


def test_score_item_uses_url():
    item = MCSSearchResultItem(name="Document.pdf", url="https://example.com/affordable-housing")
    score = _score_item(item, ["affordable", "housing", "scheme"])
    # 'affordable' and 'housing' in URL → 2/3
    assert score == pytest.approx(2 / 3)


def test_score_item_empty_terms_returns_zero():
    item = MCSSearchResultItem(name="Housing Scheme.pdf")
    assert _score_item(item, []) == 0.0


# ── Step scoring ──────────────────────────────────────────────────────────────


def _make_step(**kwargs) -> MCSPlannerStepTrace:
    return MCSPlannerStepTrace(**kwargs)


def test_score_step_high_quality():
    step = _make_step(
        user_ask="affordable housing scheme",
        search_query="affordable housing scheme",
        search_keywords="affordable, housing",
        knowledge_sources_candidate=["agent.topic.GuidanceNotes"],
        knowledge_sources_output=["agent.topic.GuidanceNotes"],
        result_items=[
            MCSSearchResultItem(name="Affordable Housing Scheme Guide.pdf"),
        ],
    )
    _score_step(step)
    assert step.item_hit_rate_pct == pytest.approx(100.0)
    assert step.source_fidelity_pct == pytest.approx(100.0)
    assert step.query_fidelity_pct == pytest.approx(100.0)
    assert step.overall_success_pct == pytest.approx(100.0)
    assert "HIGH_QUALITY" in step.score_flags
    assert "TOP_RESULT_RELEVANT" in step.score_flags
    assert "ALL_SOURCES_RETURNED" in step.score_flags


def test_score_step_no_results():
    step = _make_step(user_ask="quarterly report", result_items=[])
    _score_step(step)
    assert "NO_RESULTS" in step.score_flags
    assert step.item_hit_rate_pct == 0.0
    assert step.matched_item_count == 0


def test_score_step_sources_filtered():
    step = _make_step(
        user_ask="legal guidance",
        search_query="legal guidance",
        knowledge_sources_candidate=["src_a", "src_b", "src_c"],
        knowledge_sources_output=["src_a"],
        result_items=[MCSSearchResultItem(name="Legal Guidance Note.pdf")],
    )
    _score_step(step)
    assert "SOURCES_FILTERED" in step.score_flags
    assert step.source_fidelity_pct == pytest.approx(33.3, abs=0.1)


def test_score_step_ask_term_counts_stored():
    step = _make_step(
        user_ask="affordable housing",
        search_query="affordable housing scheme",
    )
    _score_step(step)
    assert step.ask_term_count == 2  # affordable, housing
    assert step.query_matched_term_count == 2  # both found in search_query


def test_score_step_diacritics_folded():
    """'Croí Cónaithe' in the query should match 'croi conaithe' in ask (after folding)."""
    step = _make_step(
        user_ask="affordable housing scheme croai conaithe",
        search_query="affordable housing scheme Croí Cónaithe",
        result_items=[
            MCSSearchResultItem(
                name="Credit Legal Services Guidence Note on Affordable Housing Scheme Overview.pdf"
            ),
            MCSSearchResultItem(name="Retail Legal Note on Joint Account Disputes.pdf"),
        ],
    )
    _score_step(step)
    # Top result contains affordable + housing + scheme → score > 0 → relevant
    assert step.result_items[0].relevance_score > 0.0
    # Second result has no matching terms
    assert step.result_items[1].relevance_score == 0.0
    assert step.matched_item_count == 1
    assert "TOP_RESULT_RELEVANT" in step.score_flags


# ── build_planner_analysis ─────────────────────────────────────────────────────


def _make_activities(
    plan_id: str = "plan-001",
    step_id: str = "step-001",
    ask: str = "Tell me about affordable housing",
    thought: str = "I should search for affordable housing guidance.",
    search_query: str = "affordable housing",
    search_keywords: str = "affordable, housing",
    knowledge_sources: list[str] | None = None,
    output_sources: list[str] | None = None,
    results: list[dict] | None = None,
    exec_time: str = "00:00:01.500000",
) -> list[dict]:
    knowledge_sources = knowledge_sources or ["agent.topic.GuidanceNotes"]
    output_sources = output_sources if output_sources is not None else knowledge_sources
    results = results or [
        {
            "Name": "Affordable Housing Guidance.pdf",
            "Url": "https://sharepoint.com/docs/AffordableHousing.pdf",
            "FileType": "pdf",
            "SourceId": "src-1",
        }
    ]
    return [
        {
            "type": "event",
            "valueType": "DynamicPlanReceivedDebug",
            "value": {"ask": ask, "planIdentifier": plan_id},
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepTriggered",
            "value": {
                "planIdentifier": plan_id,
                "stepId": step_id,
                "taskDialogId": "P:UniversalSearchTool",
                "type": "KnowledgeSource",
                "thought": thought,
                "state": "inProgress",
                "hasRecommendations": False,
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepBindUpdate",
            "value": {
                "planIdentifier": plan_id,
                "stepId": step_id,
                "taskDialogId": "P:UniversalSearchTool",
                "arguments": {
                    "search_query": search_query,
                    "search_keywords": search_keywords,
                    "enable_summarization": False,
                },
            },
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "value": {
                "toolId": "P:UniversalSearchTool",
                "knowledgeSources": knowledge_sources,
                "outputKnowledgeSources": output_sources,
                "fullResults": [],
                "filteredResults": [],
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepFinished",
            "value": {
                "planIdentifier": plan_id,
                "stepId": step_id,
                "taskDialogId": "P:UniversalSearchTool",
                "state": "completed",
                "executionTime": exec_time,
                "observation": {
                    "search_result": {
                        "search_errors": [],
                        "search_results": results,
                    }
                },
            },
        },
    ]


def test_build_planner_analysis_empty():
    analysis = build_planner_analysis([])
    assert analysis.has_planner_events is False
    assert analysis.step_count == 0
    assert analysis.plan_count == 0


def test_build_planner_analysis_ignores_non_event_types():
    activities = [
        {"type": "message", "valueType": "DynamicPlanReceivedDebug", "value": {}},
        {"type": "typing", "valueType": "DynamicPlanStepTriggered", "value": {}},
    ]
    analysis = build_planner_analysis(activities)
    assert analysis.has_planner_events is False


def test_build_planner_analysis_extracts_all_fields():
    activities = _make_activities()
    analysis = build_planner_analysis(activities)

    assert analysis.has_planner_events is True
    assert analysis.step_count == 1
    assert analysis.plan_count == 1

    step = analysis.steps[0]
    assert step.user_ask == "Tell me about affordable housing"
    assert step.planner_thought == "I should search for affordable housing guidance."
    assert step.search_query == "affordable housing"
    assert step.search_keywords == "affordable, housing"
    assert step.enable_summarization is False
    assert step.knowledge_sources_candidate == ["agent.topic.GuidanceNotes"]
    assert step.knowledge_sources_output == ["agent.topic.GuidanceNotes"]
    assert len(step.result_items) == 1
    assert step.result_items[0].name == "Affordable Housing Guidance.pdf"
    assert step.result_items[0].file_type == "pdf"
    assert step.execution_time_ms == pytest.approx(1500.0)
    assert step.step_state == "completed"


def test_build_planner_analysis_scores_steps():
    activities = _make_activities()
    analysis = build_planner_analysis(activities)
    step = analysis.steps[0]
    # Scores should be populated (not zero) after build
    assert step.overall_success_pct > 0.0
    assert step.query_fidelity_pct > 0.0


def test_build_planner_analysis_multiple_steps():
    act1 = _make_activities(plan_id="plan-1", step_id="step-1", ask="housing rules")
    act2 = _make_activities(plan_id="plan-2", step_id="step-2", ask="legal contracts")
    analysis = build_planner_analysis(act1 + act2)
    assert analysis.step_count == 2
    assert analysis.plan_count == 2
    asks = [s.user_ask for s in analysis.steps]
    assert "housing rules" in asks
    assert "legal contracts" in asks


def test_build_planner_analysis_handles_missing_bind_update():
    """Steps with no DynamicPlanStepBindUpdate should still produce a valid trace."""
    activities = [
        {
            "type": "event",
            "valueType": "DynamicPlanReceivedDebug",
            "value": {"ask": "test ask", "planIdentifier": "p1"},
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepTriggered",
            "value": {
                "planIdentifier": "p1",
                "stepId": "s1",
                "taskDialogId": "P:UniversalSearchTool",
                "type": "KnowledgeSource",
                "thought": "Searching...",
                "state": "inProgress",
                "hasRecommendations": False,
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepFinished",
            "value": {
                "planIdentifier": "p1",
                "stepId": "s1",
                "state": "completed",
                "executionTime": "00:00:00.500",
                "observation": {"search_result": {"search_errors": [], "search_results": []}},
            },
        },
    ]
    analysis = build_planner_analysis(activities)
    assert analysis.step_count == 1
    step = analysis.steps[0]
    assert step.search_query == ""
    assert step.user_ask == "test ask"


# ── Renderer ───────────────────────────────────────────────────────────────────


def test_render_planner_analysis_empty_returns_empty():
    timeline = MCSConversationTimeline()
    assert render_planner_analysis(timeline) == ""


def test_render_planner_analysis_no_steps_returns_empty():
    timeline = MCSConversationTimeline(
        planner_analysis=MCSPlannerAnalysis(has_planner_events=False)
    )
    assert render_planner_analysis(timeline) == ""


def test_render_planner_analysis_renders_section_header():
    step = MCSPlannerStepTrace(
        tool_id="P:UniversalSearchTool",
        user_ask="housing scheme",
        planner_thought="Need to search for housing.",
        search_query="housing scheme",
        knowledge_sources_candidate=["agent.topic.GuidanceNotes"],
        knowledge_sources_output=["agent.topic.GuidanceNotes"],
        result_items=[MCSSearchResultItem(name="Housing Guide.pdf", relevance_score=0.8)],
        overall_success_pct=80.0,
        query_fidelity_pct=100.0,
        item_hit_rate_pct=100.0,
        source_fidelity_pct=100.0,
        matched_item_count=1,
        ask_term_count=2,
        query_matched_term_count=2,
        score_flags=["HIGH_QUALITY", "TOP_RESULT_RELEVANT", "ALL_SOURCES_RETURNED"],
    )
    analysis = MCSPlannerAnalysis(plan_count=1, step_count=1, steps=[step], has_planner_events=True)
    timeline = MCSConversationTimeline(planner_analysis=analysis)
    result = render_planner_analysis(timeline)

    assert "## Dynamic Planner Trace Analysis" in result
    assert "UniversalSearchTool" in result
    assert "housing scheme" in result
    assert "Planner Reasoning" in result
    assert "Retrieval Quality Scorecard" in result
    # Raw flag names must NOT appear verbatim
    assert "HIGH_QUALITY" not in result
    # Human-readable label must appear
    assert "High retrieval quality" in result
    assert "Top result is relevant" in result
    assert "All sources returned results" in result


def test_render_planner_analysis_no_results_flag():
    step = MCSPlannerStepTrace(
        tool_id="P:UniversalSearchTool",
        user_ask="something obscure",
        result_items=[],
        score_flags=["NO_RESULTS", "LOW_QUALITY"],
        overall_success_pct=0.0,
    )
    analysis = MCSPlannerAnalysis(plan_count=1, step_count=1, steps=[step], has_planner_events=True)
    timeline = MCSConversationTimeline(planner_analysis=analysis)
    result = render_planner_analysis(timeline)

    assert "No documents were returned" in result
    assert "No results returned" in result


def test_render_planner_analysis_source_routing_shown():
    step = MCSPlannerStepTrace(
        tool_id="P:UniversalSearchTool",
        knowledge_sources_candidate=["agent.topic.TopicA", "agent.topic.TopicB"],
        knowledge_sources_output=["agent.topic.TopicA"],
        score_flags=["SOURCES_FILTERED", "LOW_QUALITY"],
    )
    analysis = MCSPlannerAnalysis(plan_count=1, step_count=1, steps=[step], has_planner_events=True)
    timeline = MCSConversationTimeline(planner_analysis=analysis)
    result = render_planner_analysis(timeline)

    assert "Knowledge Source Routing" in result
    assert "TopicA" in result
    assert "TopicB" in result
    assert "Filtered" in result or "filtered" in result


def test_render_planner_analysis_from_build_pipeline():
    """Full integration: build from activities, then render."""
    activities = _make_activities(
        ask="affordable housing scheme croai conaithe",
        search_query="affordable housing scheme Croí Cónaithe",
        search_keywords="affordable housing scheme, Croí Cónaithe",
        knowledge_sources=["agent.topic.GuidanceCLS", "agent.topic.GuidanceMisc", "agent.topic.GuidanceRetail"],
        output_sources=["agent.topic.GuidanceCLS", "agent.topic.GuidanceRetail"],
        results=[
            {
                "Name": "Credit Legal Services Guidence Note on Affordable Housing Scheme Overview.pdf",
                "Url": "https://sp.example.com/docs/AffordableHousing.pdf",
                "FileType": "pdf",
                "SourceId": "src-1",
            },
            {
                "Name": "Retail Legal Note on Joint Account Disputes.pdf",
                "Url": "https://sp.example.com/docs/JointAccounts.pdf",
                "FileType": "pdf",
                "SourceId": "src-2",
            },
        ],
        exec_time="00:00:01.9891474",
    )
    analysis = build_planner_analysis(activities)
    assert analysis.step_count == 1
    step = analysis.steps[0]

    # The first result is relevant; the second is not
    assert step.result_items[0].relevance_score > 0.0
    assert step.result_items[1].relevance_score == 0.0
    assert "TOP_RESULT_RELEVANT" in step.score_flags
    assert "SOURCES_FILTERED" in step.score_flags

    timeline = MCSConversationTimeline(planner_analysis=analysis)
    rendered = render_planner_analysis(timeline)

    assert "## Dynamic Planner Trace Analysis" in rendered
    assert "affordable housing scheme croai conaithe" in rendered
    assert "Retrieval Quality Scorecard" in rendered
    assert "GuidanceCLS" in rendered
    assert "GuidanceMisc" in rendered
