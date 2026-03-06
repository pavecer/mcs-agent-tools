"""Visualizer — parse a Power Platform solution ZIP and generate a Markdown +
Mermaid report of the agent structure.

Reads botcomponent XML + YAML data files from the standard PP solution export
format (bots/{schema}/configuration.json + botcomponents/{schema}.{type}/).
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import defusedxml.ElementTree as ET
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field

try:
    import yaml as _yaml

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False

from loguru import logger
from renamer import safe_extractall


# ── Pydantic models ────────────────────────────────────────────────────────────


class ComponentSummary(BaseModel):
    kind: str
    display_name: str
    schema_name: str
    state: str = "Active"
    trigger_kind: str | None = None
    dialog_kind: str | None = None
    action_kind: str | None = None
    description: str | None = None


class GptInfo(BaseModel):
    display_name: str = ""
    model_hint: str | None = None
    web_browsing: bool = False
    instructions: str | None = None


class TopicConnection(BaseModel):
    source_display: str
    target_display: str
    condition: str | None = None


class BotProfile(BaseModel):
    schema_name: str = ""
    display_name: str = ""
    channels: list[str] = Field(default_factory=list)
    recognizer_kind: str = "Unknown"
    use_model_knowledge: bool = False
    components: list[ComponentSummary] = Field(default_factory=list)
    gpt_info: GptInfo | None = None
    topic_connections: list[TopicConnection] = Field(default_factory=list)


# ── YAML sanitisation ──────────────────────────────────────────────────────────


def _sanitize_yaml(text: str) -> str:
    """Fix common quirks in Power Platform YAML exports."""
    text = text.replace("\t", "    ")
    # Quote bare keys starting with @ (e.g. `@odata.type: …`)
    text = re.sub(r"^(\s*)(@[a-zA-Z0-9_.]+)(\s*:)", r'\1"\2"\3', text, flags=re.MULTILINE)
    # Quote bare values starting with @
    text = re.sub(
        r"(:\s+)(@[^\n]+)$",
        lambda m: m.group(1) + '"' + m.group(2) + '"',
        text,
        flags=re.MULTILINE,
    )
    return text


# ── Helpers ────────────────────────────────────────────────────────────────────


def _parse_xml_fields(xml_path: Path, *tags: str) -> dict[str, str]:
    """Return a dict of {tag: text} for the given XML file."""
    try:
        root = ET.parse(xml_path).getroot()
        return {tag: root.findtext(tag) or "" for tag in tags}
    except Exception:
        return {tag: "" for tag in tags}


def _load_data_yaml(data_path: Path) -> dict:
    """Load a YAML 'data' file, returning an empty dict on any failure."""
    if not data_path.exists():
        return {}
    try:
        raw = data_path.read_text(encoding="utf-8", errors="replace")
        result = _yaml.safe_load(_sanitize_yaml(raw))  # type: ignore[union-attr]
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


# ── Parser ─────────────────────────────────────────────────────────────────────


def parse_solution_zip(work_dir: Path) -> BotProfile:
    """Parse an extracted Power Platform solution ZIP directory."""
    if not _YAML_AVAILABLE:  # pragma: no cover
        raise RuntimeError("pyyaml is required for visualization. Run: uv add pyyaml")

    # 1. Find schema from bots/ folder name
    bots_dir = work_dir / "bots"
    if not bots_dir.exists():
        raise ValueError("No 'bots/' directory found in the solution ZIP.")
    bot_folders = [d for d in bots_dir.iterdir() if d.is_dir()]
    if not bot_folders:
        raise ValueError("No bot folder found inside 'bots/'.")
    if len(bot_folders) > 1:
        logger.warning(
            f"Multiple bot folders found; using '{bot_folders[0].name}'. Others: {[d.name for d in bot_folders[1:]]}"
        )
    schema = bot_folders[0].name

    # 2. Read bots/{schema}/configuration.json
    channels: list[str] = []
    use_model_knowledge = False
    recognizer_kind = "Unknown"
    web_browsing = False

    config_path = bots_dir / schema / "configuration.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            channels_raw = config.get("channels", []) or []
            channels = [ch.get("channelId", "") for ch in channels_raw if isinstance(ch, dict)]
            ai_raw = config.get("aISettings", {}) or {}
            use_model_knowledge = bool(ai_raw.get("useModelKnowledge", False))
            recognizer = config.get("recognizer", {}) or {}
            recognizer_kind = recognizer.get("$kind", "Unknown")
            for _key, sv in (config.get("settings") or {}).items():
                if isinstance(sv, dict) and (sv.get("capabilities") or {}).get("webBrowsing"):
                    web_browsing = True
                    break
        except Exception:  # nosec B110 – intentionally skip malformed bot config
            pass

    # 3. Parse GPT component (botcomponents/{schema}.gpt.default/)
    botcomponents_dir = work_dir / "botcomponents"
    gpt_info: GptInfo | None = None
    display_name = schema

    gpt_dir = botcomponents_dir / f"{schema}.gpt.default"
    if gpt_dir.exists():
        xml_fields = _parse_xml_fields(gpt_dir / "botcomponent.xml", "name", "description")
        display_name = xml_fields.get("name") or schema
        gpt_data = _load_data_yaml(gpt_dir / "data")
        model = (gpt_data.get("aISettings") or {}).get("model") or {}
        gpt_info = GptInfo(
            display_name=display_name,
            model_hint=model.get("modelNameHint"),
            web_browsing=web_browsing,
            instructions=gpt_data.get("instructions"),
        )

    # 4. Parse topic / file / entity components
    components: list[ComponentSummary] = []
    schema_to_display: dict[str, str] = {}
    topic_action_map: dict[str, list] = {}  # folder_name -> beginDialog.actions

    if botcomponents_dir.exists():
        for comp_dir in sorted(botcomponents_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            folder_name = comp_dir.name
            # skip system mspva_ components and the gpt.default we already handled
            if folder_name.startswith("mspva_") or folder_name == f"{schema}.gpt.default":
                continue
            # only process components belonging to this bot schema
            parts = folder_name.split(".", 2)
            if len(parts) < 2 or parts[0] != schema:
                continue
            comp_kind = parts[1]

            xml_path = comp_dir / "botcomponent.xml"
            if not xml_path.exists():
                continue
            xml_fields = _parse_xml_fields(xml_path, "name", "description", "statecode")
            name = xml_fields.get("name") or folder_name
            description = xml_fields.get("description") or None
            state = "Active" if xml_fields.get("statecode", "0") == "0" else "Inactive"

            trigger_kind: str | None = None
            dialog_kind: str | None = None

            if comp_kind == "topic":
                topic_data = _load_data_yaml(comp_dir / "data")
                dialog_kind = topic_data.get("kind")  # e.g. "AdaptiveDialog"
                begin = topic_data.get("beginDialog") or {}
                trigger_kind = begin.get("kind")
                topic_action_map[folder_name] = begin.get("actions") or []

            components.append(
                ComponentSummary(
                    kind=comp_kind,
                    display_name=name,
                    schema_name=folder_name,
                    state=state,
                    trigger_kind=trigger_kind,
                    dialog_kind=dialog_kind,
                    description=description,
                )
            )
            schema_to_display[folder_name] = name

    # 5. Extract topic-to-topic connections
    topic_connections = _extract_topic_connections(topic_action_map, schema_to_display)

    return BotProfile(
        schema_name=schema,
        display_name=display_name,
        channels=channels,
        recognizer_kind=recognizer_kind,
        use_model_knowledge=use_model_knowledge,
        components=components,
        gpt_info=gpt_info,
        topic_connections=topic_connections,
    )


def _extract_topic_connections(
    topic_action_map: dict[str, list],
    schema_to_display: dict[str, str],
) -> list[TopicConnection]:
    connections: list[TopicConnection] = []
    for comp_schema, actions in topic_action_map.items():
        source_display = schema_to_display.get(comp_schema, comp_schema.split(".")[-1])
        connections.extend(_walk_actions(actions, source_display, schema_to_display))
    return connections


def _walk_actions(
    actions: list,
    source_display: str,
    schema_to_display: dict[str, str],
    condition: str | None = None,
) -> list[TopicConnection]:
    connections: list[TopicConnection] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        kind = action.get("kind", "")

        if kind == "BeginDialog":
            target_schema = action.get("dialog", "")
            if target_schema:
                target_display = schema_to_display.get(target_schema, "")
                if not target_display:
                    parts = target_schema.split(".")
                    target_display = parts[-1] if len(parts) >= 2 else target_schema
                connections.append(
                    TopicConnection(
                        source_display=source_display,
                        target_display=target_display,
                        condition=condition,
                    )
                )

        elif kind == "ConditionGroup":
            for cond in action.get("conditions", []) or []:
                if isinstance(cond, dict):
                    connections.extend(
                        _walk_actions(
                            cond.get("actions", []) or [],
                            source_display,
                            schema_to_display,
                            condition=cond.get("condition"),
                        )
                    )
            connections.extend(
                _walk_actions(
                    action.get("elseActions", []) or [],
                    source_display,
                    schema_to_display,
                    condition="else",
                )
            )

        if kind != "ConditionGroup":
            for key in ("actions", "elseActions"):
                nested = action.get(key)
                if isinstance(nested, list):
                    connections.extend(_walk_actions(nested, source_display, schema_to_display, condition))
    return connections


# ── Mermaid helpers ────────────────────────────────────────────────────────────

_MERMAID_SUBS: list[tuple[str, str]] = [
    ("→", "to"),
    ("—", "-"),
    ("✓", "OK"),
    ("✗", "FAIL"),
    ("⚠", "WARN"),
    ("\n", " "),
    ("\r", ""),
    ('"', ""),
    ("'", ""),
    ("%", "pct"),
    ("#", ""),
    (";", ","),
    (":", " -"),
    ("[", ""),
    ("]", ""),
    ("(", ""),
    (")", ""),
    ("{", ""),
    ("}", ""),
    ("|", ""),
    ("<", ""),
    (">", ""),
    ("\xa0", " "),
]


def _sanitize_mermaid(text: str) -> str:
    for src, dst in _MERMAID_SUBS:
        text = text.replace(src, dst)
    return text[:80]


def _make_node_id(name: str) -> str:
    clean = "".join(c for c in name if c.isalnum() or c == "_")
    return clean or "Unknown"


# ── Component classification ─────────────────────────────────────────────────

_SYSTEM_TRIGGERS: set[str] = {
    "OnSystemRedirect",
    "OnError",
    "OnEscalate",
    "OnSignIn",
    "OnUnknownIntent",
    "OnConversationStart",
    "OnSelectIntent",
    "OnInactivity",
}
_AUTOMATION_TRIGGERS: set[str] = {"OnRedirect", "OnActivity"}

_CAT_ORDER = [
    "user_topics",
    "orchestrator_topics",
    "system_topics",
    "automation_topics",
    "knowledge",
    "skills",
    "custom_entities",
    "variables",
    "settings",
]
_CAT_LABELS: dict[str, str] = {
    "user_topics": "User Topics",
    "orchestrator_topics": "Orchestrator Topics",
    "system_topics": "System Topics",
    "automation_topics": "Automation Topics",
    "knowledge": "Knowledge",
    "skills": "Skills & Connectors",
    "custom_entities": "Custom Entities",
    "variables": "Variables",
    "settings": "Settings",
}


def _classify(comp: ComponentSummary) -> str | None:
    if comp.kind in ("gpt", "GptComponent"):
        return None
    if comp.kind in ("topic", "DialogComponent"):
        if comp.dialog_kind in ("TaskDialog", "AgentDialog"):
            return "orchestrator_topics"
        trigger = comp.trigger_kind or ""
        if trigger in _SYSTEM_TRIGGERS:
            return "system_topics"
        if trigger in _AUTOMATION_TRIGGERS:
            return "automation_topics"
        return "user_topics"
    if comp.kind in ("file", "FileAttachmentComponent", "KnowledgeSourceComponent"):
        return "knowledge"
    if comp.kind == "SkillComponent":
        return "skills"
    if comp.kind in ("entity", "CustomEntityComponent"):
        return "custom_entities"
    if comp.kind == "GlobalVariableComponent":
        return "variables"
    return "settings"


# ── Report sections ────────────────────────────────────────────────────────────


def _render_ai_config(profile: BotProfile) -> str:
    if not profile.gpt_info:
        return ""
    g = profile.gpt_info
    lines = ["## AI Configuration\n", "| Property | Value |", "| --- | --- |"]
    if g.model_hint:
        lines.append(f"| Model | {g.model_hint} |")
    lines.append(f"| Web Browsing | {'Yes' if g.web_browsing else 'No'} |")
    lines.append(f"| Use Model Knowledge | {'Yes' if profile.use_model_knowledge else 'No'} |")
    lines.append("")
    if g.instructions:
        snippet = g.instructions[:500] + ("…" if len(g.instructions) > 500 else "")
        lines.append(f"**System Instructions** ({len(g.instructions)} chars):\n")
        lines.append(f"```\n{snippet}\n```")
        lines.append("")
    return "\n".join(lines)


def _render_profile(profile: BotProfile) -> str:
    lines = [
        "## Agent Profile\n",
        "| Property | Value |",
        "| --- | --- |",
        f"| Schema Name | `{profile.schema_name}` |",
        f"| Channels | {', '.join(c for c in profile.channels if c) or 'None configured'} |",
        f"| Recognizer | {profile.recognizer_kind} |",
        "",
    ]
    return "\n".join(lines)


def _render_components(profile: BotProfile) -> str:
    by_cat: dict[str, list[ComponentSummary]] = {}
    for comp in profile.components:
        cat = _classify(comp)
        if cat is not None:
            by_cat.setdefault(cat, []).append(comp)

    total = sum(len(v) for v in by_cat.values())
    active = sum(1 for v in by_cat.values() for c in v if c.state == "Active")

    lines = [
        "## Components\n",
        f"**{total}** total — **{active}** active, **{total - active}** inactive\n",
        "| Category | Count | Active | Inactive |",
        "| --- | --- | --- | --- |",
    ]
    for cat in _CAT_ORDER:
        comps = by_cat.get(cat)
        if comps:
            act = sum(1 for c in comps if c.state == "Active")
            lines.append(f"| {_CAT_LABELS[cat]} | {len(comps)} | {act} | {len(comps) - act} |")
    lines.append("")

    for cat in _CAT_ORDER:
        comps = by_cat.get(cat)
        if not comps:
            continue
        lines.append(f"### {_CAT_LABELS[cat]} ({len(comps)})\n")
        lines.append("| Name | Schema | State |")
        lines.append("| --- | --- | --- |")
        for c in comps:
            lines.append(f"| {c.display_name} | `{c.schema_name}` | {c.state} |")
        lines.append("")

    return "\n".join(lines)


def _render_topic_graph(profile: BotProfile) -> str:
    if not profile.topic_connections:
        return ""

    nodes: dict[str, str] = {}
    edges: list[tuple[str, str, str | None]] = []
    seen_edges: dict[tuple[str, str], int] = {}

    for conn in profile.topic_connections:
        src_id = _make_node_id(conn.source_display)
        tgt_id = _make_node_id(conn.target_display)
        nodes[src_id] = conn.source_display
        nodes[tgt_id] = conn.target_display

        edge_key = (src_id, tgt_id)
        if edge_key not in seen_edges:
            seen_edges[edge_key] = 1
            edges.append((src_id, tgt_id, conn.condition))
        else:
            seen_edges[edge_key] += 1
            for i, (s, t, _c) in enumerate(edges):
                if s == src_id and t == tgt_id:
                    edges[i] = (s, t, None)
                    break

    # Cap to 80 most-connected nodes to avoid huge diagrams
    if len(nodes) > 80:
        counts: dict[str, int] = {nid: 0 for nid in nodes}
        for s, t, _ in edges:
            counts[s] = counts.get(s, 0) + 1
            counts[t] = counts.get(t, 0) + 1
        keep = set(sorted(counts, key=lambda n: counts[n], reverse=True)[:80])
        nodes = {nid: d for nid, d in nodes.items() if nid in keep}
        edges = [(s, t, c) for s, t, c in edges if s in keep and t in keep]

    lines = [
        "## Topic Connection Graph\n",
        "```mermaid",
        '%%{init: {"useMaxWidth": false}}%%',
        "graph TD",
    ]
    for nid, display in sorted(nodes.items()):
        lines.append(f"    {nid}[{_sanitize_mermaid(display)}]")

    for src, tgt, condition in edges:
        if condition:
            cond_label = _sanitize_mermaid(condition)
            lines.append(f"    {src} -->|{cond_label}| {tgt}")
        else:
            lines.append(f"    {src} --> {tgt}")

    lines.extend(["```", ""])
    return "\n".join(lines)


# ── Report assembler ───────────────────────────────────────────────────────────


def generate_markdown_report(profile: BotProfile) -> str:
    """Render a full Markdown + Mermaid report for the BotProfile."""
    sections = [f"# {profile.display_name}\n"]

    ai_section = _render_ai_config(profile)
    if ai_section:
        sections.append(ai_section)

    sections.append(_render_profile(profile))
    sections.append(_render_components(profile))

    graph = _render_topic_graph(profile)
    if graph:
        sections.append(graph)

    return "\n".join(sections)


# ── Segment splitter ───────────────────────────────────────────────────────────


def split_segments(md: str) -> list[dict]:
    """Split markdown into alternating {'type': 'markdown'|'mermaid', 'content': …} dicts."""
    pattern = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
    segments: list[dict] = []
    last_end = 0

    for match in pattern.finditer(md):
        before = md[last_end : match.start()]
        if before.strip():
            segments.append({"type": "markdown", "content": before.strip()})
        segments.append({"type": "mermaid", "content": match.group(1).strip()})
        last_end = match.end()

    after = md[last_end:]
    if after.strip():
        segments.append({"type": "markdown", "content": after.strip()})

    return segments


# ── Public API ─────────────────────────────────────────────────────────────────


def visualize_zip_bytes(zip_bytes: bytes) -> list[dict]:
    """Parse a solution ZIP and return render segments for the web UI.

    Returns a list of ``{'type': 'markdown'|'mermaid', 'content': str}`` dicts.
    Raises ``ValueError`` or ``RuntimeError`` on failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, tmp)
        profile = parse_solution_zip(tmp)

    md = generate_markdown_report(profile)
    return split_segments(md)
