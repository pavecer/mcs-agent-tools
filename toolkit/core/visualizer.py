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
from toolkit.core.renamer import safe_extractall
from toolkit.core.yaml_utils import sanitize_yaml


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


# ── Evaluation / test models ───────────────────────────────────────────────────


class EvalDataRow(BaseModel):
    input: str = ""
    expected_output: str = ""
    keywords: list[str] = Field(default_factory=list)
    source: str = "Manual"


class EvalSet(BaseModel):
    schema_name: str = ""
    display_name: str = ""
    graders: list[str] = Field(default_factory=list)
    rows: list[EvalDataRow] = Field(default_factory=list)


class TestCase(BaseModel):
    schema_name: str = ""
    input: str = ""
    expected_response: str = ""
    score_threshold: int = 70
    origin_type: str = "Imported"


class TestSet(BaseModel):
    schema_name: str = ""
    display_name: str = ""
    test_cases: list[TestCase] = Field(default_factory=list)


class EvalsProfile(BaseModel):
    test_sets: list[TestSet] = Field(default_factory=list)
    eval_sets: list[EvalSet] = Field(default_factory=list)


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
        result = _yaml.safe_load(sanitize_yaml(raw))  # type: ignore[union-attr]
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _get_parent_schema(xml_path: Path) -> str:
    """Return the parentbotcomponentid/schemaname value from a botcomponent.xml, or ''."""
    try:
        root = ET.parse(xml_path).getroot()
        parent_el = root.find("parentbotcomponentid")
        if parent_el is not None:
            sn = parent_el.find("schemaname")
            if sn is not None and sn.text:
                return sn.text
    except Exception:
        pass
    return ""


# ── Evaluation / test parser ───────────────────────────────────────────────────


def parse_evals_zip(work_dir: Path) -> EvalsProfile:
    """Parse TestSetDefinition, TestCaseDefinition, EvaluationSet, and EvaluationData
    components from an extracted Power Platform solution directory.
    """
    if not _YAML_AVAILABLE:  # pragma: no cover
        raise RuntimeError("pyyaml is required for visualization. Run: uv add pyyaml")

    botcomponents_dir = work_dir / "botcomponents"
    if not botcomponents_dir.exists():
        return EvalsProfile()

    # Pass 1: collect metadata for all mspva_ components
    comp_kinds: dict[str, str] = {}
    comp_names: dict[str, str] = {}
    comp_parents: dict[str, str] = {}
    comp_data: dict[str, dict] = {}

    for comp_dir in sorted(botcomponents_dir.iterdir()):
        if not comp_dir.is_dir():
            continue
        folder = comp_dir.name
        if not folder.startswith("mspva_"):
            continue
        xml_path = comp_dir / "botcomponent.xml"
        data_path = comp_dir / "data"

        if xml_path.exists():
            fields = _parse_xml_fields(xml_path, "name")
            comp_names[folder] = (fields.get("name") or "").strip()
            comp_parents[folder] = _get_parent_schema(xml_path)

        if data_path.exists():
            d = _load_data_yaml(data_path)
            if isinstance(d, dict):
                comp_data[folder] = d
                comp_kinds[folder] = d.get("kind") or ""

    # Pass 2: build TestSets from TestSetDefinition components
    test_sets: dict[str, TestSet] = {}
    for schema, kind in comp_kinds.items():
        if kind == "TestSetDefinition":
            test_sets[schema] = TestSet(
                schema_name=schema,
                display_name=comp_names.get(schema) or schema,
            )

    # Pass 3: attach TestCaseDefinitions to their parent TestSet
    for schema, kind in comp_kinds.items():
        if kind != "TestCaseDefinition":
            continue
        parent = comp_parents.get(schema, "")
        if parent not in test_sets:
            parent = "__ungrouped__"
            if parent not in test_sets:
                test_sets[parent] = TestSet(schema_name=parent, display_name="Ungrouped")

        d = comp_data.get(schema, {})
        activities = (d.get("transcriptDefinition") or {}).get("testActivities") or []
        input_text = expected_response = ""
        score_threshold = 70
        origin_type = "Imported"

        for act in activities:
            if not isinstance(act, dict) or act.get("kind") != "SendUserActivity":
                continue
            input_text = (act.get("activity") or "").strip()
            origin_type = act.get("originType") or "Imported"
            for assertion in act.get("activityAssertions") or []:
                if isinstance(assertion, dict) and assertion.get("kind") == "IntentMatchAssertion":
                    expected_response = (assertion.get("expectedResponse") or "").strip()
                    try:
                        score_threshold = int(assertion.get("scoreThreshold") or 70)
                    except (TypeError, ValueError):
                        score_threshold = 70
            break  # only process first SendUserActivity

        if input_text:
            test_sets[parent].test_cases.append(
                TestCase(
                    schema_name=schema,
                    input=input_text,
                    expected_response=expected_response,
                    score_threshold=score_threshold,
                    origin_type=origin_type,
                )
            )

    # Pass 4: build EvaluationSets from EvaluationSet components
    eval_sets: dict[str, EvalSet] = {}
    for schema, kind in comp_kinds.items():
        if kind == "EvaluationSet":
            d = comp_data.get(schema, {})
            graders_raw = d.get("graders") or []
            graders = [g["kind"] for g in graders_raw if isinstance(g, dict) and g.get("kind")]
            eval_sets[schema] = EvalSet(
                schema_name=schema,
                display_name=comp_names.get(schema) or schema,
                graders=graders,
            )

    # Pass 5: attach EvaluationData rows to their parent EvaluationSet
    for schema, kind in comp_kinds.items():
        if kind != "EvaluationData":
            continue
        parent = comp_parents.get(schema, "")
        if parent not in eval_sets:
            parent = "__ungrouped_eval__"
            if parent not in eval_sets:
                eval_sets[parent] = EvalSet(schema_name=parent, display_name="Ungrouped")

        d = comp_data.get(schema, {})
        for row in d.get("rows") or []:
            if not isinstance(row, dict):
                continue
            keywords_raw = row.get("expectedKeywords") or []
            eval_sets[parent].rows.append(
                EvalDataRow(
                    input=(row.get("input") or "").strip(),
                    expected_output=(row.get("expectedOutput") or "").strip(),
                    keywords=[str(k) for k in keywords_raw if k],
                    source=row.get("source") or "Manual",
                )
            )

    return EvalsProfile(
        test_sets=[ts for ts in test_sets.values() if ts.test_cases],
        eval_sets=[es for es in eval_sets.values() if es.rows],
    )


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


def _short_trigger_label(trigger_kind: str | None) -> str:
    """Return a short human-readable label for a trigger kind."""
    if not trigger_kind:
        return "—"
    # Strip the leading 'On' prefix then insert spaces before capitals
    label = trigger_kind.removeprefix("On")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label) or trigger_kind


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
        char_count = len(g.instructions)
        lines.append(f"**System Instructions** ({char_count:,} chars):\n")
        snippet = g.instructions[:600] + ("…" if char_count > 600 else "")
        for ql in snippet.replace("\r\n", "\n").replace("\r", "\n").split("\n")[:15]:
            lines.append(f"> {ql}" if ql.strip() else ">")
        if char_count > 600:
            lines.append(">")
            lines.append(f"> *…({char_count - 600:,} more characters)*")
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
    inactive = total - active

    inactive_note = f", **{inactive}** inactive" if inactive else ""
    lines = [
        "## Components\n",
        f"**{total}** total — **{active}** active{inactive_note}\n",
        "| Category | Count | Active | Inactive |",
        "| --- | --- | --- | --- |",
    ]
    for cat in _CAT_ORDER:
        comps = by_cat.get(cat)
        if comps:
            act = sum(1 for c in comps if c.state == "Active")
            inact = len(comps) - act
            lines.append(f"| {_CAT_LABELS[cat]} | {len(comps)} | {act} | {inact if inact else '—'} |")
    lines.append("")

    _TOPIC_CATS = {"user_topics", "orchestrator_topics", "system_topics", "automation_topics"}

    for cat in _CAT_ORDER:
        comps = by_cat.get(cat)
        if not comps:
            continue
        lines.append(f"### {_CAT_LABELS[cat]} ({len(comps)})\n")
        if cat in _TOPIC_CATS:
            lines.append("| Name | Trigger | Status |")
            lines.append("| --- | --- | --- |")
            for c in comps:
                trigger = _short_trigger_label(c.trigger_kind)
                status = "✓ Active" if c.state == "Active" else "╌ Inactive"
                lines.append(f"| {c.display_name} | {trigger} | {status} |")
        else:
            lines.append("| Name | Status |")
            lines.append("| --- | --- |")
            for c in comps:
                status = "✓ Active" if c.state == "Active" else "╌ Inactive"
                lines.append(f"| {c.display_name} | {status} |")
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
        '%%{init: {"useMaxWidth": false, "theme": "base", "themeVariables": {"fontFamily": "Segoe UI, Arial, sans-serif", "fontSize": "14px", "primaryTextColor": "#102548", "lineColor": "#6f86a8"}, "flowchart": {"htmlLabels": false, "curve": "basis", "nodeSpacing": 60, "rankSpacing": 80, "padding": 16}}}%%',
        "graph TD",
        "    classDef default fill:#ffffff,stroke:#8bb8ff,stroke-width:1.6px,color:#102548;",
        "    linkStyle default stroke:#6f86a8,stroke-width:1.4px;",
    ]
    for nid, display in sorted(nodes.items()):
        lines.append(f'    {nid}("{_sanitize_mermaid(display)}")')

    for src, tgt, condition in edges:
        if condition:
            cond_label = _sanitize_mermaid(condition)
            if len(cond_label) > 28:
                cond_label = cond_label[:25] + "..."
            lines.append(f"    {src} -->|{cond_label}| {tgt}")
        else:
            lines.append(f"    {src} --> {tgt}")

    lines.extend(["```", ""])
    return "\n".join(lines)


# ── Structured viz dict (for rich web UI rendering) ──────────────────────────

_CAT_COLORS: dict[str, str] = {
    "user_topics": "#0078d4",
    "orchestrator_topics": "#7719aa",
    "system_topics": "#107c10",
    "automation_topics": "#c7921e",
    "knowledge": "#0fa3b1",
    "skills": "#5c6bc0",
    "custom_entities": "#e67e22",
    "variables": "#795548",
    "settings": "#607d8b",
}

_TOPIC_CATS: set[str] = {"user_topics", "orchestrator_topics", "system_topics", "automation_topics"}


def _profile_to_viz_dict(profile: BotProfile) -> dict:
    """Convert a parsed BotProfile into a flat, JSON-serialisable dict for the web UI."""
    by_cat: dict[str, list[ComponentSummary]] = {}
    for comp in profile.components:
        cat = _classify(comp)
        if cat is not None:
            by_cat.setdefault(cat, []).append(comp)

    total = sum(len(v) for v in by_cat.values())
    active = sum(1 for v in by_cat.values() for c in v if c.state == "Active")

    category_stats: list[dict] = []
    for cat in _CAT_ORDER:
        comps = by_cat.get(cat)
        if comps:
            act = sum(1 for c in comps if c.state == "Active")
            category_stats.append(
                {
                    "label": _CAT_LABELS[cat],
                    "color": _CAT_COLORS.get(cat, "#607d8b"),
                    "total": len(comps),
                    "active": act,
                    "inactive": len(comps) - act,
                    "inactive_display": str(len(comps) - act) if (len(comps) - act) > 0 else "—",
                }
            )

    # Flat list of header + item rows for rx.foreach rendering
    component_rows: list[dict] = []
    for cat in _CAT_ORDER:
        comps = by_cat.get(cat)
        if not comps:
            continue
        color = _CAT_COLORS.get(cat, "#607d8b")
        component_rows.append(
            {
                "kind": "header",
                "label": f"{_CAT_LABELS[cat]} ({len(comps)})",
                "color": color,
                "name": "",
                "trigger": "",
                "state": "",
            }
        )
        for c in comps:
            is_active = c.state == "Active"
            component_rows.append(
                {
                    "kind": "topic" if cat in _TOPIC_CATS else "other",
                    "name": c.display_name,
                    "trigger": _short_trigger_label(c.trigger_kind) if cat in _TOPIC_CATS else "",
                    "state": c.state,
                    "status_label": "Active" if is_active else "Inactive",
                    "status_scheme": "green" if is_active else "orange",
                    "row_bg": "#f6fff6" if is_active else "#fffbe6",
                    "row_border": "#107c10" if is_active else "#c7921e",
                    "color": color,
                    "label": "",
                }
            )

    # Instructions
    g = profile.gpt_info
    instructions_length = 0
    instructions_preview = ""
    model = ""
    web_browsing = False
    if g:
        model = g.model_hint or ""
        web_browsing = g.web_browsing
        if g.instructions:
            instructions_length = len(g.instructions)
            snippet = g.instructions[:600]
            instructions_preview = snippet + ("…" if instructions_length > 600 else "")

    # Mermaid
    mermaid_content = ""
    if profile.topic_connections:
        graph_md = _render_topic_graph(profile)
        m = re.search(r"```mermaid\s*\n(.*?)```", graph_md, re.DOTALL)
        if m:
            mermaid_content = m.group(1).strip()

    return {
        "display_name": profile.display_name,
        "schema_name": profile.schema_name,
        "channels": [c for c in profile.channels if c],
        "recognizer": profile.recognizer_kind,
        "model": model,
        "web_browsing": web_browsing,
        "use_model_knowledge": profile.use_model_knowledge,
        "instructions_length": instructions_length,
        "instructions_preview": instructions_preview,
        "total": total,
        "active": active,
        "inactive": total - active,
        "category_stats": category_stats,
        "component_rows": component_rows,
        "mermaid": mermaid_content,
    }


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


def visualize_zip_bytes(zip_bytes: bytes) -> dict:
    """Parse a solution ZIP and return a structured dict for the rich web UI.

    Returns a flat, JSON-serialisable dict ready to be unpacked into State viz_* vars.
    Raises ``ValueError`` or ``RuntimeError`` on failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, tmp)
        profile = parse_solution_zip(tmp)

    return _profile_to_viz_dict(profile)


def get_evals_data(zip_bytes: bytes) -> dict:
    """Parse evaluation and test sets from a solution ZIP and return a serializable dict.

    Returns a dict with keys:
      - ``test_sets``: list of TestSet dicts (schema_name, display_name, test_cases)
      - ``eval_sets``: list of EvalSet dicts (schema_name, display_name, graders, rows)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, tmp)
        profile = parse_evals_zip(tmp)
    return profile.model_dump()
