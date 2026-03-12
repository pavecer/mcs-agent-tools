"""Tests for the Topic & Trigger Audit report section."""

from __future__ import annotations

from mcs_models import MCSBotProfile, MCSComponentSummary, MCSGptInfo, MCSTopicConnection
from mcs_renderer import render_topic_trigger_audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dialog(
    display_name: str,
    schema_name: str,
    trigger_kind: str | None = "OnRecognizedIntent",
    trigger_queries: list[str] | None = None,
    state: str = "Active",
) -> MCSComponentSummary:
    return MCSComponentSummary(
        kind="DialogComponent",
        display_name=display_name,
        schema_name=schema_name,
        trigger_kind=trigger_kind,
        trigger_queries=trigger_queries or [],
        state=state,
    )


def _make_system(trigger_kind: str, display_name: str = "") -> MCSComponentSummary:
    return MCSComponentSummary(
        kind="DialogComponent",
        display_name=display_name or trigger_kind,
        schema_name=trigger_kind,
        trigger_kind=trigger_kind,
        state="Active",
    )


# ---------------------------------------------------------------------------
# Orchestration Mode
# ---------------------------------------------------------------------------


def test_audit_shows_generative_mode_when_gpt_info_present():
    profile = MCSBotProfile(
        gpt_info=MCSGptInfo(display_name="My Bot", model_hint="GPT-4o"),
        components=[
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ],
    )
    result = render_topic_trigger_audit(profile)
    assert "Generative AI" in result
    assert "GPT-4o" in result
    assert "suggestions" in result.lower()


def test_audit_shows_classic_mode_with_recognizer_kind():
    profile = MCSBotProfile(
        recognizer_kind="OrchestratorRecognizer",
        recognizer_id="my-clu-project",
        components=[
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ],
    )
    result = render_topic_trigger_audit(profile)
    assert "Classic" in result
    assert "OrchestratorRecognizer" in result
    assert "my-clu-project" in result


def test_audit_shows_unknown_orchestration_when_no_clues():
    profile = MCSBotProfile(
        recognizer_kind="Unknown",
        components=[
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ],
    )
    result = render_topic_trigger_audit(profile)
    assert "could not be determined" in result


# ---------------------------------------------------------------------------
# Conflicting Triggers
# ---------------------------------------------------------------------------


def test_audit_detects_exact_trigger_overlap():
    profile = MCSBotProfile(
        components=[
            _make_dialog("Greet", "topic.Greet", trigger_queries=["hello", "hi there"]),
            _make_dialog("Welcome", "topic.Welcome", trigger_queries=["hello", "good morning"]),
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ]
    )
    result = render_topic_trigger_audit(profile)
    assert "hello" in result
    assert "Greet" in result
    assert "Welcome" in result
    assert "⚠️" in result


def test_audit_detects_case_insensitive_overlap():
    profile = MCSBotProfile(
        components=[
            _make_dialog("Alpha", "topic.Alpha", trigger_queries=["Hello World"]),
            _make_dialog("Beta", "topic.Beta", trigger_queries=["hello world"]),
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ]
    )
    result = render_topic_trigger_audit(profile)
    assert "hello world" in result


def test_audit_no_conflicts_when_phrases_are_unique():
    profile = MCSBotProfile(
        components=[
            _make_dialog("Billing", "topic.Billing", trigger_queries=["show my bill"]),
            _make_dialog("Support", "topic.Support", trigger_queries=["I need help"]),
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ]
    )
    result = render_topic_trigger_audit(profile)
    assert "No overlapping trigger phrases" in result


# ---------------------------------------------------------------------------
# Orphan Topics
# ---------------------------------------------------------------------------


def test_audit_identifies_orphan_topic():
    profile = MCSBotProfile(
        components=[
            _make_dialog("Unused Topic", "topic.Unused", trigger_kind="OnRecognizedIntent", trigger_queries=[]),
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ],
        topic_connections=[],
    )
    result = render_topic_trigger_audit(profile)
    assert "Unused Topic" in result
    assert "⚠️" in result


def test_audit_topic_not_orphan_when_called_by_other():
    profile = MCSBotProfile(
        components=[
            _make_dialog("Child Topic", "topic.Child", trigger_kind="OnRecognizedIntent", trigger_queries=[]),
            _make_dialog("Parent Topic", "topic.Parent", trigger_queries=["start parent"]),
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ],
        topic_connections=[
            MCSTopicConnection(
                source_schema="topic.Parent",
                source_display="Parent Topic",
                target_schema="topic.Child",
                target_display="Child Topic",
            )
        ],
    )
    result = render_topic_trigger_audit(profile)
    # Child Topic should NOT appear in orphan list
    assert "No orphaned topics" in result


def test_audit_system_topics_never_flagged_as_orphans():
    profile = MCSBotProfile(
        components=[
            _make_system("OnUnknownIntent", "Fallback"),
            _make_system("OnEscalate", "Escalate"),
            _make_system("OnEndConversation", "End Conv"),
        ],
        topic_connections=[],
    )
    result = render_topic_trigger_audit(profile)
    assert "No orphaned topics" in result


# ---------------------------------------------------------------------------
# Missing Guardrails
# ---------------------------------------------------------------------------


def test_audit_flags_missing_fallback_topic():
    profile = MCSBotProfile(
        components=[
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ]
    )
    result = render_topic_trigger_audit(profile)
    assert "🚨" in result
    assert "Fallback" in result
    assert "OnUnknownIntent" in result


def test_audit_flags_inactive_escalate_topic():
    profile = MCSBotProfile(
        components=[
            _make_system("OnUnknownIntent"),
            MCSComponentSummary(
                kind="DialogComponent",
                display_name="Escalate",
                schema_name="topic.Escalate",
                trigger_kind="OnEscalate",
                state="Inactive",
            ),
            _make_system("OnEndConversation"),
        ]
    )
    result = render_topic_trigger_audit(profile)
    assert "⚠️" in result
    assert "Escalate" in result
    assert "inactive" in result.lower() or "disabled" in result.lower()


def test_audit_all_guardrails_present_shows_ok():
    profile = MCSBotProfile(
        components=[
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ]
    )
    result = render_topic_trigger_audit(profile)
    assert "✅" in result
    assert "essential guardrail topics are present" in result


# ---------------------------------------------------------------------------
# Empty profile
# ---------------------------------------------------------------------------


def test_audit_handles_empty_components():
    profile = MCSBotProfile(components=[])
    result = render_topic_trigger_audit(profile)
    assert "## Topic & Trigger Audit" in result
    assert "No topics found" in result


# ---------------------------------------------------------------------------
# Integration: render_report_sections includes audit key
# ---------------------------------------------------------------------------


def test_render_report_sections_includes_audit_key():
    from mcs_models import MCSConversationTimeline
    from mcs_renderer import render_report_sections

    profile = MCSBotProfile(
        display_name="Test Bot",
        components=[
            _make_system("OnUnknownIntent"),
            _make_system("OnEscalate"),
            _make_system("OnEndConversation"),
        ],
    )
    timeline = MCSConversationTimeline()
    sections = render_report_sections(profile, timeline)
    assert "audit" in sections
    assert "## Topic & Trigger Audit" in sections["audit"]
