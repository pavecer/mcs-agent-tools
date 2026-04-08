"""Tests for transcript conversation flow rendering helpers."""

from __future__ import annotations

from mcs_models import (
    MCSBotProfile,
    MCSConversationTimeline,
    MCSEventType,
    MCSExecutionPhase,
    MCSGptInfo,
    MCSKnowledgeSearchTrace,
    MCSTimelineEvent,
    MCSTopicConnection,
)
from mcs_renderer import build_conversation_deep_dive_cards
from mcs_renderer import build_conversation_flow_items
from mcs_renderer import build_conversation_visual_summary
from mcs_renderer import render_gantt_chart
from mcs_renderer import render_latency_bottlenecks
from mcs_renderer import render_message_chat_timeline
from mcs_renderer import render_mermaid_sequence
from mcs_renderer import render_turn_journey_analysis
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
    assert items[0]["lane"] == "user"

    assert items[1]["kind"] == "event"
    assert items[1]["event_type"] == MCSEventType.STEP_TRIGGERED.value
    assert items[1]["title"] == "Action Started"
    assert items[1]["lane"] == "bot"

    assert items[2]["kind"] == "message"
    assert items[2]["role"] == "bot"
    assert items[2]["text"] == "The form has been auto-populated from your recent chat history."
    assert items[2]["lane"] == "bot"


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
    assert items[0]["lane"] == "error"


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
    assert "classDef default fill:#ffffff,stroke:#8bb8ff,stroke-width:1.6px,color:#102548;" in graph
    assert 'N1("[CA] Ask \\"HR\\"")' in graph
    assert 'N2("Employee/Benefits (EU)\\\\V2")' in graph
    assert "N1 --> N2" in graph


def test_render_gantt_chart_produces_stable_svg_not_mermaid_gantt():
    """Timeline must render as pure SVG (ppsvg fence), never as a Mermaid gantt block."""
    timeline = MCSConversationTimeline(
        phases=[
            MCSExecutionPhase(label="UniversalSearchTool", duration_ms=800),
            MCSExecutionPhase(label="CreateTicket", phase_type="DynamicPlan", duration_ms=1200),
        ]
    )

    chart = render_gantt_chart(timeline)

    # Must use ppsvg fence, not mermaid
    assert "```ppsvg" in chart
    assert "```mermaid" not in chart
    assert "gantt" not in chart
    # Must be valid SVG
    assert "<svg " in chart
    assert "</svg>" in chart
    # Labels must appear (HTML-escaped is fine too)
    assert "UniversalSearchTool" in chart
    assert "CreateTicket" in chart
    # Duration annotations must appear
    assert "800ms" in chart
    assert "1200ms" in chart


def test_render_message_chat_timeline_produces_svg_not_sequence_diagram():
    """Chat timeline must use ppsvg SVG, never a Mermaid sequenceDiagram."""
    timeline = MCSConversationTimeline(
        events=[
            MCSTimelineEvent(
                timestamp="2026-03-11T12:13:08+00:00",
                event_type=MCSEventType.USER_MESSAGE,
                summary='User: How can I reset my password?',
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:13:10+00:00",
                event_type=MCSEventType.BOT_MESSAGE,
                summary="Bot: Please visit the self-service portal.",
            ),
        ]
    )

    output = render_message_chat_timeline(timeline)

    assert "```ppsvg" in output
    assert "<svg " in output
    assert "</svg>" in output
    assert "```mermaid" not in output
    assert "sequenceDiagram" not in output
    # Turn latency table must still be present
    assert "Turn Latency" in output
    assert "| Turn |" in output


def test_render_mermaid_sequence_produces_svg_event_log():
    """Full event flow must render as ppsvg event log, Mermaid-free."""
    timeline = MCSConversationTimeline(
        events=[
            MCSTimelineEvent(
                timestamp="2026-03-11T12:13:08+00:00",
                event_type=MCSEventType.USER_MESSAGE,
                summary="User: Create a support ticket",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:13:09+00:00",
                event_type=MCSEventType.STEP_TRIGGERED,
                summary="Step start: CreateTicketTopic",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:13:10+00:00",
                event_type=MCSEventType.ERROR,
                summary="Connector timeout",
            ),
        ]
    )

    output = render_mermaid_sequence(timeline)

    assert "```ppsvg" in output
    assert "<svg " in output
    assert "</svg>" in output
    assert "```mermaid" not in output
    assert "sequenceDiagram" not in output
    # All event summaries should appear
    assert "Create a support ticket" in output
    assert "Connector timeout" in output


def test_render_turn_journey_analysis_surfaces_fallback_boosting_and_query_changes():
    timeline = MCSConversationTimeline(
        events=[
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:00+00:00",
                event_type=MCSEventType.USER_MESSAGE,
                summary='User: "Need MyImpact guidance"',
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:01+00:00",
                event_type=MCSEventType.STEP_TRIGGERED,
                topic_name="Conversational boosting",
                summary="Step start: Search (Topic)",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:02+00:00",
                event_type=MCSEventType.KNOWLEDGE_SEARCH,
                search_query="myimpact goals",
                details={"result_count": "0"},
                summary="Knowledge search: myimpact goals",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:03+00:00",
                event_type=MCSEventType.KNOWLEDGE_SEARCH,
                search_query="myimpact development objective",
                details={"result_count": "2"},
                summary="Knowledge search: myimpact development objective",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:04+00:00",
                event_type=MCSEventType.STEP_TRIGGERED,
                topic_name="Fallback",
                summary="Step start: Fallback (Topic)",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:09+00:00",
                event_type=MCSEventType.BOT_MESSAGE,
                summary="Bot: I could not find a precise answer.",
            ),
        ]
    )

    output = render_turn_journey_analysis(timeline)

    assert "Turn-by-Turn Search & Routing Journey" in output
    assert "Fallback triggered" in output
    assert "Generative boosting invoked" in output
    assert "Query reformulated" in output
    assert "myimpact goals" in output
    assert "myimpact development objective" in output


def test_build_conversation_deep_dive_cards_surfaces_trace_details_and_instruction_overlap():
    profile = MCSBotProfile(
        gpt_info=MCSGptInfo(
            instructions=(
                "Use MyImpact SharePoint guidance, North Star alignment, values, and SMART goals when grounding answers."
            )
        )
    )
    timeline = MCSConversationTimeline(
        events=[
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:00+00:00",
                event_type=MCSEventType.USER_MESSAGE,
                summary='User: "Help me draft goals"',
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:01+00:00",
                event_type=MCSEventType.STEP_TRIGGERED,
                topic_name="Conversational boosting",
                summary="Step start: Search (Topic)",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:02+00:00",
                event_type=MCSEventType.KNOWLEDGE_SEARCH,
                search_query="draft 2026 goals",
                summary="Knowledge search: draft 2026 goals",
                search_trace=MCSKnowledgeSearchTrace(
                    endpoints=["https://contoso.sharepoint.com/sites/MyImpact"],
                    rewritten_question="Help me identify my priorities and draft 2026 MyImpact goals.",
                    rewritten_keywords="priorities 2026 MyImpact goals",
                    hypothetical_snippet="Draft SMART goals aligned to the North Star and values.",
                    completion_state="AnswerNotFoundInSearchResults",
                    result_count=3,
                    verified_result_count=1,
                    top_results=["Goal-Setting-2026-.aspx [SharepointSiteSearch]"],
                    verified_top_results=["Goal-Setting-2026-.aspx [SharepointSiteSearch]"],
                    rewrite_model_name="gpt-41-2025-04-14",
                    rewrite_prompt_tokens=1052,
                    rewrite_completion_tokens=164,
                    summary_preview="Ask the user for role and priorities.",
                ),
                details={"result_count": "3"},
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:00:06+00:00",
                event_type=MCSEventType.BOT_MESSAGE,
                summary="Bot: Tell me more about your role.",
            ),
        ]
    )

    cards = build_conversation_deep_dive_cards(profile, timeline)

    assert len(cards) == 1
    assert cards[0]["searches"][0]["rewrite_model"] == "gpt-41-2025-04-14"
    assert cards[0]["searches"][0]["instruction_overlap_label"] in {"Strong", "Partial"}
    assert cards[0]["searches"][0]["signal_label"] == "Answer not found in verified search results"


def test_render_latency_bottlenecks_marks_slow_turn_contributors():
    timeline = MCSConversationTimeline(
        events=[
            MCSTimelineEvent(
                timestamp="2026-03-11T12:10:00+00:00",
                event_type=MCSEventType.USER_MESSAGE,
                summary='User: "Find policy"',
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:10:01+00:00",
                event_type=MCSEventType.STEP_TRIGGERED,
                topic_name="Search",
                summary="Step start: Search (Topic)",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:10:02+00:00",
                event_type=MCSEventType.KNOWLEDGE_SEARCH,
                search_query="policy",
                details={"result_count": "0"},
                summary="Knowledge search: policy",
            ),
            MCSTimelineEvent(
                timestamp="2026-03-11T12:10:09+00:00",
                event_type=MCSEventType.BOT_MESSAGE,
                summary="Bot: I need more details.",
            ),
        ]
    )

    output = render_latency_bottlenecks(timeline)

    assert "Latency Bottlenecks" in output
    assert "slow turn" in output.lower()
    assert "No usable KB results" in output
