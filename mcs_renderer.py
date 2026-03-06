"""MCS Agent Analyser — render Markdown + Mermaid reports.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

from mcs_models import MCSBotProfile, MCSConversationTimeline, MCSEventType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IDLE_THRESHOLD_MS = 5_000  # ms silence before marking a gap

ACTOR_NAMES = {
    "bot": "Copilot",
    "user": "User",
}

_SYSTEM_TRIGGERS = {
    "StartConversation",
    "WelcomeMessage",
    "OnConversationStart",
}

_GANTT_COLORS = {
    "DynamicPlan": "crit",
    "Search": "active",
    "System": "done",
    "User": "",  # grey default
    "Bot": "",
    "Redirect": "active",
}


# ---------------------------------------------------------------------------
# Individual section renderers
# ---------------------------------------------------------------------------


def render_bot_profile(profile: MCSBotProfile) -> str:
    lines: list[str] = [
        "## Bot Profile",
        "",
        f"| Field | Value |",
        f"| --- | --- |",
        f"| **Name** | {profile.display_name or '—'} |",
        f"| **Schema Name** | `{profile.schema_name or '—'}` |",
        f"| **Bot ID** | {profile.bot_id or '—'} |",
        f"| **Recognizer** | {profile.recognizer_kind or '—'} |",
        f"| **Orchestrator** | {profile.is_orchestrator} |",
        "",
    ]
    return "\n".join(lines)


def render_bot_metadata(profile: MCSBotProfile) -> str:
    ai = profile.ai_settings
    lines: list[str] = [
        "## AI Settings",
        "",
        f"| Setting | Value |",
        f"| --- | --- |",
        f"| **Use Model Knowledge** | {ai.use_model_knowledge} |",
        f"| **File Analysis** | {ai.file_analysis} |",
        f"| **Semantic Search** | {ai.semantic_search} |",
        f"| **Content Moderation** | {ai.content_moderation} |",
        f"| **Opt-in Latest Models** | {ai.opt_in_latest_models} |",
        "",
    ]
    if profile.gpt_info:
        gpt = profile.gpt_info
        lines += [
            f"### GPT Instructions ({gpt.display_name})",
            "",
            f"```",
            gpt.instructions.strip() if gpt.instructions else "(none)",
            f"```",
            "",
        ]
    return "\n".join(lines)


def render_components(profile: MCSBotProfile) -> str:
    if not profile.components:
        return ""
    lines: list[str] = [
        "## Topics & Components",
        "",
        "| # | Display Name | Schema Name | Kind | State | Trigger Kind |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, c in enumerate(profile.components, 1):
        trigger = c.trigger_kind or "—"
        lines.append(
            f"| {i} | {c.display_name or '—'} | `{c.schema_name or '—'}` "
            f"| {c.kind} | {c.state} | {trigger} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_topic_graph(profile: MCSBotProfile) -> str:
    if not profile.topic_connections:
        return ""
    lines: list[str] = [
        "## Topic Redirect Graph",
        "",
        "```mermaid",
        "graph TD",
    ]

    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()

    def node_id(name: str) -> str:
        return name.replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")

    for conn in profile.topic_connections:
        src = conn.source_display or conn.source_schema or "Unknown"
        dst = conn.target_display or conn.target_schema or "Unknown"
        edge = (src, dst)
        if edge in seen_edges:
            continue
        seen_edges.add(edge)

        sid = node_id(src)
        did = node_id(dst)
        if sid not in seen_nodes:
            seen_nodes.add(sid)
            lines.append(f'    {sid}["{src}"]')
        if did not in seen_nodes:
            seen_nodes.add(did)
            lines.append(f'    {did}["{dst}"]')
        lines.append(f"    {sid} --> {did}")

    lines += ["```", ""]
    return "\n".join(lines)


def render_mermaid_sequence(timeline: MCSConversationTimeline) -> str:
    lines: list[str] = [
        "## Conversation Sequence Diagram",
        "",
        "```mermaid",
        "sequenceDiagram",
        "    autonumber",
        "    participant U as User",
        "    participant C as Copilot",
        "    participant E as Engine",
        "",
    ]

    for event in timeline.events:
        ev_type = event.event_type
        label = (event.summary or "")[:80].replace('"', "'")

        if ev_type == MCSEventType.USER_MESSAGE:
            lines.append(f'    U->>C: "{label}"')

        elif ev_type == MCSEventType.BOT_MESSAGE:
            lines.append(f'    C-->>U: "{label}"')

        elif ev_type == MCSEventType.DIALOG_TRACING:
            lines.append(f"    Note over C,E: Topic → {label}")

        elif ev_type == MCSEventType.DIALOG_REDIRECT:
            lines.append(f"    C->>C: Redirect → {label}")

        elif ev_type == MCSEventType.PLAN_RECEIVED:
            lines.append(f"    E-->>C: DynamicPlan received")

        elif ev_type == MCSEventType.STEP_TRIGGERED:
            lines.append(f'    C->>E: Step "{label}"')

        elif ev_type == MCSEventType.STEP_FINISHED:
            lines.append(f'    E-->>C: Done "{label}"')

        elif ev_type == MCSEventType.KNOWLEDGE_SEARCH:
            lines.append(f'    C->>E: Search "{label}"')

        elif ev_type == MCSEventType.VARIABLE_ASSIGNMENT:
            lines.append(f"    Note over C: {label}")

        elif ev_type == MCSEventType.ERROR:
            lines.append(f"    Note over C,E: ERROR — {label}")

    lines += ["```", ""]
    return "\n".join(lines)


def render_gantt_chart(timeline: MCSConversationTimeline) -> str:
    if not timeline.phases:
        return ""

    lines: list[str] = [
        "## Execution Gantt Chart",
        "",
        "```mermaid",
        "gantt",
        "    title Conversation Execution Timeline",
        "    dateFormat  x",
        "    axisFormat  %H:%M:%S",
        "",
    ]

    for phase in timeline.phases:
        section_name = (phase.label or phase.phase_type or "Phase").replace(":", " ")
        lines.append(f"    section {section_name}")
        color_keyword = _GANTT_COLORS.get(phase.phase_type, "")
        duration = max(int(phase.duration_ms) if phase.duration_ms else 100, 50)
        color_part = f"{color_keyword}, " if color_keyword else ""
        lines.append(f"    {section_name} :{color_part}0, {duration}ms")

    lines += ["```", ""]
    return "\n".join(lines)


def render_phase_breakdown(timeline: MCSConversationTimeline) -> str:
    if not timeline.phases:
        return ""
    lines: list[str] = [
        "## Phase Breakdown",
        "",
        "| Phase | Type | Duration (ms) | State |",
        "| --- | --- | --- | --- |",
    ]
    for phase in timeline.phases:
        lbl = phase.label or phase.phase_type or "—"
        lines.append(
            f"| {lbl} | {phase.phase_type} "
            f"| {phase.duration_ms or '—'} | {phase.state} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_event_log(timeline: MCSConversationTimeline) -> str:
    if not timeline.events:
        return ""
    lines: list[str] = [
        "## Event Log",
        "",
        "| # | Timestamp | Type | Label |",
        "| --- | --- | --- | --- |",
    ]
    for i, event in enumerate(timeline.events, 1):
        ts = event.timestamp or "—"
        ev_type = event.event_type or "—"
        lbl = (event.summary or "—")[:120].replace("|", "\\|")
        lines.append(f"| {i} | {ts} | `{ev_type}` | {lbl} |")
    lines.append("")
    return "\n".join(lines)


def render_errors(timeline: MCSConversationTimeline) -> str:
    error_events = [e for e in timeline.events if e.event_type == MCSEventType.ERROR]
    if not error_events:
        return ""
    lines: list[str] = [
        "## Errors",
        "",
        "> The following errors were detected during the session.",
        "",
    ]
    for ev in error_events:
        lbl = ev.error or ev.summary or "Unknown error"
        ts = ev.timestamp or ""
        ts_str = f" _(at {ts})_" if ts else ""
        lines.append(f"- **{lbl}**{ts_str}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level render functions
# ---------------------------------------------------------------------------


def render_report(profile: MCSBotProfile, timeline: MCSConversationTimeline) -> str:
    """Render a full Markdown + Mermaid report for a bot snapshot + dialog."""
    bot_name = profile.display_name or "Unknown Bot"
    title = f"# {bot_name} — Agent Analysis Report"

    sections = [
        title,
        "",
        render_bot_profile(profile),
        render_bot_metadata(profile),
        render_components(profile),
        render_topic_graph(profile),
    ]

    if timeline.events:
        sections += [
            render_mermaid_sequence(timeline),
            render_gantt_chart(timeline),
            render_phase_breakdown(timeline),
            render_event_log(timeline),
            render_errors(timeline),
        ]

    return "\n".join(sections)


def render_report_sections(
    profile: MCSBotProfile, timeline: MCSConversationTimeline
) -> dict[str, str]:
    """Return the report split into named sections for tabbed display.

    Keys: ``"profile"``, ``"topics"``, ``"graph"``, ``"conversation"``.
    """
    bot_name = profile.display_name or "Unknown Bot"

    profile_md = "\n\n".join(
        p
        for p in [
            f"# {bot_name} — Agent Analysis",
            "",
            render_bot_profile(profile),
            render_bot_metadata(profile),
        ]
        if p
    )

    topics_md = (
        render_components(profile)
        if profile.components
        else "## Topics & Components\n\n_No topics found in this snapshot._\n"
    )

    graph_md = (
        render_topic_graph(profile)
        if profile.topic_connections
        else "## Topic Redirect Graph\n\n_No topic connections found in this snapshot._\n"
    )

    if timeline.events:
        conv_parts = [
            render_mermaid_sequence(timeline),
            render_gantt_chart(timeline),
            render_phase_breakdown(timeline),
            render_event_log(timeline),
            render_errors(timeline),
        ]
        conversation_md = "\n\n".join(p for p in conv_parts if p.strip())
    else:
        conversation_md = (
            "## Conversation\n\n"
            "_No conversation events in this snapshot. "
            "Drop a transcript JSON in the Conversation tab for dialogue analysis._\n"
        )

    return {
        "profile": profile_md,
        "topics": topics_md,
        "graph": graph_md,
        "conversation": conversation_md,
    }


def to_viz_segments(profile: MCSBotProfile) -> list[dict]:
    """Convert a snapshot bot profile into viz_segments (same format as visualize_zip_bytes).

    Used to populate the Visualize tab for Copilot Studio snapshot ZIPs.
    """
    segments: list[dict] = []

    # ── Overview + AI settings table ─────────────────────────────────────────
    ai = profile.ai_settings
    overview_md = "\n".join(
        [
            "## Bot Overview",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| **Name** | {profile.display_name or '—'} |",
            f"| **Schema** | `{profile.schema_name or '—'}` |",
            f"| **Bot ID** | {profile.bot_id or '—'} |",
            f"| **Recognizer** | {profile.recognizer_kind or '—'} |",
            f"| **Orchestrator** | {profile.is_orchestrator} |",
            f"| **Topics** | {len(profile.components)} |",
            "",
            "## AI Settings",
            "",
            "| Setting | Value |",
            "| --- | --- |",
            f"| Use Model Knowledge | {ai.use_model_knowledge} |",
            f"| File Analysis | {ai.file_analysis} |",
            f"| Semantic Search | {ai.semantic_search} |",
            f"| Content Moderation | {ai.content_moderation} |",
            "",
        ]
    )
    segments.append({"type": "text", "content": overview_md})

    # ── Components table ──────────────────────────────────────────────────────
    components_md = render_components(profile)
    if components_md.strip():
        segments.append({"type": "text", "content": components_md})

    # ── Topic redirect graph (Mermaid) ────────────────────────────────────────
    if profile.topic_connections:
        graph_md = render_topic_graph(profile)
        fence_start = graph_md.find("```mermaid")
        if fence_start != -1:
            heading = graph_md[:fence_start].strip()
            rest = graph_md[fence_start + len("```mermaid"):]
            fence_end = rest.rfind("```")
            if fence_end != -1:
                mermaid_code = rest[:fence_end].strip()
                if heading:
                    segments.append({"type": "text", "content": heading})
                segments.append({"type": "mermaid", "content": mermaid_code})

    return segments


def render_transcript_report(
    title: str,
    timeline: MCSConversationTimeline,
    metadata: dict,
) -> str:
    """Render a report from transcript-only analysis (no bot profile)."""
    sections: list[str] = [f"# {title}", ""]

    # Session metadata table
    session_info = metadata.get("session_info", {})
    conv_info = metadata.get("conversation_info", {})
    if session_info or conv_info:
        sections += [
            "## Session Metadata",
            "",
            "| Key | Value |",
            "| --- | --- |",
        ]
        for k, v in session_info.items():
            sections.append(f"| {k} | {v} |")
        for k, v in conv_info.items():
            sections.append(f"| {k} | {v} |")
        sections.append("")

    if timeline.events:
        sections += [
            render_mermaid_sequence(timeline),
            render_gantt_chart(timeline),
            render_phase_breakdown(timeline),
            render_event_log(timeline),
            render_errors(timeline),
        ]

    return "\n".join(sections)
