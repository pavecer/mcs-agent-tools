"""Tests for transcript timeline diagnostics extraction."""

from __future__ import annotations

from mcs_models import MCSEventType
from mcs_timeline import build_timeline


def test_universal_search_query_and_result_extraction():
    activities = [
        {
            "type": "message",
            "timestamp": "2026-03-11T12:13:08.304+00:00",
            "from": {"role": "user"},
            "text": "How to address conflict of interest?",
            "channelData": {"webchat:internal:position": 1000},
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "timestamp": "2026-03-11T12:13:09.000+00:00",
            "from": {"role": "bot"},
            "value": {
                "request": {"searchQuery": "conflict of interest policy"},
                "knowledgeSources": ["sharepoint.policies", "confluence.hr"],
                "filteredResults": [{"id": 1}, {"id": 2}],
            },
            "channelData": {"webchat:internal:position": 2000},
        },
    ]

    timeline = build_timeline(activities, {})
    search_events = [e for e in timeline.events if e.event_type == MCSEventType.KNOWLEDGE_SEARCH]

    assert len(search_events) == 1
    event = search_events[0]
    assert event.search_query == "conflict of interest policy"
    assert event.details.get("source_count") == "2"
    assert event.details.get("result_count") == "2"


def test_universal_search_enriched_trace_extraction():
    activities = [
        {
            "type": "message",
            "timestamp": "2026-03-11T12:13:08.304+00:00",
            "from": {"role": "user"},
            "text": "Help me draft my goals",
            "channelData": {"webchat:internal:position": 1000},
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "timestamp": "2026-03-11T12:13:09.000+00:00",
            "from": {"role": "bot"},
            "value": {
                "knowledgeSources": ["sharepoint.myimpact", "dataverse.people"],
                "outputKnowledgeSources": ["sharepoint.myimpact"],
                "endpoints": [
                    "https://contoso.sharepoint.com/sites/MyImpact",
                    "https://contoso.sharepoint.com/sites/Values",
                ],
                "queryRewrittingOpenAIResponse": {
                    "Response": {
                        "RewrittenQuestion": "Help me identify my priorities and draft 2026 goals.",
                        "QuestionKeywords": "priorities 2026 goals",
                        "HypotheticalSnippetQuery": "Draft SMART goals aligned to company priorities.",
                    },
                    "PromptTokens": 100,
                    "CompletionTokens": 25,
                    "CapiResourceUsage": {"ModelName": "gpt-41-2025-04-14"},
                },
                "summarizationOpenAIResponse": {
                    "RawSummary": "Ask the user for role, scope, and priorities.",
                    "PromptTokens": 200,
                    "CompletionTokens": 40,
                },
                "searchResults": [
                    {
                        "url": "https://contoso.sharepoint.com/sites/MyImpact/SitePages/Goal-Setting.aspx",
                        "searchType": "SharepointSiteSearch",
                    }
                ],
                "verifiedSearchResults": [
                    {
                        "url": "https://contoso.sharepoint.com/sites/MyImpact/SitePages/Goal-Setting.aspx",
                        "searchType": "SharepointSiteSearch",
                    }
                ],
                "completionState": "AnswerNotFoundInSearchResults",
                "gptAnswerState": "Answer not Found in Search Results",
            },
            "channelData": {"webchat:internal:position": 2000},
        },
    ]

    timeline = build_timeline(activities, {})
    search_event = next(e for e in timeline.events if e.event_type == MCSEventType.KNOWLEDGE_SEARCH)

    assert search_event.search_trace is not None
    assert search_event.search_trace.rewrite_model_name == "gpt-41-2025-04-14"
    assert search_event.search_trace.rewritten_question == "Help me identify my priorities and draft 2026 goals."
    assert search_event.search_trace.result_count == 1
    assert search_event.search_trace.verified_result_count == 1
    assert search_event.search_trace.completion_state == "AnswerNotFoundInSearchResults"
    assert search_event.search_trace.endpoints[0] == "https://contoso.sharepoint.com/sites/MyImpact"


def test_debug_message_search_trace_becomes_knowledge_search_event():
    activities = [
        {
            "type": "message",
            "timestamp": "2026-03-11T12:13:09.000+00:00",
            "from": {"role": "debug"},
            "value": {
                "knowledgeSources": ["sharepoint.myimpact"],
                "queryRewrittingOpenAIResponse": {
                    "Response": {"RewrittenQuestion": "Draft my 2026 MyImpact goals."},
                    "CapiResourceUsage": {"ModelName": "gpt-41-2025-04-14"},
                },
                "searchResults": [{"url": "https://contoso.sharepoint.com/sites/MyImpact/SitePages/Goal-Setting.aspx"}],
                "verifiedSearchResults": [],
                "completionState": "AnswerNotFoundInSearchResults",
            },
            "channelData": {"webchat:internal:position": 2000},
        }
    ]

    timeline = build_timeline(activities, {})
    search_events = [e for e in timeline.events if e.event_type == MCSEventType.KNOWLEDGE_SEARCH]

    assert len(search_events) == 1
    assert search_events[0].search_query == "Draft my 2026 MyImpact goals."
    assert search_events[0].search_trace is not None
    assert search_events[0].search_trace.rewrite_model_name == "gpt-41-2025-04-14"


def test_timeline_counts_include_typing_and_events():
    activities = [
        {"type": "typing", "channelData": {"webchat:internal:position": 1000}},
        {
            "type": "message",
            "timestamp": "2026-03-11T12:13:08.304+00:00",
            "from": {"role": "user"},
            "text": "Ping",
            "channelData": {"webchat:internal:position": 2000},
        },
        {
            "type": "event",
            "valueType": "DynamicPlanReceived",
            "value": {"steps": []},
            "channelData": {"webchat:internal:position": 3000},
        },
    ]

    timeline = build_timeline(activities, {})

    assert timeline.total_activities == 3
    assert timeline.typing_count == 1
    assert timeline.message_count == 1
    assert timeline.event_count == 1
