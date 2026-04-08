"""MCS Agent Analyser — render Markdown + Mermaid reports.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

import html as _html
import re
import socket
from datetime import datetime
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
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

# SVG timeline colours: (bar_fill, accent/text)
_SVG_PHASE_COLORS: dict[str, tuple[str, str]] = {
    "DynamicPlan": ("#ffc8c3", "#c0392b"),
    "Search": ("#cce0ff", "#0a66ff"),
    "System": ("#c8f0d8", "#107c10"),
    "Redirect": ("#ddd4ff", "#5b21b6"),
}
_SVG_DEFAULT_COLOR: tuple[str, str] = ("#b8d0f8", "#1a3a6b")

# SVG event-log colours per event type: (actor_char, row_bg, text_color)
_SVG_EVENT_STYLES: dict[str, tuple[str, str, str]] = {}  # populated after MCSEventType is importable


def _svg_event_styles() -> dict:
    """Lazily build the event-styles map so it doesn't depend on import order."""
    if _SVG_EVENT_STYLES:
        return _SVG_EVENT_STYLES
    _SVG_EVENT_STYLES.update(
        {
            MCSEventType.USER_MESSAGE: ("U", "#ddeeff", "#1a3a6b"),
            MCSEventType.BOT_MESSAGE: ("C", "#d8f5e0", "#0d5c26"),
            MCSEventType.STEP_TRIGGERED: ("▶", "#fff0cc", "#7a5200"),
            MCSEventType.STEP_FINISHED: ("✓", "#e0f4e0", "#0a4020"),
            MCSEventType.KNOWLEDGE_SEARCH: ("S", "#d3eaff", "#0a4299"),
            MCSEventType.PLAN_RECEIVED: ("P", "#ede9ff", "#3b1a7a"),
            MCSEventType.PLAN_RECEIVED_DEBUG: ("P", "#ede9ff", "#3b1a7a"),
            MCSEventType.PLAN_FINISHED: ("P", "#ede9ff", "#3b1a7a"),
            MCSEventType.DIALOG_REDIRECT: ("→", "#fce8ff", "#6b007a"),
            MCSEventType.ERROR: ("!", "#fce8e8", "#7a0010"),
            MCSEventType.DIALOG_TRACING: ("T", "#fff8e0", "#664400"),
            MCSEventType.VARIABLE_ASSIGNMENT: ("V", "#f0f0f0", "#404040"),
            MCSEventType.ACTION_HTTP_REQUEST: ("H", "#e8f0ff", "#1a3a6b"),
            MCSEventType.ACTION_BEGIN_DIALOG: ("D", "#f0f8ff", "#1a5a9a"),
            MCSEventType.ACTION_SEND_ACTIVITY: ("A", "#f0fff4", "#0a4020"),
            MCSEventType.ACTION_TRIGGER_EVAL: ("E", "#fff4f0", "#7a3000"),
            MCSEventType.ACTION_QA: ("Q", "#fffbe0", "#664400"),
        }
    )
    return _SVG_EVENT_STYLES


_SVG_EVENT_DEFAULT: tuple[str, str, str] = ("·", "#f3f3f3", "#605e5c")


def _render_chat_svg(turns: list[dict]) -> str:
    """Build a two-column chat swimlane SVG from paired user/bot turns."""
    limited = turns[:60]
    n = len(limited)
    if not n:
        return ""

    W = 760
    HEADER_H = 34
    ROW_H = 52
    PAD = 12
    CX = W // 2  # centre divider x

    h = HEADER_H + n * ROW_H + PAD

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" '
        f'width="100%" style="font-family:\'Segoe UI\',system-ui,sans-serif;display:block">',
        f'<rect width="{W}" height="{h}" rx="10" fill="#f8fbff" stroke="#d7e2f2" stroke-width="1"/>',
        # Column headers
        f'<rect x="0" y="0" width="{CX}" height="{HEADER_H}" rx="8" fill="#ddeeff"/>',
        f'<rect x="{CX}" y="0" width="{CX}" height="{HEADER_H}" rx="8" fill="#d8f5e0"/>',
        # square off the bottom corners of the rounded header rects
        f'<rect x="0" y="{HEADER_H - 6}" width="{CX}" height="6" fill="#ddeeff"/>',
        f'<rect x="{CX}" y="{HEADER_H - 6}" width="{CX}" height="6" fill="#d8f5e0"/>',
        f'<text x="{CX // 2}" y="22" text-anchor="middle" font-size="13" font-weight="700" fill="#1a3a6b">User</text>',
        f'<text x="{CX + CX // 2}" y="22" text-anchor="middle" font-size="13" font-weight="700" fill="#0d5c26">Copilot</text>',
        f'<line x1="0" y1="{HEADER_H}" x2="{W}" y2="{HEADER_H}" stroke="#c0d4ee" stroke-width="1"/>',
        f'<line x1="{CX}" y1="{HEADER_H}" x2="{CX}" y2="{h - PAD}" stroke="#c0d4ee" stroke-width="1" stroke-dasharray="4,3"/>',
    ]

    for i, turn in enumerate(limited):
        y = HEADER_H + i * ROW_H
        bg = "#f4f8ff" if i % 2 == 0 else "#fbfeff"
        out.append(f'<rect x="0" y="{y}" width="{W}" height="{ROW_H}" fill="{bg}"/>')
        if i < n - 1:
            out.append(f'<line x1="0" y1="{y + ROW_H}" x2="{W}" y2="{y + ROW_H}" stroke="#e8eef8" stroke-width="1"/>')

        umsg = _html.escape((turn.get("user_msg") or "")[:55])
        bmsg = _html.escape((turn.get("bot_msg") or "")[:55])
        lat_ms = int(turn.get("latency_ms") or 0)
        uts = turn.get("user_ts") or ""
        uts_fmt = uts[-14:-6] if len(uts) >= 14 else uts[-8:] if uts else ""

        # User side (left)
        out.append(f'<text x="{PAD}" y="{y + 20}" font-size="12" fill="#1a3a6b">{umsg}</text>')
        if uts_fmt:
            out.append(f'<text x="{PAD}" y="{y + 38}" font-size="10" fill="#7899c4">{_html.escape(uts_fmt)}</text>')

        # Latency badge straddling the centre line
        lat_txt = f"{lat_ms}ms"
        badge_w = max(len(lat_txt) * 7, 44)
        bx = CX - badge_w // 2
        by = y + ROW_H // 2 - 9
        out.append(
            f'<rect x="{bx}" y="{by}" width="{badge_w}" height="18" rx="9" '
            f'fill="#fffbe0" stroke="#c7921e" stroke-width="0.8"/>'
        )
        out.append(
            f'<text x="{CX}" y="{by + 13}" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#7a5200">{_html.escape(lat_txt)}</text>'
        )

        # Bot side (right)
        out.append(f'<text x="{CX + PAD}" y="{y + 20}" font-size="12" fill="#0d5c26">{bmsg}</text>')

    if len(turns) > 60:
        out.append(
            f'<text x="{CX}" y="{h - 4}" text-anchor="middle" font-size="10" fill="#93a8c8">'
            f"… {len(turns) - 60} more turns not shown</text>"
        )

    out.append("</svg>")
    return "\n".join(out)


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
    def _as_blockquote(markdown: str) -> str:
        raw = markdown.strip()
        if not raw:
            return "> _(none)_"
        quoted_lines: list[str] = []
        for line in raw.splitlines():
            quoted_lines.append(">" if line.strip() == "" else f"> {line}")
        return "\n".join(quoted_lines)

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
            _as_blockquote(gpt.instructions or ""),
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
    if "sync" in low and "sharepoint" in low:
        return "SharePoint Sync"
    if "page" in low and "sharepoint" in low:
        return "SharePoint Page"
    if "website" in low or "public" in low:
        return "Website"
    if "sharepoint" in low:
        return "SharePoint"
    if "uploaded file" in low:
        return "Uploaded File"
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


def _knowledge_group_label(source_type: str) -> str:
    low = source_type.lower()
    if "uploaded file" in low or low == "file":
        return "Uploaded File"
    if "sharepoint sync" in low:
        return "SharePoint Sync"
    if "sharepoint page" in low:
        return "SharePoint"
    if "sharepoint" in low:
        return "SharePoint"
    if "website" in low:
        return "Website"
    if "dataverse" in low:
        return "Dataverse"
    return "Other"


def _extract_source_description(source) -> str:
    return (source.details.get("description", "") if source.details else "").strip()


def _has_grounding_guidance(instructions: str) -> bool:
    if not instructions:
        return False
    low = instructions.lower()
    patterns = (
        "knowledge source",
        "sharepoint",
        "uploaded file",
        "ground",
        "cite",
        "if not found",
        "when unsure",
        "use provided documents",
    )
    return any(p in low for p in patterns)


def _tokenize_terms(text: str) -> set[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "into",
        "your",
        "you",
        "are",
        "use",
        "using",
        "agent",
        "knowledge",
        "source",
        "sources",
        "information",
    }
    return {t for t in re.findall(r"[a-zA-Z0-9]{3,}", text.lower()) if t not in stop}


def _classify_result_source_type(source_ref: str) -> str:
    low = (source_ref or "").lower()
    if not low:
        return "Other"
    if "sharepoint" in low or "sharepoint.com" in low:
        return "SharePoint"
    if "dataverse" in low or "dynamics.com" in low or ".crm" in low:
        return "Dataverse"
    if re.search(r"\.(pdf|pptx|docx|xlsx|csv|txt|md|json)(\?|$)", low):
        return "File"
    if low.startswith("http://") or low.startswith("https://"):
        return "Website"
    return "Other"


def _result_source_mix_counts(result_sources: list[str], top_results: list[str]) -> dict[str, int]:
    counts = {
        "SharePoint": 0,
        "Dataverse": 0,
        "Website": 0,
        "File": 0,
        "Other": 0,
    }
    for source_ref in result_sources + top_results:
        counts[_classify_result_source_type(source_ref)] += 1
    return counts


def _instruction_alignment_status(source, instructions: str) -> tuple[str, str]:
    if not instructions.strip():
        return "High risk", "Instructions are empty, so the orchestrator has no guidance to pick this source."

    name_terms = _tokenize_terms(source.name or "")
    location_terms: set[str] = set()
    if source.location:
        parsed = urlparse(source.location)
        host_terms = _tokenize_terms(parsed.hostname or "")
        path_terms = _tokenize_terms(parsed.path or "")
        location_terms = host_terms | path_terms
    desc_terms = _tokenize_terms(_extract_source_description(source))

    candidate_terms = set(list(name_terms)[:8]) | set(list(location_terms)[:6]) | set(list(desc_terms)[:8])
    instr_terms = _tokenize_terms(instructions)
    overlap = candidate_terms & instr_terms

    if overlap:
        return "Good", f"Instruction overlap detected: {', '.join(sorted(list(overlap))[:4])}."
    if _has_grounding_guidance(instructions):
        return "Partial", "Instructions include general grounding guidance but do not reference this source explicitly."
    return "Needs work", "No source-specific or grounding guidance found for this source."


def _description_quality_status(source) -> tuple[str, str]:
    desc = _extract_source_description(source)
    if not desc:
        return "Needs work", "Missing description. Add scope, coverage, and expected usage in one sentence."

    if len(desc) < 45:
        return "Needs work", "Description is too short for retrieval guidance. Include domain and intended question types."

    generic_starts = (
        "this knowledge source searches information contained",
        "this knowledge source provides information",
        "diese wissensquelle stellt informationen bereit",
    )
    low = desc.lower().strip()
    if any(low.startswith(prefix) for prefix in generic_starts):
        return "Partial", "Description is generic template text; add concrete topic/domain cues and freshness context."

    return "Good", "Description appears specific enough for source routing."


def _is_generic_description(desc: str) -> bool:
    low = (desc or "").strip().lower()
    if not low:
        return False
    generic_patterns = (
        "this knowledge source searches information contained",
        "this knowledge source provides information",
        "diese wissensquelle stellt informationen bereit",
    )
    return any(p in low for p in generic_patterns)


def _render_instruction_patch_suggestion(profile: MCSBotProfile) -> list[str]:
    if not profile.knowledge_sources:
        return []

    groups: dict[str, list] = {}
    for source in profile.knowledge_sources:
        source_type = _friendly_source_type(source.source_type)
        groups.setdefault(_knowledge_group_label(source_type), []).append(source)

    ordered_classes = [g for g in ["SharePoint", "SharePoint Sync", "Uploaded File", "Website", "Dataverse", "Other"] if groups.get(g)]
    if not ordered_classes:
        return []

    top_sources: list[str] = []
    for cls in ordered_classes:
        for source in groups[cls][:2]:
            top_sources.append(_compact_component_name(source.name or "Unnamed source"))

    class_line = ", ".join(ordered_classes)
    source_line = ", ".join(top_sources[:6])

    lines: list[str] = [
        "### Instruction Patch Suggestion",
        "",
        "Add this to system instructions to improve orchestrator grounding and source routing:",
        "",
        f"- When answering knowledge questions, prioritize source classes in this order: {class_line}.",
        f"- Prefer these named sources when relevant: {source_line}.",
        "- If no matching evidence is found, explicitly say evidence was not found in available knowledge sources and ask one clarifying question.",
        "- For factual claims, cite the source name (and URL when available) in the answer.",
        "- Do not invent policy, deadlines, or process details that are not present in the retrieved sources.",
        "",
    ]
    return lines


def _render_knowledge_validation(profile: MCSBotProfile) -> list[str]:
    lines: list[str] = ["### Knowledge Description & Instruction Alignment", ""]
    if not profile.knowledge_sources:
        lines += ["_No knowledge sources available to validate._", ""]
        return lines

    instructions = (profile.gpt_info.instructions if profile.gpt_info and profile.gpt_info.instructions else "").strip()
    if not instructions:
        lines += ["⚠️ GPT instructions are empty. Knowledge-source routing quality will likely be poor.", ""]

    lines += [
        "| Knowledge Source | Description Quality | Instruction Alignment |",
        "| --- | --- | --- |",
    ]

    desc_issues = 0
    align_issues = 0
    generic_desc_sources: list[str] = []
    for source in profile.knowledge_sources:
        source_type = _friendly_source_type(source.source_type)
        label = _compact_component_name(source.name or "Unnamed source")
        description = _extract_source_description(source)
        desc_status, desc_note = _description_quality_status(source)
        align_status, align_note = _instruction_alignment_status(source, instructions)

        if desc_status != "Good":
            desc_issues += 1
            if _is_generic_description(description):
                generic_desc_sources.append(label)
        if align_status in {"Needs work", "High risk"}:
            align_issues += 1

        lines.append(
            f"| {label} ({source_type}) | **{desc_status}** - {desc_note} | **{align_status}** - {align_note} |"
        )

    lines += [
        "",
        f"Summary: {desc_issues} source(s) need better descriptions, {align_issues} source(s) need stronger instruction alignment.",
        "",
    ]

    if generic_desc_sources:
        names = ", ".join(generic_desc_sources)
        lines += [
            "🚨 Warning: default or generic KB descriptions detected.",
            f"Affected sources: {names}",
            "These descriptions should be replaced with scope-specific guidance so the orchestrator can route retrieval more reliably.",
            "",
        ]

    if align_issues:
        lines += [
            "Recommended instruction pattern for orchestrator grounding:",
            "",
            "- Explicitly list preferred source classes in order (for example SharePoint policy pages before uploaded slide decks).",
            "- Instruct the agent to acknowledge uncertainty when no matching evidence is found in available sources.",
            "- Require concise source citation (source name or URL) in final answers for knowledge-backed claims.",
            "",
        ]

    if desc_issues or align_issues or generic_desc_sources:
        lines += _render_instruction_patch_suggestion(profile)

    return lines


def _severity_badge(level: str) -> str:
    norm = (level or "Info").strip().lower()
    if norm == "critical":
        return "🚨 **Critical**"
    if norm == "warning":
        return "⚠️ **Warning**"
    return "ℹ️ **Info**"


def _knowledge_health_summary(profile: MCSBotProfile) -> list[str]:
    """Build a compact top-level KB health summary with severity badges."""
    lines: list[str] = ["### Knowledge Health Summary", ""]
    if not profile.knowledge_sources:
        lines += ["_No knowledge sources detected._", ""]
        return lines

    instructions = (profile.gpt_info.instructions if profile.gpt_info and profile.gpt_info.instructions else "").strip()
    has_grounding = _has_grounding_guidance(instructions)

    desc_needs_work = 0
    generic_count = 0
    align_needs_work = 0
    align_high_risk = 0

    for source in profile.knowledge_sources:
        description = _extract_source_description(source)
        desc_status, _ = _description_quality_status(source)
        align_status, _ = _instruction_alignment_status(source, instructions)

        if desc_status != "Good":
            desc_needs_work += 1
        if _is_generic_description(description):
            generic_count += 1
        if align_status in {"Needs work", "High risk"}:
            align_needs_work += 1
        if align_status == "High risk":
            align_high_risk += 1

    if not instructions:
        grounding_severity = "Critical"
        grounding_detail = "Instructions missing; orchestrator has no source-usage guidance."
    elif align_high_risk > 0 or align_needs_work > 0:
        grounding_severity = "Warning"
        grounding_detail = f"{align_needs_work} source(s) are not well aligned with instructions."
    elif has_grounding:
        grounding_severity = "Info"
        grounding_detail = "Grounding guidance is present in instructions."
    else:
        grounding_severity = "Warning"
        grounding_detail = "Instructions do not include explicit grounding cues."

    if desc_needs_work == 0:
        desc_severity = "Info"
        desc_detail = "All KB descriptions look source-specific."
    elif generic_count > 0:
        desc_severity = "Warning"
        desc_detail = f"{generic_count} source(s) use default/generic template descriptions."
    else:
        desc_severity = "Warning"
        desc_detail = f"{desc_needs_work} source(s) need clearer scope descriptions."

    action_severity = "Critical" if not instructions else ("Warning" if (generic_count or align_needs_work) else "Info")
    action_detail = (
        "Add explicit source-priority and citation rules in instructions."
        if action_severity != "Info"
        else "Current setup is healthy; keep KB metadata maintained."
    )

    lines += [
        "| Check | Severity | Summary |",
        "| --- | --- | --- |",
        f"| Instruction grounding readiness | {_severity_badge(grounding_severity)} | {grounding_detail} |",
        f"| Knowledge description quality | {_severity_badge(desc_severity)} | {desc_detail} |",
        f"| Recommended action | {_severity_badge(action_severity)} | {action_detail} |",
        "",
    ]
    return lines


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
        lines += _knowledge_health_summary(profile)
        grouped: dict[str, list] = {}
        for source in profile.knowledge_sources:
            source_type = _friendly_source_type(source.source_type)
            grouped.setdefault(_knowledge_group_label(source_type), []).append(source)

        lines += [
            "| Source Class | Count |",
            "| --- | ---: |",
        ]
        for group_name in sorted(grouped):
            lines.append(f"| {group_name} | {len(grouped[group_name])} |")
        lines.append("")

        url_cache: dict[str, tuple[bool, str]] = {}
        group_order = ["Uploaded File", "SharePoint Sync", "SharePoint", "Website", "Dataverse", "Other"]
        for group_name in group_order:
            sources = grouped.get(group_name, [])
            if not sources:
                continue

            lines += [f"#### {group_name} ({len(sources)})", ""]
            for source in sources:
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
                elif source.location is None and group_name != "Uploaded File":
                    line += "  \n  Status: **Missing Resource⚠️** (no URL/path provided)"

                description = _extract_source_description(source)
                if description:
                    line += f"  \n  Description: {description}"

                details = []
                for key, value in source.details.items():
                    if value and key not in {"description"}:
                        details.append(f"{key}={value}")
                if details:
                    line += f"  \n  Details: `{'; '.join(details)}`"

                lines.append(line)
            lines.append("")

        lines += _render_knowledge_validation(profile)
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
        '%%{init: {"useMaxWidth": false, "theme": "base", "themeVariables": {"fontFamily": "Segoe UI, Arial, sans-serif", "fontSize": "14px", "primaryTextColor": "#102548", "lineColor": "#6f86a8"}, "flowchart": {"htmlLabels": false, "curve": "basis", "nodeSpacing": 60, "rankSpacing": 80, "padding": 16}}}%%',
        "graph TD",
        "    classDef default fill:#ffffff,stroke:#8bb8ff,stroke-width:1.6px,color:#102548;",
        "    linkStyle default stroke:#6f86a8,stroke-width:1.4px;",
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
            lines.append(f'    {sid}("{_escape_label(src)}")')
        if did not in declared_node_ids:
            declared_node_ids.add(did)
            lines.append(f'    {did}("{_escape_label(dst)}")')
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
    """Render the full event flow as a self-contained SVG (ppsvg fence, Mermaid-free)."""
    if not timeline.events:
        return ""

    styles = _svg_event_styles()
    limited = timeline.events[:120]
    n = len(limited)

    W = 780
    HEADER_H = 34
    ROW_H = 38
    ACTOR_D = 26         # actor badge diameter
    TYPE_W = 130         # event-type label column width
    TS_W = 70            # timestamp column width
    PAD = 10
    h = HEADER_H + n * ROW_H + PAD

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" '
        f'width="100%" style="font-family:\'Segoe UI\',system-ui,sans-serif;display:block">',
        f'<rect width="{W}" height="{h}" rx="10" fill="#f8fbff" stroke="#d7e2f2" stroke-width="1"/>',
        # Header bar
        f'<rect x="0" y="0" width="{W}" height="{HEADER_H}" rx="8" fill="#eef3fb"/>',
        f'<rect x="0" y="{HEADER_H - 6}" width="{W}" height="6" fill="#eef3fb"/>',
        f'<line x1="0" y1="{HEADER_H}" x2="{W}" y2="{HEADER_H}" stroke="#c0d4ee" stroke-width="1"/>',
        f'<text x="{PAD + ACTOR_D // 2}" y="22" text-anchor="middle" font-size="11" font-weight="700" fill="#4d6287">#</text>',
        f'<text x="{PAD + ACTOR_D + 8}" y="22" font-size="11" font-weight="700" fill="#4d6287">Actor</text>',
        f'<text x="{PAD + ACTOR_D + 36}" y="22" font-size="11" font-weight="700" fill="#4d6287">Event Type</text>',
        f'<text x="{PAD + ACTOR_D + TYPE_W + 44}" y="22" font-size="11" font-weight="700" fill="#4d6287">Summary</text>',
        f'<text x="{W - PAD}" y="22" text-anchor="end" font-size="11" font-weight="700" fill="#4d6287">Time</text>',
    ]

    for i, event in enumerate(limited):
        y = HEADER_H + i * ROW_H
        actor_char, row_bg, text_fg = styles.get(event.event_type, _SVG_EVENT_DEFAULT)
        label = _html.escape((event.summary or "")[:90])
        ts = _format_clock(event.timestamp)
        ev_name = _html.escape(
            (event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type or ""))
            .replace("Action", "")
            .replace("MCS", "")
        )

        if i % 2 == 0:
            out.append(f'<rect x="0" y="{y}" width="{W}" height="{ROW_H}" fill="#f0f4fa"/>')

        # Row divider
        if i < n - 1:
            out.append(
                f'<line x1="{PAD}" y1="{y + ROW_H}" x2="{W - PAD}" y2="{y + ROW_H}" '
                f'stroke="#e8eef8" stroke-width="1"/>'
            )

        mid_y = y + ROW_H // 2

        # Actor badge (circle)
        out.append(
            f'<circle cx="{PAD + ACTOR_D // 2}" cy="{mid_y}" r="{ACTOR_D // 2}" fill="{row_bg}"/>'
        )
        out.append(
            f'<text x="{PAD + ACTOR_D // 2}" y="{mid_y + 4}" text-anchor="middle" '
            f'font-size="11" font-weight="700" fill="{text_fg}">{_html.escape(actor_char)}</text>'
        )

        # Event type label
        out.append(
            f'<text x="{PAD + ACTOR_D + 8}" y="{mid_y + 4}" '
            f'font-size="10" fill="#4d6287">{ev_name}</text>'
        )

        # Summary
        label_x = PAD + ACTOR_D + TYPE_W + 44
        out.append(
            f'<text x="{label_x}" y="{mid_y + 4}" font-size="11" fill="#2f425f">{label}</text>'
        )

        # Timestamp
        if ts:
            out.append(
                f'<text x="{W - PAD}" y="{mid_y + 4}" text-anchor="end" '
                f'font-size="10" fill="#93a8c8">{_html.escape(ts)}</text>'
            )

    if len(timeline.events) > 120:
        out.append(
            f'<text x="{W // 2}" y="{h - 4}" text-anchor="middle" font-size="10" fill="#93a8c8">'
            f"… {len(timeline.events) - 120} more events not shown</text>"
        )

    out.append("</svg>")
    svg_str = "\n".join(out)
    return f"## Conversation Event Flow\n\n```ppsvg\n{svg_str}\n```\n"


def render_svg_timeline(timeline: MCSConversationTimeline) -> str:
    """Render a self-contained SVG horizontal bar chart for execution phases.

    The SVG is wrapped in a ``ppsvg`` Markdown fence so the web layer renders
    it via ``rx.html()`` — Mermaid is never involved.
    """
    if not timeline.phases:
        return ""

    phases = timeline.phases
    n = len(phases)
    durations = [max(int(p.duration_ms) if p.duration_ms else 50, 1) for p in phases]
    total_ms = sum(durations)

    ROW_H = 36
    LABEL_W = 210
    BAR_AREA_W = 560
    AXIS_H = 28
    HEADER_H = 44
    PAD = 16
    w = PAD + LABEL_W + BAR_AREA_W + PAD
    h = HEADER_H + n * ROW_H + AXIS_H + PAD

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="100%" style="font-family:\'Segoe UI\',system-ui,sans-serif;display:block">',
        f'<rect width="{w}" height="{h}" rx="12" fill="#f8fbff" stroke="#d7e2f2" stroke-width="1"/>',
        f'<text x="{w // 2}" y="28" text-anchor="middle" font-size="14" '
        f'font-weight="700" fill="#102548">Execution Phases</text>',
        f'<line x1="{PAD + LABEL_W}" y1="{HEADER_H - 4}" '
        f'x2="{PAD + LABEL_W}" y2="{HEADER_H + n * ROW_H + 4}" '
        f'stroke="#c0cfe8" stroke-width="1"/>',
    ]

    for i, (phase, dur) in enumerate(zip(phases, durations)):
        y = HEADER_H + i * ROW_H
        bar_w = max(int(BAR_AREA_W * dur / max(total_ms, 1)), 4)
        bar_x = PAD + LABEL_W
        bar_y = y + 6
        bar_h = ROW_H - 12
        label_txt = _html.escape((phase.label or phase.phase_type or "Phase")[:32])
        fill, accent = _SVG_PHASE_COLORS.get(phase.phase_type, _SVG_DEFAULT_COLOR)
        ms_txt = _html.escape(f"{int(phase.duration_ms)}ms") if phase.duration_ms else ""

        if i % 2 == 0:
            out.append(
                f'<rect x="{PAD}" y="{y}" width="{LABEL_W + BAR_AREA_W}" '
                f'height="{ROW_H}" fill="#eef4ff" rx="3"/>'
            )
        out.append(
            f'<text x="{PAD + LABEL_W - 8}" y="{y + ROW_H // 2 + 5}" '
            f'text-anchor="end" font-size="12" fill="#2f425f">{label_txt}</text>'
        )
        out.append(
            f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" '
            f'rx="4" fill="{fill}" stroke="{accent}" stroke-width="0.5" stroke-opacity="0.4"/>'
        )
        if ms_txt:
            if bar_w > 50:
                out.append(
                    f'<text x="{bar_x + bar_w - 6}" y="{bar_y + bar_h // 2 + 4}" '
                    f'text-anchor="end" font-size="10" fill="{accent}">{ms_txt}</text>'
                )
            else:
                out.append(
                    f'<text x="{bar_x + bar_w + 5}" y="{bar_y + bar_h // 2 + 4}" '
                    f'font-size="10" fill="{accent}">{ms_txt}</text>'
                )

    axis_y = HEADER_H + n * ROW_H + 6
    out.append(
        f'<line x1="{PAD + LABEL_W}" y1="{axis_y}" '
        f'x2="{PAD + LABEL_W + BAR_AREA_W}" y2="{axis_y}" '
        f'stroke="#c0cfe8" stroke-width="1"/>'
    )
    out.append(
        f'<text x="{PAD + LABEL_W}" y="{axis_y + 14}" '
        f'text-anchor="start" font-size="10" fill="#93a8c8">0ms</text>'
    )
    out.append(
        f'<text x="{PAD + LABEL_W + BAR_AREA_W}" y="{axis_y + 14}" '
        f'text-anchor="end" font-size="10" fill="#93a8c8">{_html.escape(str(total_ms))}ms total</text>'
    )
    out.append("</svg>")

    svg_str = "\n".join(out)
    return f"## Execution Gantt Chart\n\n```ppsvg\n{svg_str}\n```\n"


# Keep the old name as an alias for backward-compatibility.
render_gantt_chart = render_svg_timeline


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
    - message: {kind, role, actor, text, timestamp, lane}
    - event:   {kind, event_type, title, summary, timestamp, tone, lane}

    lane values: "user" | "bot" | "tool" | "error"
    """
    items: list[dict] = []

    _EVENT_LANE: dict[MCSEventType, str] = {
        MCSEventType.PLAN_RECEIVED: "bot",
        MCSEventType.PLAN_FINISHED: "bot",
        MCSEventType.STEP_TRIGGERED: "bot",
        MCSEventType.STEP_FINISHED: "bot",
        MCSEventType.KNOWLEDGE_SEARCH: "tool",
        MCSEventType.DIALOG_TRACING: "bot",
        MCSEventType.DIALOG_REDIRECT: "bot",
        MCSEventType.ERROR: "error",
    }

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
                    "lane": "user",
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
                    "lane": "bot",
                }
            )
            continue

        # Keep high-value telemetry items as system cards between chat turns.
        if ev.event_type in _EVENT_LANE:
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
                    "lane": _EVENT_LANE[ev.event_type],
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

    answer_not_found = sum(
        1
        for e in timeline.events
        if e.event_type == MCSEventType.KNOWLEDGE_SEARCH
        and e.search_trace
        and (e.search_trace.completion_state or "").lower() == "answernotfoundinsearchresults"
    )
    query_rewrites = sum(
        1
        for e in timeline.events
        if e.event_type == MCSEventType.KNOWLEDGE_SEARCH and e.search_trace and e.search_trace.rewritten_question
    )
    if answer_not_found:
        highlights.append({"title": "Answer Not Found", "value": str(answer_not_found), "tone": "bad"})
    if query_rewrites:
        highlights.append({"title": "Query Rewrites", "value": str(query_rewrites), "tone": "info"})

    return {
        "kpis": kpis,
        "event_mix": event_mix,
        "latency_bands": latency_bands,
        "highlights": highlights,
    }


def build_conversation_deep_dive_cards(
    profile: MCSBotProfile | None,
    timeline: MCSConversationTimeline,
) -> list[dict]:
    instructions = ""
    if profile and profile.gpt_info and profile.gpt_info.instructions:
        instructions = profile.gpt_info.instructions.strip()
    instruction_terms = _tokenize_terms(instructions)

    turns = _build_turn_journey(timeline)
    if not turns:
        return []

    search_events = [e for e in timeline.events if e.event_type == MCSEventType.KNOWLEDGE_SEARCH]
    search_idx = 0
    cards: list[dict] = []

    for turn in turns:
        query_count = len(turn.get("search_queries", []))
        searches: list[dict] = []
        for _ in range(query_count):
            if search_idx >= len(search_events):
                break
            ev = search_events[search_idx]
            search_idx += 1
            trace = ev.search_trace
            if trace is None:
                continue

            trace_terms = _tokenize_terms(
                " ".join(
                    part
                    for part in [
                        trace.rewritten_question or ev.search_query or "",
                        trace.rewritten_keywords or "",
                        trace.hypothetical_snippet or "",
                    ]
                    if part
                )
            )
            overlap = sorted(trace_terms & instruction_terms)
            overlap_pct = round((len(overlap) / len(trace_terms)) * 100) if trace_terms and instruction_terms else 0
            if not instructions:
                overlap_label = "Unavailable"
            elif overlap_pct >= 35:
                overlap_label = "Strong"
            elif overlap_pct >= 15:
                overlap_label = "Partial"
            else:
                overlap_label = "Weak"

            completion_state = trace.completion_state or trace.gpt_answer_state or "Unknown"
            state_low = completion_state.lower().replace(" ", "")
            if "answernotfound" in state_low:
                signal_tone = "bad"
                signal_label = "Answer not found in verified search results"
            elif trace.verified_result_count > 0:
                signal_tone = "good"
                signal_label = "Verified search results returned"
            elif trace.result_count > 0:
                signal_tone = "warn"
                signal_label = "Only raw search hits returned"
            else:
                signal_tone = "warn"
                signal_label = "Search executed with no visible hits"

            source_mix = _result_source_mix_counts(trace.result_sources, trace.top_results)

            searches.append(
                {
                    "index": len(searches) + 1,
                    "query": ev.search_query or trace.rewritten_question or "—",
                    "rewritten_question": trace.rewritten_question or "—",
                    "keywords": trace.rewritten_keywords or "—",
                    "snippet": trace.hypothetical_snippet or "—",
                    "completion_state": completion_state,
                    "signal_tone": signal_tone,
                    "signal_label": signal_label,
                    "endpoint_count": str(len(trace.endpoints)),
                    "endpoints": trace.endpoints,
                    "endpoints_text": "\n".join(trace.endpoints) or "No endpoints exposed in this trace.",
                    "result_count": str(trace.result_count),
                    "verified_result_count": str(trace.verified_result_count),
                    "result_summary": f"{trace.result_count} raw / {trace.verified_result_count} verified",
                    "result_sources": trace.result_sources,
                    "top_results": trace.top_results,
                    "top_results_text": "\n".join(trace.top_results) or "No raw search results recorded.",
                    "verified_top_results": trace.verified_top_results,
                    "verified_top_results_text": "\n".join(trace.verified_top_results) or "No verified results recorded.",
                    "rewrite_model": trace.rewrite_model_name or "—",
                    "rewrite_tokens": (
                        f"{trace.rewrite_prompt_tokens} in / {trace.rewrite_completion_tokens} out"
                        if trace.rewrite_prompt_tokens or trace.rewrite_completion_tokens
                        else "—"
                    ),
                    "summary_model": trace.summary_model_name or "—",
                    "summary_tokens": (
                        f"{trace.summary_prompt_tokens} in / {trace.summary_completion_tokens} out"
                        if trace.summary_prompt_tokens or trace.summary_completion_tokens
                        else "—"
                    ),
                    "summary_preview": trace.summary_preview or "—",
                    "instruction_overlap_pct": str(overlap_pct),
                    "instruction_overlap_pct_text": f"{overlap_pct}%",
                    "instruction_overlap_label": overlap_label,
                    "instruction_overlap_terms": overlap[:8],
                    "search_errors": trace.search_errors,
                    "search_errors_text": "\n".join(trace.search_errors) or "No search errors recorded.",
                    "source_names": trace.source_names,
                    "output_source_names": trace.output_source_names,
                    "source_mix_sharepoint": str(source_mix["SharePoint"]),
                    "source_mix_dataverse": str(source_mix["Dataverse"]),
                    "source_mix_website": str(source_mix["Website"]),
                    "source_mix_file": str(source_mix["File"]),
                    "source_mix_other": str(source_mix["Other"]),
                }
            )

        summary_badges: list[str] = []
        if turn.get("boosting"):
            summary_badges.append("Generative boosting")
        if turn.get("fallback"):
            summary_badges.append("Fallback")
        if query_count > 1:
            summary_badges.append("Query reformulation")
        if int(turn.get("latency_ms", 0)) >= 5000:
            summary_badges.append("Slow turn")
        if not summary_badges:
            summary_badges.append("Standard route")

        if searches:
            primary = searches[0]
            has_rewrite = primary["rewritten_question"] != "—"
            has_raw_hits = int(primary["result_count"]) > 0
            has_verified_hits = int(primary["verified_result_count"]) > 0
            answer_not_found = "answernotfound" in primary["completion_state"].lower().replace(" ", "")

            cards.append(
                {
                    "turn": turn.get("turn", 0),
                    "user": turn.get("user", "—"),
                    "topics": turn.get("topics", []),
                    "topics_text": ", ".join(turn.get("topics", [])) or "—",
                    "latency_ms": str(int(turn.get("latency_ms", 0))),
                    "latency_summary": f"{int(turn.get('latency_ms', 0))} ms | {len(searches)} search traces",
                    "search_count": str(len(searches)),
                    "searches": searches,
                    "summary_badges": summary_badges,
                    "summary_badges_text": " | ".join(summary_badges),
                    "search_status": searches[-1]["signal_label"],
                    "timeline_rewrite_scheme": "green" if has_rewrite else "gray",
                    "timeline_search_scheme": "green" if has_raw_hits else "amber",
                    "timeline_verify_scheme": "green" if has_verified_hits else "amber",
                    "timeline_answer_scheme": "red" if answer_not_found else "green",
                    "timeline_rewrite_hint": (
                        f"Query Rewriting — LLM contextualizes the question (model: {primary['rewrite_model']})"
                        if has_rewrite
                        else "Query Rewriting — not triggered for this turn"
                    ),
                    "timeline_search_hint": (
                        f"Knowledge Search — {primary['result_count']} raw results"
                        f" from {primary['endpoint_count']} endpoints"
                    ),
                    "timeline_verify_hint": (
                        f"Verification — {primary['verified_result_count']} of"
                        f" {primary['result_count']} results passed scoring"
                    ),
                    "timeline_answer_hint": f"Answer Generation — {primary['signal_label']}",
                    "query": primary["query"],
                    "rewritten_question": primary["rewritten_question"],
                    "keywords": primary["keywords"],
                    "snippet": primary["snippet"],
                    "completion_state": primary["completion_state"],
                    "signal_tone": primary["signal_tone"],
                    "signal_label": primary["signal_label"],
                    "endpoint_count": primary["endpoint_count"],
                    "endpoints_text": "\n".join(primary["endpoints"]) or "No endpoints exposed in this trace.",
                    "result_count": primary["result_count"],
                    "verified_result_count": primary["verified_result_count"],
                    "result_summary": f"{primary['result_count']} raw / {primary['verified_result_count']} verified",
                    "top_results_text": "\n".join(primary["top_results"]) or "No raw search results recorded.",
                    "verified_top_results_text": "\n".join(primary["verified_top_results"]) or "No verified results recorded.",
                    "rewrite_model": primary["rewrite_model"],
                    "rewrite_tokens": primary["rewrite_tokens"],
                    "summary_model": primary["summary_model"],
                    "summary_tokens": primary["summary_tokens"],
                    "summary_preview": primary["summary_preview"],
                    "instruction_overlap_pct": primary["instruction_overlap_pct"],
                    "instruction_overlap_pct_text": primary["instruction_overlap_pct"] + "%",
                    "instruction_overlap_label": primary["instruction_overlap_label"],
                    "instruction_overlap_terms_text": ", ".join(primary["instruction_overlap_terms"]) or "No direct lexical overlap detected.",
                    "search_errors_text": "\n".join(primary["search_errors"]) or "No search errors recorded.",
                    "source_chip_sharepoint": f"SharePoint {primary['source_mix_sharepoint']}",
                    "source_chip_dataverse": f"Dataverse {primary['source_mix_dataverse']}",
                    "source_chip_website": f"Website {primary['source_mix_website']}",
                    "source_chip_file": f"File {primary['source_mix_file']}",
                    "source_chip_other": f"Other {primary['source_mix_other']}",
                }
            )

    return cards


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
    """Render a message-only SVG chat view and turn latency table."""
    turns = _pair_message_turns(timeline)
    if not turns:
        return ""

    svg_src = _render_chat_svg(turns)
    lines: list[str] = [
        "## Message Chat Timeline",
        "",
        "```ppsvg",
        svg_src,
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


def _short_text(text: str | None, max_len: int = 96) -> str:
    raw = (text or "").strip().replace("|", "\\|")
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 1] + "…"


def _is_fallback_topic(topic: str | None) -> bool:
    low = (topic or "").lower()
    return "fallback" in low or "unknown intent" in low


def _is_generative_boosting_topic(topic: str | None) -> bool:
    low = (topic or "").lower()
    return "search" in low or "boost" in low or "conversational boosting" in low


def _build_turn_journey(timeline: MCSConversationTimeline) -> list[dict]:
    turns: list[dict] = []
    current: dict | None = None
    turn_idx = 0

    for ev in timeline.events:
        if ev.event_type == MCSEventType.USER_MESSAGE:
            if current is not None:
                turns.append(current)
            turn_idx += 1
            current = {
                "turn": turn_idx,
                "user": (ev.summary or "").replace("User: ", "", 1).strip().strip('"'),
                "topics": [],
                "search_queries": [],
                "search_results": [],
                "fallback": False,
                "boosting": False,
                "errors": [],
            }
            continue

        if current is None:
            continue

        if ev.event_type == MCSEventType.STEP_TRIGGERED:
            topic = ev.topic_name or ""
            if topic and topic not in current["topics"]:
                current["topics"].append(topic)
            if _is_fallback_topic(topic):
                current["fallback"] = True
            if _is_generative_boosting_topic(topic):
                current["boosting"] = True

        if ev.event_type == MCSEventType.KNOWLEDGE_SEARCH:
            q = (ev.search_query or "").strip()
            if q:
                current["search_queries"].append(q)
            result_count_raw = (ev.details or {}).get("result_count", "0")
            try:
                rc = int(str(result_count_raw))
            except ValueError:
                rc = 0
            current["search_results"].append(rc)

        if ev.event_type == MCSEventType.ERROR:
            current["errors"].append(ev.error or ev.summary or "Error")

    if current is not None:
        turns.append(current)

    # Attach measured turn latency where available.
    pair_turns = _pair_message_turns(timeline)
    for idx, rec in enumerate(turns):
        rec["latency_ms"] = int(pair_turns[idx]["latency_ms"]) if idx < len(pair_turns) else 0

    return turns


def render_turn_journey_analysis(timeline: MCSConversationTimeline) -> str:
    turns = _build_turn_journey(timeline)
    if not turns:
        return ""

    lines: list[str] = [
        "## Turn-by-Turn Search & Routing Journey",
        "",
        "| Turn | User Ask | Triggered Topics | KB Search Query Evolution | KB Result Signal | Latency | Signals |",
        "| ---: | --- | --- | --- | --- | ---: | --- |",
    ]

    for t in turns:
        user = _short_text(t.get("user", ""), 70) or "—"
        topics = t.get("topics", [])
        topics_txt = ", ".join(_short_text(x, 28) for x in topics[:3]) if topics else "—"

        queries = t.get("search_queries", [])
        if queries:
            unique_queries: list[str] = []
            for q in queries:
                if q not in unique_queries:
                    unique_queries.append(q)
            if len(unique_queries) == 1:
                query_txt = _short_text(unique_queries[0], 80)
            else:
                first_q = _short_text(unique_queries[0], 42)
                last_q = _short_text(unique_queries[-1], 42)
                query_txt = f"{first_q} → {last_q}"
        else:
            query_txt = "—"

        results = t.get("search_results", [])
        if not results:
            result_signal = "No KB search"
        elif max(results) == 0:
            result_signal = "No usable KB result ❌"
        else:
            result_signal = f"Best KB hit count: {max(results)}"

        latency = int(t.get("latency_ms", 0))
        signals: list[str] = []
        if t.get("fallback"):
            signals.append("Fallback triggered")
        if t.get("boosting"):
            signals.append("Generative boosting invoked")
        if len(queries) > 1:
            signals.append("Query reformulated")
        if latency >= 8000:
            signals.append("Slow turn")
        if t.get("errors"):
            signals.append("Error seen")
        signal_txt = " · ".join(signals) if signals else "—"

        lines.append(
            f"| {t.get('turn', 0)} | {user} | {topics_txt} | {query_txt} | {result_signal} | {latency} ms | {signal_txt} |"
        )

    lines += ["", "### Query Reformulation Notes", ""]
    reformulated = [t for t in turns if len(set(t.get("search_queries", []))) > 1]
    if reformulated:
        for t in reformulated:
            uq = []
            for q in t.get("search_queries", []):
                if q not in uq:
                    uq.append(q)
            lines.append(
                f"- Turn {t['turn']}: query changed from \"{_short_text(uq[0], 110)}\" "
                f"to \"{_short_text(uq[-1], 110)}\" after planner/tool routing."
            )
    else:
        lines.append("- No explicit query reformulation detected between search attempts.")

    lines.append("")
    return "\n".join(lines)


def render_search_trace_deep_dive(profile: MCSBotProfile | None, timeline: MCSConversationTimeline) -> str:
    cards = build_conversation_deep_dive_cards(profile, timeline)
    if not cards:
        return ""

    lines: list[str] = [
        "## Generative Search Deep Dive",
        "",
        "This section appears only when the conversation contains planner or boosting search traces.",
        "",
    ]

    for card in cards:
        if not card["searches"]:
            continue
        lines += [f"### Turn {card['turn']} — {_short_text(card['user'], 90)}", ""]
        lines.append(f"- Route signals: {'; '.join(card['summary_badges'])}")
        lines.append(f"- Triggered topics: {', '.join(card['topics']) if card['topics'] else '—'}")
        lines.append(f"- Latency: {card['latency_ms']} ms")
        for search in card["searches"]:
            lines += [
                f"- Search {search['index']}: {search['signal_label']}",
                f"  Query: {search['query']}",
                f"  Keywords: {search['keywords']}",
                f"  Endpoints: {search['endpoint_count']}",
                f"  Results: {search['result_count']} raw / {search['verified_result_count']} verified",
                f"  Completion state: {search['completion_state']}",
                f"  Instruction lexical overlap: {search['instruction_overlap_pct']}% ({search['instruction_overlap_label']})",
            ]
        lines.append("")

    return "\n".join(lines)


def render_latency_bottlenecks(timeline: MCSConversationTimeline) -> str:
    turns = _build_turn_journey(timeline)
    if not turns:
        return ""

    slow_turns = [t for t in turns if int(t.get("latency_ms", 0)) >= 5000]
    lines: list[str] = [
        "## Latency Bottlenecks",
        "",
        f"Detected **{len(slow_turns)}** slow turn(s) (>= 5000 ms).",
        "",
    ]

    if not slow_turns:
        lines += ["- No significant latency bottlenecks detected.", ""]
        return "\n".join(lines)

    lines += [
        "| Turn | Latency | Likely Contributors |",
        "| ---: | ---: | --- |",
    ]
    for t in slow_turns:
        contributors: list[str] = []
        search_count = len(t.get("search_queries", []))
        if search_count > 1:
            contributors.append(f"Multiple KB searches ({search_count})")
        if t.get("fallback"):
            contributors.append("Fallback path triggered")
        if t.get("boosting"):
            contributors.append("Generative boosting route")
        if t.get("search_results") and max(t.get("search_results", [0])) == 0:
            contributors.append("No usable KB results")
        if t.get("errors"):
            contributors.append("Error telemetry present")
        if not contributors:
            contributors.append("General orchestration/tool latency")
        lines.append(f"| {t['turn']} | {int(t.get('latency_ms', 0))} ms | {'; '.join(contributors)} |")

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
# Dynamic Planner trace analysis renderer
# ---------------------------------------------------------------------------

# Import the term-extraction helper from the analysis module so explanation
# strings are computed from the same normalisation logic as the scores.
from toolkit.mcs.planner_analysis import _extract_terms as _planner_extract_terms  # noqa: E402


def _compact_tool_id(tool_id: str) -> str:
    """Shorten 'P:UniversalSearchTool' → 'UniversalSearchTool'."""
    if not tool_id:
        return "Unknown Tool"
    return tool_id.split(":", 1)[1] if ":" in tool_id else tool_id


def _relevance_icon(score: float) -> str:
    """Return a coloured circle icon for a relevance score."""
    if score >= 0.5:
        return "🟢"
    if score >= 0.1:
        return "🟡"
    return "🔴"


def _overall_quality_label(step) -> str:
    if "HIGH_QUALITY" in step.score_flags:
        return "Good ✅"
    if "PARTIAL_QUALITY" in step.score_flags:
        return "Partial ⚠️"
    return "Poor ❌"


def _flag_labels(step) -> list[str]:
    """Convert raw score_flags to human-readable labels for display."""
    mapping = {
        "TOP_RESULT_RELEVANT": "Top result is relevant ✅",
        "NO_RESULTS": "No results returned ❌",
        "SOURCES_FILTERED": "Some sources produced no results ⚠️",
        "ALL_SOURCES_RETURNED": "All sources returned results ✅",
        "HIGH_QUALITY": "High retrieval quality ✅",
        "PARTIAL_QUALITY": "Partial retrieval quality ⚠️",
        "LOW_QUALITY": "Low retrieval quality ❌",
    }
    return [mapping[f] for f in step.score_flags if f in mapping]


def render_planner_analysis(timeline: MCSConversationTimeline) -> str:
    """Render the Dynamic Planner Trace Analysis section.

    Shows, per planner step:
    - User ask (verbatim from DynamicPlanReceivedDebug)
    - Planner reasoning thought (from DynamicPlanStepTriggered)
    - Generated search payload (query, keywords, summarisation flag)
    - Knowledge source routing (candidate vs output)
    - Retrieved documents table with per-item relevance scores
    - Quality scorecard (query fidelity, item hit rate, source coverage, overall)
    """
    analysis = timeline.planner_analysis
    if not analysis or not analysis.has_planner_events or not analysis.steps:
        return ""

    lines: list[str] = [
        "## Dynamic Planner Trace Analysis",
        "",
        "> Detailed breakdown of how the generative AI planner interpreted the user request, "
        "generated search queries, routed knowledge sources, and the relevance of retrieved results.",
        "",
    ]

    for i, step in enumerate(analysis.steps, 1):
        tool_short = _compact_tool_id(step.tool_id)
        lines += [
            f"### Step {i} of {analysis.step_count} — {tool_short}",
            "",
        ]

        # ── User ask ──────────────────────────────────────────────────────────
        if step.user_ask:
            lines += [
                "**User Ask**",
                "",
                f"> {step.user_ask}",
                "",
            ]

        # ── Planner reasoning ─────────────────────────────────────────────────
        if step.planner_thought:
            lines += [
                "**Planner Reasoning**",
                "",
                f"> {step.planner_thought}",
                "",
            ]

        # ── Generated search payload ──────────────────────────────────────────
        if step.search_query or step.search_keywords:
            lines += [
                "**Generated Search Payload**",
                "",
                "| Field | Value |",
                "| --- | --- |",
            ]
            if step.search_query:
                lines.append(f"| Search Query | {step.search_query} |")
            if step.search_keywords:
                lines.append(f"| Keywords | {step.search_keywords} |")
            lines.append(f"| Summarisation | {'On' if step.enable_summarization else 'Off'} |")
            lines.append("")

        # ── Knowledge source routing ──────────────────────────────────────────
        if step.knowledge_sources_candidate:
            lines += [
                "**Knowledge Source Routing**",
                "",
                "| # | Source | Outcome |",
                "| --- | --- | --- |",
            ]
            output_set = set(step.knowledge_sources_output)
            for j, src in enumerate(step.knowledge_sources_candidate, 1):
                src_short = src.split(".")[-1] if "." in src else src
                outcome = "✅ Returned results" if src in output_set else "⚫ Filtered / no results"
                lines.append(f"| {j} | `{src_short}` | {outcome} |")
            lines.append("")

        # ── Retrieved documents ───────────────────────────────────────────────
        exec_ms = f"{step.execution_time_ms:.0f}" if step.execution_time_ms else "—"
        result_count = len(step.result_items)

        if "NO_RESULTS" in step.score_flags:
            lines += [
                f"**Retrieved Documents** — 0 results (execution: {exec_ms} ms)",
                "",
                "_No documents were returned by the knowledge search._",
                "",
            ]
        elif step.result_items:
            lines += [
                f"**Retrieved Documents** — {result_count} result{'s' if result_count != 1 else ''}"
                f" (execution: {exec_ms} ms)",
                "",
                "| # | Document | Type | Relevance |",
                "| --- | --- | --- | --- |",
            ]
            for j, item in enumerate(step.result_items, 1):
                doc_name = (item.name or "—")[:90].replace("|", "\\|")
                file_type = item.file_type or "—"
                icon = _relevance_icon(item.relevance_score)
                lines.append(f"| {j} | {doc_name} | {file_type} | {icon} {item.relevance_score:.2f} |")
            lines.append("")

        # ── Quality scorecard ─────────────────────────────────────────────────
        src_cand = len(step.knowledge_sources_candidate)
        src_out = len(step.knowledge_sources_output)
        src_detail = (
            f"{src_out} of {src_cand} candidate sources returned results"
            if src_cand
            else "No knowledge sources specified"
        )
        ask_detail = (
            f"{step.query_matched_term_count} of {step.ask_term_count} ask-terms reflected in generated query"
            if step.ask_term_count
            else "No ask terms to evaluate"
        )
        lines += [
            "**Retrieval Quality Scorecard**",
            "",
            "| Metric | Score | Detail |",
            "| --- | ---: | --- |",
            f"| Query Generation Fidelity | {step.query_fidelity_pct:.1f}% | {ask_detail} |",
            f"| Item Relevance Rate | {step.item_hit_rate_pct:.1f}% | "
            f"{step.matched_item_count} of {result_count} returned documents match ask terms |",
            f"| Source Coverage | {step.source_fidelity_pct:.1f}% | {src_detail} |",
            f"| **Overall Retrieval Quality** | **{step.overall_success_pct:.1f}%** | "
            f"{_overall_quality_label(step)} |",
            "",
        ]

        # ── Score flags ───────────────────────────────────────────────────────
        labels = _flag_labels(step)
        if labels:
            lines += [f"**Signals:** {' · '.join(labels)}", ""]

        # ── Search errors ─────────────────────────────────────────────────────
        if step.search_errors:
            lines += ["**Search Errors**", ""]
            for err in step.search_errors:
                lines.append(f"- {err}")
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
            render_turn_journey_analysis(timeline),
            render_search_trace_deep_dive(profile, timeline),
            render_tool_diagnostics(timeline),
            render_latency_bottlenecks(timeline),
            render_planner_analysis(timeline),
            render_conversation_findings(timeline),
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
            render_turn_journey_analysis(timeline),
            render_search_trace_deep_dive(profile, timeline),
            render_tool_diagnostics(timeline),
            render_latency_bottlenecks(timeline),
            render_planner_analysis(timeline),
            render_conversation_findings(timeline),
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
            render_turn_journey_analysis(timeline),
            render_search_trace_deep_dive(None, timeline),
            render_message_chat_timeline(timeline),
            render_tool_diagnostics(timeline),
            render_planner_analysis(timeline),
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
