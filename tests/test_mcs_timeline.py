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
