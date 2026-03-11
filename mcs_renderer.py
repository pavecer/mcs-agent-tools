"""MCS Agent Analyser — render Markdown + Mermaid reports.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

from datetime import datetime

from mcs_credits import MCSCreditEstimate
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
        "| Field | Value |",
        "| --- | --- |",
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
        "| Setting | Value |",
        "| --- | --- |",
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
            "```",
            gpt.instructions.strip() if gpt.instructions else "(none)",
            "```",
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
        lines.append(f"| {i} | {c.display_name or '—'} | `{c.schema_name or '—'}` | {c.kind} | {c.state} | {trigger} |")
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
            lines.append("    E-->>C: DynamicPlan received")

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
        lines.append(f"| {lbl} | {phase.phase_type} | {phase.duration_ms or '—'} | {phase.state} |")
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


def _ms_between_iso(start: str | None, end: str | None) -> float:
    """Best-effort milliseconds between two ISO timestamps."""
    if not start or not end:
        return 0.0
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (e - s).total_seconds() * 1000
    except Exception:
        return 0.0


def _pair_message_turns(timeline: MCSConversationTimeline) -> list[dict]:
    """Pair user messages with the next bot message to form chat turns."""
    turns: list[dict] = []
    pending_user: dict | None = None

    for ev in timeline.events:
        if ev.event_type == MCSEventType.USER_MESSAGE:
            pending_user = {
                "user_ts": ev.timestamp,
                "user_msg": (ev.summary or "").replace("User: ", "", 1),
            }
            continue

        if ev.event_type == MCSEventType.BOT_MESSAGE and pending_user is not None:
            latency_ms = _ms_between_iso(pending_user.get("user_ts"), ev.timestamp)
            turns.append(
                {
                    "user_ts": pending_user.get("user_ts") or "",
                    "user_msg": pending_user.get("user_msg") or "",
                    "bot_ts": ev.timestamp or "",
                    "bot_msg": (ev.summary or "").replace("Bot: ", "", 1),
                    "latency_ms": latency_ms,
                }
            )
            pending_user = None

    return turns


def render_conversation_overview(timeline: MCSConversationTimeline) -> str:
    """Render KPI summary for transcript diagnostics."""
    user_msgs = sum(1 for e in timeline.events if e.event_type == MCSEventType.USER_MESSAGE)
    bot_msgs = sum(1 for e in timeline.events if e.event_type == MCSEventType.BOT_MESSAGE)
    steps_triggered = sum(1 for e in timeline.events if e.event_type == MCSEventType.STEP_TRIGGERED)
    steps_finished = sum(1 for e in timeline.events if e.event_type == MCSEventType.STEP_FINISHED)
    searches = sum(1 for e in timeline.events if e.event_type == MCSEventType.KNOWLEDGE_SEARCH)
    errors = sum(1 for e in timeline.events if e.event_type == MCSEventType.ERROR)
    turns = _pair_message_turns(timeline)
    avg_latency = (sum(t["latency_ms"] for t in turns) / len(turns)) if turns else 0.0
    p95_latency = 0.0
    if turns:
        sorted_lat = sorted(t["latency_ms"] for t in turns)
        idx = int(max(0, min(len(sorted_lat) - 1, round(0.95 * (len(sorted_lat) - 1)))))
        p95_latency = sorted_lat[idx]

    lines: list[str] = [
        "## Conversation Overview",
        "",
        "| KPI | Value |",
        "| --- | ---: |",
        f"| Total activities | {timeline.total_activities} |",
        f"| Message events | {timeline.message_count} |",
        f"| Event telemetry | {timeline.event_count} |",
        f"| Trace telemetry | {timeline.trace_count} |",
        f"| Typing indicators | {timeline.typing_count} |",
        f"| User messages | {user_msgs} |",
        f"| Bot messages | {bot_msgs} |",
        f"| Steps triggered | {steps_triggered} |",
        f"| Steps finished | {steps_finished} |",
        f"| UniversalSearch calls | {searches} |",
        f"| Error events | {errors} |",
        f"| Total elapsed | {timeline.total_elapsed_ms:.0f} ms |",
        f"| Avg turn latency | {avg_latency:.0f} ms |",
        f"| P95 turn latency | {p95_latency:.0f} ms |",
        "",
    ]
    return "\n".join(lines)


def render_message_chat_timeline(timeline: MCSConversationTimeline) -> str:
    """Render a message-only sequence and turn latency table."""
    turns = _pair_message_turns(timeline)
    if not turns:
        return ""

    lines: list[str] = [
        "## Message Chat Timeline",
        "",
        "```mermaid",
        "sequenceDiagram",
        "    autonumber",
        "    participant U as User",
        "    participant C as Copilot",
        "",
    ]
    for turn in turns[:80]:
        umsg = turn["user_msg"].replace('"', "'")[:90]
        bmsg = turn["bot_msg"].replace('"', "'")[:90]
        uts = (turn["user_ts"] or "")[-14:-6] if turn["user_ts"] else ""
        bts = (turn["bot_ts"] or "")[-14:-6] if turn["bot_ts"] else ""
        lines.append(f'    U->>C: [{uts}] {umsg}')
        lines.append(f'    C-->>U: [{bts}] {bmsg}')

    lines += [
        "```",
        "",
        "### Turn Latency",
        "",
        "| Turn | User Message | Bot Response | Latency (ms) |",
        "| ---: | --- | --- | ---: |",
    ]
    for i, turn in enumerate(turns, 1):
        umsg = turn["user_msg"][:80].replace("|", "\\|")
        bmsg = turn["bot_msg"][:80].replace("|", "\\|")
        lines.append(f"| {i} | {umsg} | {bmsg} | {turn['latency_ms']:.0f} |")
    lines.append("")
    return "\n".join(lines)


def render_tool_diagnostics(timeline: MCSConversationTimeline) -> str:
    """Render execution and tool diagnostics for troubleshooting."""
    step_started = [e for e in timeline.events if e.event_type == MCSEventType.STEP_TRIGGERED]
    step_finished = [e for e in timeline.events if e.event_type == MCSEventType.STEP_FINISHED]
    step_by_id: dict[str, dict] = {}
    for e in step_started:
        if e.step_id:
            step_by_id[e.step_id] = {"topic": e.topic_name or "—", "start": e.timestamp, "state": "started"}
    for e in step_finished:
        if e.step_id:
            rec = step_by_id.setdefault(e.step_id, {"topic": e.topic_name or "—", "start": None})
            rec["end"] = e.timestamp
            rec["state"] = e.state or "unknown"
            rec["error"] = e.error or ""

    lines: list[str] = [
        "## Tool & Step Diagnostics",
        "",
        "| Step ID | Topic | Start | End | State | Error |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    if step_by_id:
        for sid, row in list(step_by_id.items())[:200]:
            topic = str(row.get("topic", "—")).replace("|", "\\|")
            start = row.get("start") or "—"
            end = row.get("end") or "—"
            state = row.get("state") or "—"
            err = str(row.get("error", "")).replace("|", "\\|")[:120] or "—"
            lines.append(f"| `{sid[:12]}…` | {topic} | {start} | {end} | {state} | {err} |")
    else:
        lines.append("| — | — | — | — | — | — |")

    lines += ["", "### Universal Search Diagnostics", "", "| Timestamp | Query | Sources | Results |", "| --- | --- | --- | ---: |"]
    search_events = [e for e in timeline.events if e.event_type == MCSEventType.KNOWLEDGE_SEARCH]
    if search_events:
        for e in search_events[:200]:
            query = (e.search_query or "").replace("|", "\\|")[:140] or "—"
            sources = (e.details.get("sources", "none") if e.details else "none").replace("|", "\\|")
            results = e.details.get("result_count", "0") if e.details else "0"
            lines.append(f"| {e.timestamp or '—'} | {query} | {sources} | {results} |")
    else:
        lines.append("| — | — | — | 0 |")

    lines.append("")
    return "\n".join(lines)


def render_conversation_findings(timeline: MCSConversationTimeline) -> str:
    """Highlight potential issues and bottlenecks in the conversation flow."""
    turns = _pair_message_turns(timeline)
    long_turns = [t for t in turns if t["latency_ms"] >= 8000]
    incomplete_steps = [e for e in timeline.events if e.event_type == MCSEventType.STEP_TRIGGERED and e.step_id]
    finished_ids = {e.step_id for e in timeline.events if e.event_type == MCSEventType.STEP_FINISHED and e.step_id}
    orphaned = [e for e in incomplete_steps if e.step_id not in finished_ids]
    searches = [e for e in timeline.events if e.event_type == MCSEventType.KNOWLEDGE_SEARCH]
    search_without_query = [e for e in searches if not e.search_query]

    lines: list[str] = [
        "## Findings",
        "",
        f"- Long user-to-bot turns (>= 8000 ms): **{len(long_turns)}**",
        f"- Step triggers without matching finish event: **{len(orphaned)}**",
        f"- Universal Search calls without extracted query payload: **{len(search_without_query)}**",
        f"- Total explicit errors in telemetry: **{len(timeline.errors)}**",
        "",
    ]
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
            render_conversation_overview(timeline),
            render_message_chat_timeline(timeline),
            render_tool_diagnostics(timeline),
            render_conversation_findings(timeline),
            render_mermaid_sequence(timeline),
            render_gantt_chart(timeline),
            render_phase_breakdown(timeline),
            render_event_log(timeline),
            render_errors(timeline),
        ]

    return "\n".join(sections)


def render_report_sections(profile: MCSBotProfile, timeline: MCSConversationTimeline) -> dict[str, str]:
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
            render_conversation_overview(timeline),
            render_message_chat_timeline(timeline),
            render_tool_diagnostics(timeline),
            render_conversation_findings(timeline),
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
            rest = graph_md[fence_start + len("```mermaid") :]
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
            render_conversation_overview(timeline),
            render_message_chat_timeline(timeline),
            render_tool_diagnostics(timeline),
            render_conversation_findings(timeline),
            render_mermaid_sequence(timeline),
            render_gantt_chart(timeline),
            render_phase_breakdown(timeline),
            render_event_log(timeline),
            render_errors(timeline),
        ]

    return "\n".join(sections)


def render_credit_estimate(title: str, estimate: MCSCreditEstimate) -> str:
    """Render credit estimation breakdown as Markdown."""
    lines: list[str] = [
        f"## {title}",
        "",
        "| Meter | Observed count | Rate | Estimated credits |",
        "| --- | ---: | ---: | ---: |",
        f"| Classic answer | {estimate.classic_answers} | 1 | {estimate.classic_credits} |",
        f"| Generative answer | {estimate.generative_answers} | 2 | {estimate.generative_credits} |",
        f"| Agent action | {estimate.agent_actions} | 5 | {estimate.agent_action_credits} |",
        f"| Tenant graph grounding (messages) | {estimate.tenant_graph_grounding_messages} | 10 | {estimate.tenant_graph_credits} |",
        f"| Agent flow actions | {estimate.agent_flow_actions} | 13 / 100 | {estimate.agent_flow_credits} |",
        f"| Text/gen AI tools (premium) responses | {estimate.premium_tool_responses} | 100 / 10 | {estimate.premium_tool_credits} |",
        "",
        f"**Total predicted Copilot Credits:** {estimate.total_credits}",
        "",
        "### Assumptions",
        "",
    ]
    lines.extend(f"- {item}" for item in estimate.assumptions)
    lines.append("")
    return "\n".join(lines)
