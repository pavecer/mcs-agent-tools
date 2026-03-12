"""MCS Agent Analyser — render Markdown + Mermaid reports.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

import socket
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from toolkit.mcs.credits import MCSCreditEstimate
from toolkit.mcs.models import MCSBotProfile, MCSConversationTimeline, MCSEventType

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
    model_hint = profile.gpt_info.model_hint if profile.gpt_info else None
    model_display = model_hint or "—"
    lines: list[str] = [
        "## AI Settings",
        "",
        "| Setting | Value |",
        "| --- | --- |",
        f"| **Foundation Model** | {model_display} |",
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


def _check_public_url(url: str, timeout_s: float = 5.0) -> tuple[bool, str]:
    """Perform a basic HTTP GET check and return (is_accessible, status)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "Not HTTP/HTTPS"

    req = Request(url=url, method="GET", headers={"User-Agent": "pp-agent-toolkit/0.2"})
    try:
        with urlopen(req, timeout=timeout_s) as response:
            code = getattr(response, "status", None) or response.getcode()
            if code == 200:
                return True, "HTTP 200"
            return False, f"HTTP {code}"
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (URLError, TimeoutError, socket.timeout) as exc:
        return False, f"Error: {exc}"
    except Exception as exc:
        return False, f"Error: {exc}"


def _format_auth_mode(auth_mode: str | None) -> str:
    if not auth_mode:
        return "—"
    mode = auth_mode.strip().lower()
    if "user" in mode:
        return "user identity"
    if any(token in mode for token in ("maker", "service", "owner", "application", "app")):
        return "service account (maker auth)"
    return auth_mode


def _friendly_source_type(raw: str | None) -> str:
    value = (raw or "Unknown").strip()
    low = value.lower()
    if "website" in low or "public" in low:
        return "Website"
    if "sharepoint" in low:
        return "SharePoint"
    if "dataverse" in low:
        return "Dataverse"
    if "file" in low:
        return "File"
    if "searchspecificknowledgesources" in low:
        return "Knowledge Search"
    if "knowledgesources" in low:
        return "Knowledge Source"
    return value


def _compact_component_name(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "Unnamed"
    low = raw.lower()
    for marker in (".topic.", ".agent.", ".globalvariablecomponent.", ".gpt.", ".entity.", ".file."):
        idx = low.find(marker)
        if idx >= 0:
            return raw[idx + len(marker) :].strip() or raw
    return raw


def _friendly_location(location: str | None) -> str:
    if not location:
        return "Not provided"
    parsed = urlparse(location)
    if parsed.scheme in {"http", "https"}:
        return location
    return _compact_component_name(location)


def render_knowledge_sources_and_tools(profile: MCSBotProfile) -> str:
    """Render knowledge source inventory and external connector/tool usage."""
    lines: list[str] = ["## Knowledge Sources & External Tools", ""]

    lines += ["### Knowledge Sources", ""]
    if not profile.knowledge_sources:
        lines += ["_No knowledge sources detected in snapshot configuration._", ""]
    else:
        total_sources = len(profile.knowledge_sources)
        website_count = sum(1 for s in profile.knowledge_sources if _friendly_source_type(s.source_type) == "Website")
        lines += [
            f"Detected **{total_sources}** knowledge source(s)"
            + (f" including **{website_count}** website source(s)." if website_count else "."),
            "",
        ]
        url_cache: dict[str, tuple[bool, str]] = {}
        for source in profile.knowledge_sources:
            source_type = _friendly_source_type(source.source_type)
            label = _compact_component_name(source.name or "Unnamed source")
            location = _friendly_location(source.location)

            line = f"- **{label}**  \n  Type: `{source_type}`  \n  Location: {location}"
            if source.site_id:
                line += f"  \n  Site ID: `{source.site_id}`"

            if source_type.lower() == "website" and source.location:
                parsed = urlparse(source.location)
                if parsed.scheme in {"http", "https"}:
                    status = url_cache.get(source.location)
                    if status is None:
                        status = _check_public_url(source.location)
                        url_cache[source.location] = status
                    ok, reason = status
                    if ok:
                        line += "  \n  Status: **Accessible✅**"
                    else:
                        line += f"  \n  Status: **Inaccessible⚠️** ({reason})"
                else:
                    line += "  \n  Status: **Inaccessible⚠️** (invalid URL scheme)"
            elif source_type.lower() == "website" and not source.location:
                line += "  \n  Status: **Missing Resource⚠️** (URL not provided)"
            elif source.location is None:
                line += "  \n  Status: **Missing Resource⚠️** (no URL/path provided)"

            details = []
            for key, value in source.details.items():
                if value:
                    details.append(f"{key}={value}")
            if details:
                line += f"  \n  Details: `{'; '.join(details)}`"

            lines.append(line)
        lines.append("")

    lines += ["### External Tools, Connectors & Flows", ""]
    if not profile.external_tools:
        lines += ["_No external tools/connectors detected in snapshot configuration._", ""]
    else:
        lines += [f"Detected **{len(profile.external_tools)}** external tool(s)/connector(s).", ""]
        for tool in profile.external_tools:
            tool_type = tool.tool_type or "Tool"
            name = _compact_component_name(tool.name or tool.connector_id or "Unnamed tool")
            connector = tool.connector_id or "n/a"
            auth = _format_auth_mode(tool.auth_mode)

            line = f"- **{name}**  \n  Type: `{tool_type}`"
            if connector != "n/a":
                line += f"  \n  Connector ID: `{connector}`"
            line += f"  \n  Authentication: uses **{auth}**"

            details = []
            for key, value in tool.details.items():
                if value:
                    details.append(f"{key}={value}")
            if details:
                line += f"  \n  Details: `{'; '.join(details)}`"

            lines.append(line)
        lines.append("")

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

    seen_edges: set[tuple[str, str]] = set()
    declared_node_ids: set[str] = set()

    label_to_id: dict[str, str] = {}

    def _escape_label(text: str) -> str:
        # Mermaid quoted labels require escaped quotes/backslashes/newlines.
        return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    def _node_id_for(label: str) -> str:
        existing = label_to_id.get(label)
        if existing:
            return existing
        node_id = f"N{len(label_to_id) + 1}"
        label_to_id[label] = node_id
        return node_id

    for conn in profile.topic_connections:
        src = conn.source_display or conn.source_schema or "Unknown"
        dst = conn.target_display or conn.target_schema or "Unknown"
        edge = (src, dst)
        if edge in seen_edges:
            continue
        seen_edges.add(edge)

        sid = _node_id_for(src)
        did = _node_id_for(dst)
        if sid not in declared_node_ids:
            declared_node_ids.add(sid)
            lines.append(f'    {sid}["{_escape_label(src)}"]')
        if did not in declared_node_ids:
            declared_node_ids.add(did)
            lines.append(f'    {did}["{_escape_label(dst)}"]')
        lines.append(f"    {sid} --> {did}")

    lines += ["```", ""]
    return "\n".join(lines)


_SYSTEM_TRIGGER_KINDS: frozenset[str] = frozenset(
    {
        "OnConversationStart",
        "OnUnknownIntent",
        "OnEscalate",
        "OnError",
        "OnSignIn",
        "OnEndConversation",
        "OnActivity",
    }
)

# Guardrail topics that every production agent should have (trigger_kind → label)
_GUARDRAIL_TOPICS: dict[str, str] = {
    "OnUnknownIntent": "Fallback (Unknown Intent)",
    "OnEscalate": "Escalate",
    "OnEndConversation": "End Conversation",
}


def render_topic_trigger_audit(profile: MCSBotProfile) -> str:
    """Render the Topic & Trigger Audit section of the report."""
    lines: list[str] = ["## Topic & Trigger Audit", ""]

    dialog_topics = [c for c in profile.components if c.kind == "DialogComponent"]

    if not dialog_topics:
        lines += ["_No topics found in this snapshot._", ""]
        return "\n".join(lines)

    total_topics = len(dialog_topics)
    custom_topics = sum(1 for c in dialog_topics if c.trigger_kind not in _SYSTEM_TRIGGER_KINDS)
    system_topics = total_topics - custom_topics
    lines += [
        "### Overview",
        "",
        f"Detected **{total_topics}** topic(s): **{custom_topics}** custom and **{system_topics}** system trigger topic(s).",
        "",
    ]

    # ── Orchestration Mode ─────────────────────────────────────────────────────
    lines += ["### Orchestration Mode", ""]
    if profile.gpt_info:
        model_name = profile.gpt_info.model_hint or "GPT"
        lines += [
            f"Orchestration: **Generative AI ({model_name})**  ",
            "_Triggers are suggestions — the LLM decides when to invoke each topic._",
            "",
        ]
    elif profile.recognizer_kind and profile.recognizer_kind.lower() not in ("unknown", ""):
        recognizer_label = profile.recognizer_kind
        if profile.recognizer_id:
            recognizer_label += f" (`{profile.recognizer_id}`)"
        lines += [
            f"Orchestration: **Classic ({recognizer_label})**  ",
            "_Ensure each intent-based topic has sufficient trigger phrase coverage._",
            "",
        ]
    else:
        lines += ["_Orchestration mode could not be determined._", ""]

    # ── Conflicting Triggers ───────────────────────────────────────────────────
    lines += ["### Conflicting Triggers", ""]

    phrase_to_topics: dict[str, list[str]] = {}
    for comp in dialog_topics:
        if not comp.trigger_queries:
            continue
        name = comp.display_name or comp.schema_name or "Unknown"
        for phrase in comp.trigger_queries:
            key = phrase.strip().lower()
            if key:
                phrase_to_topics.setdefault(key, []).append(name)

    conflicts = {phrase: topics for phrase, topics in phrase_to_topics.items() if len(topics) > 1}
    if conflicts:
        for phrase, topics in sorted(conflicts.items()):
            topic_names = ", ".join(f"`{_compact_component_name(t)}`" for t in topics)
            lines.append(f'- ⚠️ Trigger phrase conflict\n  Phrase: **"{phrase}"**\n  Topics: {topic_names}')
        lines.append("")
    else:
        lines += ["_No overlapping trigger phrases detected._", ""]

    # ── Orphan Topics ──────────────────────────────────────────────────────────
    lines += ["### Orphan Topics", ""]

    called_targets: set[str] = {c.target_schema for c in profile.topic_connections}
    called_targets |= {c.target_display for c in profile.topic_connections}

    orphans: list[str] = []
    for comp in dialog_topics:
        if comp.trigger_kind in _SYSTEM_TRIGGER_KINDS:
            continue
        has_triggers = bool(comp.trigger_queries)
        is_called = comp.schema_name in called_targets or comp.display_name in called_targets
        if not has_triggers and not is_called:
            name = _compact_component_name(comp.display_name or comp.schema_name or "Unknown")
            state_note = f" _(state: {comp.state})_" if comp.state and comp.state.lower() != "active" else ""
            orphans.append(
                "- ⚠️ Orphan topic"
                f"\n  Topic: **{name}**{state_note}"
                "\n  Reason: no trigger phrases and not called by any other topic"
            )

    if orphans:
        lines += orphans + [""]
    else:
        lines += ["_No orphaned topics detected._", ""]

    # ── Missing Guardrails ─────────────────────────────────────────────────────
    lines += ["### Missing Guardrails", ""]

    active_trigger_kinds: set[str] = {
        c.trigger_kind for c in dialog_topics if c.trigger_kind and c.state.lower() == "active"
    }
    all_trigger_kinds: set[str] = {c.trigger_kind for c in dialog_topics if c.trigger_kind}

    guardrail_issues: list[str] = []
    for trigger_kind, label in _GUARDRAIL_TOPICS.items():
        if trigger_kind not in all_trigger_kinds:
            guardrail_issues.append(
                f"- 🚨 Missing guardrail\n  Topic: **{label}** (`{trigger_kind}`)\n  Status: **missing**"
            )
        elif trigger_kind not in active_trigger_kinds:
            guardrail_issues.append(
                "- ⚠️ Guardrail not active"
                f"\n  Topic: **{label}** (`{trigger_kind}`)"
                "\n  Status: exists but is **inactive/disabled**"
            )

    if guardrail_issues:
        lines += guardrail_issues + [""]
    else:
        lines += ["_All essential guardrail topics are present and active. ✅_", ""]

    return "\n".join(lines)


def render_model_comparison(profile: MCSBotProfile) -> str:
    """Render the Model Performance Comparison section for a bot profile."""
    from toolkit.mcs.model_comparison import build_comparison_markdown

    return build_comparison_markdown(profile)


def render_mermaid_sequence(timeline: MCSConversationTimeline) -> str:
    if not timeline.events:
        return ""

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


def _format_clock(ts: str | None) -> str:
    """Format an ISO timestamp into HH:MM:SS (best effort)."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ""


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


def build_conversation_flow_items(timeline: MCSConversationTimeline) -> list[dict]:
    """Build chat-style flow items from timeline events for UI rendering.

    Output item format:
    - message: {kind, role, actor, text, timestamp}
    - event: {kind, event_type, title, summary, timestamp, tone}
    """
    items: list[dict] = []

    def _strip_prefix(text: str, prefix: str) -> str:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
        return text

    for ev in timeline.events:
        summary = (ev.summary or "").strip()
        timestamp = _format_clock(ev.timestamp)

        if ev.event_type == MCSEventType.USER_MESSAGE:
            items.append(
                {
                    "kind": "message",
                    "role": "user",
                    "actor": ACTOR_NAMES["user"],
                    "text": _strip_prefix(summary, "User:"),
                    "timestamp": timestamp,
                }
            )
            continue

        if ev.event_type == MCSEventType.BOT_MESSAGE:
            items.append(
                {
                    "kind": "message",
                    "role": "bot",
                    "actor": ACTOR_NAMES["bot"],
                    "text": _strip_prefix(summary, "Bot:"),
                    "timestamp": timestamp,
                }
            )
            continue

        # Keep high-value telemetry items as system cards between chat turns.
        if ev.event_type in {
            MCSEventType.PLAN_RECEIVED,
            MCSEventType.PLAN_FINISHED,
            MCSEventType.STEP_TRIGGERED,
            MCSEventType.STEP_FINISHED,
            MCSEventType.KNOWLEDGE_SEARCH,
            MCSEventType.DIALOG_TRACING,
            MCSEventType.DIALOG_REDIRECT,
            MCSEventType.ERROR,
        }:
            title_map = {
                MCSEventType.PLAN_RECEIVED: "Plan Received",
                MCSEventType.PLAN_FINISHED: "Plan Finished",
                MCSEventType.STEP_TRIGGERED: "Action Started",
                MCSEventType.STEP_FINISHED: "Action Finished",
                MCSEventType.KNOWLEDGE_SEARCH: "Knowledge Search",
                MCSEventType.DIALOG_TRACING: "Topic Trace",
                MCSEventType.DIALOG_REDIRECT: "Topic Redirect",
                MCSEventType.ERROR: "Error",
            }
            tone = "error" if ev.event_type == MCSEventType.ERROR else "info"
            detail = summary
            if ev.event_type == MCSEventType.KNOWLEDGE_SEARCH and ev.search_query:
                detail = f'Query: "{ev.search_query}"'

            items.append(
                {
                    "kind": "event",
                    "event_type": ev.event_type.value,
                    "title": title_map.get(ev.event_type, ev.event_type.value),
                    "summary": detail,
                    "timestamp": timestamp,
                    "tone": tone,
                }
            )

    return items


def build_conversation_visual_summary(timeline: MCSConversationTimeline) -> dict[str, list[dict]]:
    """Build visual-friendly conversation summary structures for the UI."""
    user_msgs = sum(1 for e in timeline.events if e.event_type == MCSEventType.USER_MESSAGE)
    bot_msgs = sum(1 for e in timeline.events if e.event_type == MCSEventType.BOT_MESSAGE)
    searches = sum(1 for e in timeline.events if e.event_type == MCSEventType.KNOWLEDGE_SEARCH)
    errors = sum(1 for e in timeline.events if e.event_type == MCSEventType.ERROR)

    turns = _pair_message_turns(timeline)
    avg_latency = (sum(t["latency_ms"] for t in turns) / len(turns)) if turns else 0.0
    p95_latency = 0.0
    if turns:
        sorted_lat = sorted(t["latency_ms"] for t in turns)
        idx = int(max(0, min(len(sorted_lat) - 1, round(0.95 * (len(sorted_lat) - 1)))))
        p95_latency = sorted_lat[idx]

    started_steps = [e for e in timeline.events if e.event_type == MCSEventType.STEP_TRIGGERED and e.step_id]
    finished_step_ids = {e.step_id for e in timeline.events if e.event_type == MCSEventType.STEP_FINISHED and e.step_id}
    orphaned_steps = sum(1 for e in started_steps if e.step_id not in finished_step_ids)

    kpis = [
        {
            "label": "User Messages",
            "value": str(user_msgs),
            "hint": "Incoming requests",
            "tone": "neutral",
        },
        {
            "label": "Bot Responses",
            "value": str(bot_msgs),
            "hint": "Delivered answers",
            "tone": "neutral",
        },
        {
            "label": "Avg Turn Latency",
            "value": f"{avg_latency:.0f} ms",
            "hint": "User -> bot response",
            "tone": "neutral" if avg_latency < 4000 else "warn",
        },
        {
            "label": "P95 Turn Latency",
            "value": f"{p95_latency:.0f} ms",
            "hint": "Worst typical latency",
            "tone": "warn" if p95_latency >= 6000 else "neutral",
        },
    ]

    mix_raw = [
        ("Messages", user_msgs + bot_msgs, "#0a66ff"),
        ("Steps", len(started_steps), "#0f8c76"),
        ("Search", searches, "#c17c00"),
        ("Errors", errors, "#b4232a"),
    ]
    mix_total = sum(v for _, v, _ in mix_raw) or 1
    event_mix = [
        {
            "label": label,
            "count": str(count),
            "color": color,
            "pct": f"{(count / mix_total) * 100:.1f}%",
        }
        for label, count, color in mix_raw
    ]

    bands = [
        ("< 1s", sum(1 for t in turns if t["latency_ms"] < 1000), "#107c10"),
        ("1-3s", sum(1 for t in turns if 1000 <= t["latency_ms"] < 3000), "#0a66ff"),
        ("3-8s", sum(1 for t in turns if 3000 <= t["latency_ms"] < 8000), "#c7921e"),
        (">= 8s", sum(1 for t in turns if t["latency_ms"] >= 8000), "#a4262c"),
    ]
    turns_total = len(turns) or 1
    latency_bands = [
        {
            "label": label,
            "count": str(count),
            "color": color,
            "pct": f"{(count / turns_total) * 100:.1f}%",
        }
        for label, count, color in bands
    ]

    highlights = [
        {
            "title": "Errors",
            "value": str(errors),
            "tone": "bad" if errors > 0 else "good",
        },
        {
            "title": "Open Steps",
            "value": str(orphaned_steps),
            "tone": "bad" if orphaned_steps > 0 else "good",
        },
        {
            "title": "Search Calls",
            "value": str(searches),
            "tone": "info",
        },
    ]

    return {
        "kpis": kpis,
        "event_mix": event_mix,
        "latency_bands": latency_bands,
        "highlights": highlights,
    }


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
        lines.append(f"    U->>C: [{uts}] {umsg}")
        lines.append(f"    C-->>U: [{bts}] {bmsg}")

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

    lines += [
        "",
        "### Universal Search Diagnostics",
        "",
        "| Timestamp | Query | Sources | Results |",
        "| --- | --- | --- | ---: |",
    ]
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
        render_knowledge_sources_and_tools(profile),
        render_components(profile),
        render_topic_graph(profile),
        render_topic_trigger_audit(profile),
        render_model_comparison(profile),
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

    Keys: ``"profile"``, ``"knowledge_tools"``, ``"topics"``, ``"graph"``, ``"audit"``, ``"conversation"``.
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

    knowledge_tools_md = render_knowledge_sources_and_tools(profile)

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

    audit_md = render_topic_trigger_audit(profile)

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
        "knowledge_tools": knowledge_tools_md,
        "topics": topics_md,
        "graph": graph_md,
        "audit": audit_md,
        "model_comparison": render_model_comparison(profile),
        "conversation": conversation_md,
    }


def to_viz_segments(profile: MCSBotProfile) -> list[dict]:
    """Convert a snapshot bot profile into viz_segments (same format as visualize_zip_bytes).

    Used to populate the Visualize tab for Copilot Studio snapshot ZIPs.
    """
    segments: list[dict] = []

    # Keep Visualize focused on topology to avoid duplicating Profile details
    # that are already presented in the Analyse tab.
    component_total = len(profile.components)
    dialog_topics = sum(1 for c in profile.components if c.kind == "DialogComponent")
    knowledge_sources = len(profile.knowledge_sources)
    external_tools = len(profile.external_tools)
    topic_edges = len(profile.topic_connections)
    topology_summary_md = "\n".join(
        [
            "## Topology Overview",
            "",
            "Visualize focuses on connection topology. Detailed bot profile and AI settings are available in Analyse > Profile.",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Components | {component_total} |",
            f"| Dialog Topics | {dialog_topics} |",
            f"| Topic Connections | {topic_edges} |",
            f"| Knowledge Sources | {knowledge_sources} |",
            f"| External Tools | {external_tools} |",
            "",
        ]
    )
    segments.append({"type": "text", "content": topology_summary_md})

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
    else:
        segments.append(
            {
                "type": "text",
                "content": "## Topic Redirect Graph\n\n_No topic-to-topic connections were found in this snapshot._\n",
            }
        )

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
