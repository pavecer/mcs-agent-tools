"""Tests for transcript conversation flow rendering helpers."""

from __future__ import annotations

from mcs_models import MCSBotProfile, MCSConversationTimeline, MCSEventType, MCSTimelineEvent, MCSTopicConnection
from mcs_renderer import build_conversation_flow_items
from mcs_renderer import build_conversation_visual_summary
from mcs_renderer import render_topic_graph


def test_build_conversation_flow_items_emits_message_and_event_items():
    timeline = MCSConversationTimeline(
        events=[
            MCSTimelineEvent(
                timestamp="2026-03-10T16:11:55+00:00",
                event_type=MCSEventType.USER_MESSAGE,
                summary='User: "My VPN is not working, create ticket"',
            ),
            MCSTimelineEvent(
                timestamp="2026-03-10T16:11:58+00:00",
                event_type=MCSEventType.STEP_TRIGGERED,
                summary="Step start: ESS IT ServiceNow ITSM Create Ticket (Topic)",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-10T16:12:00+00:00",
                event_type=MCSEventType.BOT_MESSAGE,
                summary="Bot: The form has been auto-populated from your recent chat history.",
            ),
        ]
    )

    items = build_conversation_flow_items(timeline)

    assert len(items) == 3
    assert items[0]["kind"] == "message"
    assert items[0]["role"] == "user"
    assert items[0]["text"] == '"My VPN is not working, create ticket"'

    assert items[1]["kind"] == "event"
    assert items[1]["event_type"] == MCSEventType.STEP_TRIGGERED.value
    assert items[1]["title"] == "Action Started"

    assert items[2]["kind"] == "message"
    assert items[2]["role"] == "bot"
    assert items[2]["text"] == "The form has been auto-populated from your recent chat history."


def test_build_conversation_flow_items_marks_errors():
    timeline = MCSConversationTimeline(
        events=[
            MCSTimelineEvent(
                timestamp="2026-03-10T16:11:58+00:00",
                event_type=MCSEventType.ERROR,
                summary="Connector timeout",
            )
        ]
    )

    items = build_conversation_flow_items(timeline)

    assert len(items) == 1
    assert items[0]["kind"] == "event"
    assert items[0]["tone"] == "error"
    assert items[0]["title"] == "Error"


def test_build_conversation_visual_summary_contains_kpis_and_mix():
    timeline = MCSConversationTimeline(
        events=[
            MCSTimelineEvent(
                timestamp="2026-03-10T16:11:55+00:00",
                event_type=MCSEventType.USER_MESSAGE,
                summary='User: "Need VPN help"',
            ),
            MCSTimelineEvent(
                timestamp="2026-03-10T16:11:56+00:00",
                event_type=MCSEventType.KNOWLEDGE_SEARCH,
                summary="UniversalSearchToolTraceData",
                search_query="vpn issue",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-10T16:11:58+00:00",
                event_type=MCSEventType.BOT_MESSAGE,
                summary="Bot: I can create a ticket.",
            ),
        ]
    )

    summary = build_conversation_visual_summary(timeline)

    assert len(summary["kpis"]) == 4
    assert len(summary["event_mix"]) == 4
    assert len(summary["latency_bands"]) == 4
    assert len(summary["highlights"]) == 3

    labels = {item["label"] for item in summary["event_mix"]}
    assert labels == {"Messages", "Steps", "Search", "Errors"}


def test_render_topic_graph_escapes_labels_and_uses_safe_node_ids():
    profile = MCSBotProfile(
        topic_connections=[
            MCSTopicConnection(
                source_schema="s1",
                source_display='[CA] Ask "HR"',
                target_schema="t1",
                target_display="Employee/Benefits (EU)\\V2",
            )
        ]
    )

    graph = render_topic_graph(profile)

    assert "graph TD" in graph
    assert 'N1["[CA] Ask \\"HR\\""]' in graph
    assert 'N2["Employee/Benefits (EU)\\\\V2"]' in graph
    assert "N1 --> N2" in graph
