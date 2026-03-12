"""MCS Agent Analyser — parse botContent.yml and dialog.json from a Copilot Studio snapshot.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from mcs_models import (
    MCSAISettings,
    MCSBotProfile,
    MCSComponentSummary,
    MCSExternalTool,
    MCSGptInfo,
    MCSKnowledgeSource,
    MCSTopicConnection,
)
from yaml_utils import sanitize_yaml


def _flatten_scalar(value: object) -> str | None:
    """Return a compact string for scalar-like values, otherwise None."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        text = str(value).strip()
        return text or None
    return None


def _iter_dict_nodes(node: object):
    """Yield all dict nodes recursively from a nested JSON/YAML structure."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dict_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dict_nodes(item)


def _normalize_knowledge_type(raw: str | None, bucket: str | None = None) -> str:
    src = (raw or bucket or "").strip().lower()
    mapping = {
        "publicsites": "Website",
        "websites": "Website",
        "urls": "Website",
        "sharepointsites": "SharePoint",
        "sharepoint": "SharePoint",
        "files": "File",
        "filesources": "File",
        "dataverse": "Dataverse",
        "dataversesources": "Dataverse",
        "dataversetables": "Dataverse",
        "customsources": "Custom",
        "custom": "Custom",
    }
    if src in mapping:
        return mapping[src]
    if src:
        return src.replace("_", " ").replace("-", " ").title()
    return "Unknown"


def _extract_knowledge_entry(entry: object, bucket: str | None = None) -> MCSKnowledgeSource | None:
    """Best-effort extraction of a single knowledge source entry."""
    if isinstance(entry, str):
        text = entry.strip()
        if not text:
            return None
        src_type = _normalize_knowledge_type(None, bucket)
        return MCSKnowledgeSource(
            name=text,
            source_type=src_type,
            location=text if text.startswith(("http://", "https://", "/")) else None,
        )

    if not isinstance(entry, dict):
        return None

    src_type = _normalize_knowledge_type(
        _flatten_scalar(entry.get("type"))
        or _flatten_scalar(entry.get("kind"))
        or _flatten_scalar(entry.get("sourceType")),
        bucket,
    )
    name = (
        _flatten_scalar(entry.get("name"))
        or _flatten_scalar(entry.get("displayName"))
        or _flatten_scalar(entry.get("title"))
        or _flatten_scalar(entry.get("id"))
        or "Unnamed source"
    )
    location = (
        _flatten_scalar(entry.get("url"))
        or _flatten_scalar(entry.get("siteUrl"))
        or _flatten_scalar(entry.get("sharePointSiteUrl"))
        or _flatten_scalar(entry.get("path"))
        or _flatten_scalar(entry.get("filePath"))
        or _flatten_scalar(entry.get("resource"))
        or _flatten_scalar(entry.get("entityName"))
        or _flatten_scalar(entry.get("tableName"))
    )
    site_id = (
        _flatten_scalar(entry.get("siteId"))
        or _flatten_scalar(entry.get("sharePointSiteId"))
        or _flatten_scalar(entry.get("sharepointSiteId"))
    )

    details: dict[str, str] = {}
    for key in (
        "description",
        "library",
        "list",
        "folder",
        "table",
        "entityName",
        "environment",
        "connectionReference",
        "connectionReferenceLogicalName",
    ):
        val = _flatten_scalar(entry.get(key))
        if val:
            details[key] = val

    return MCSKnowledgeSource(
        name=name,
        source_type=src_type,
        location=location,
        site_id=site_id,
        details=details,
    )


def _extract_knowledge_sources(data: dict) -> list[MCSKnowledgeSource]:
    """Extract knowledge sources from any knowledgeSources blocks in the YAML."""
    items: list[MCSKnowledgeSource] = []
    seen: set[tuple[str, str, str]] = set()

    for node in _iter_dict_nodes(data):
        if "knowledgeSources" not in node:
            continue
        block = node.get("knowledgeSources")

        if isinstance(block, dict):
            for bucket, value in block.items():
                if isinstance(value, list):
                    for entry in value:
                        src = _extract_knowledge_entry(entry, bucket=bucket)
                        if src is None:
                            continue
                        sig = (src.source_type, src.name, src.location or "")
                        if sig not in seen:
                            seen.add(sig)
                            items.append(src)
                else:
                    src = _extract_knowledge_entry(value, bucket=bucket)
                    if src is None:
                        continue
                    sig = (src.source_type, src.name, src.location or "")
                    if sig not in seen:
                        seen.add(sig)
                        items.append(src)
        elif isinstance(block, list):
            for entry in block:
                src = _extract_knowledge_entry(entry)
                if src is None:
                    continue
                sig = (src.source_type, src.name, src.location or "")
                if sig not in seen:
                    seen.add(sig)
                    items.append(src)

    return items


def _normalize_auth_mode(raw_mode: str | None) -> str | None:
    if not raw_mode:
        return None
    mode = raw_mode.strip().lower()
    if not mode:
        return None
    if any(token in mode for token in ("invoking", "user", "caller")):
        return "User identity"
    if any(token in mode for token in ("maker", "owner", "service", "application", "app")):
        return "Maker/service account"
    return raw_mode


def _extract_auth_mode(node: dict) -> str | None:
    cp = node.get("connectionProperties")
    if isinstance(cp, dict):
        mode = _flatten_scalar(cp.get("mode"))
        if mode:
            return _normalize_auth_mode(mode)

    for key in ("authMode", "authenticationMode", "mode"):
        mode = _flatten_scalar(node.get(key))
        if mode:
            return _normalize_auth_mode(mode)
    return None


_ACTION_KIND_TO_TOOL_TYPE = {
    "HttpRequestAction": "HTTP Request",
    "InvokeAIBuilderModelAction": "AI Builder Model",
    "InvokeExternalAgentTaskAction": "External Agent / MCP",
    "InvokeFlowAction": "Cloud Flow",
}


def _extract_external_tools(data: dict) -> list[MCSExternalTool]:
    """Extract connector and tool references from components and action nodes."""
    tools: list[MCSExternalTool] = []
    seen: set[tuple[str, str, str]] = set()

    def _append(tool: MCSExternalTool) -> None:
        sig = (tool.tool_type, tool.name or "", tool.connector_id or "")
        if sig in seen:
            return
        seen.add(sig)
        tools.append(tool)

    for node in _iter_dict_nodes(data):
        kind = _flatten_scalar(node.get("kind"))
        connector_id = _flatten_scalar(node.get("connectorId"))
        connection_ref = _flatten_scalar(node.get("connectionReference")) or _flatten_scalar(
            node.get("connectionReferenceLogicalName")
        )
        auth_mode = _extract_auth_mode(node)

        if kind in _ACTION_KIND_TO_TOOL_TYPE:
            name = (
                _flatten_scalar(node.get("displayName"))
                or _flatten_scalar(node.get("name"))
                or _flatten_scalar(node.get("actionName"))
                or _flatten_scalar(node.get("flowName"))
                or _flatten_scalar(node.get("flowId"))
                or _flatten_scalar(node.get("modelName"))
                or kind
            )
            details: dict[str, str] = {}
            for key in ("flowId", "modelName", "taskName", "operationId", "url", "method"):
                val = _flatten_scalar(node.get(key))
                if val:
                    details[key] = val
            if connection_ref:
                details["connectionReference"] = connection_ref
            _append(
                MCSExternalTool(
                    name=name,
                    tool_type=_ACTION_KIND_TO_TOOL_TYPE[kind],
                    connector_id=connector_id,
                    auth_mode=auth_mode,
                    details=details,
                )
            )

        # Generic connector references and connection entries.
        if connector_id or connection_ref:
            name = (
                _flatten_scalar(node.get("displayName"))
                or _flatten_scalar(node.get("name"))
                or _flatten_scalar(node.get("connectorName"))
                or connector_id
                or connection_ref
                or "Connector"
            )
            details = {}
            if connection_ref:
                details["connectionReference"] = connection_ref
            for key in ("operationId", "apiId", "connectionId"):
                val = _flatten_scalar(node.get(key))
                if val:
                    details[key] = val
            _append(
                MCSExternalTool(
                    name=name,
                    tool_type="Connector",
                    connector_id=connector_id,
                    auth_mode=auth_mode,
                    details=details,
                )
            )

        # MCP/External server references even when kind is absent.
        mcp_url = _flatten_scalar(node.get("serverUrl")) or _flatten_scalar(node.get("mcpServerUrl"))
        mcp_name = _flatten_scalar(node.get("serverName")) or _flatten_scalar(node.get("mcpServer"))
        if mcp_url or mcp_name:
            details = {}
            if mcp_url:
                details["serverUrl"] = mcp_url
            _append(
                MCSExternalTool(
                    name=mcp_name or mcp_url or "MCP Server",
                    tool_type="External Agent / MCP",
                    connector_id=connector_id,
                    auth_mode=auth_mode,
                    details=details,
                )
            )

    return tools


def _extract_gpt_info(comp: dict) -> MCSGptInfo:
    """Extract GPT configuration from a GptComponent."""
    metadata = comp.get("metadata", {}) or {}
    ai_settings = metadata.get("aISettings", {}) or {}
    model = ai_settings.get("model", {}) or {}
    capabilities = metadata.get("gptCapabilities", {}) or {}
    ks = metadata.get("knowledgeSources", {}) or {}

    return MCSGptInfo(
        display_name=metadata.get("displayName", "") or comp.get("displayName", ""),
        description=comp.get("description"),
        instructions=metadata.get("instructions"),
        model_hint=model.get("modelNameHint"),
        knowledge_sources_kind=ks.get("kind"),
        web_browsing=capabilities.get("webBrowsing", False),
        code_interpreter=capabilities.get("codeInterpreter", False),
    )


def _extract_begin_dialogs(
    actions: list,
    source_schema: str,
    source_display: str,
    schema_to_display: dict[str, str],
    condition: str | None = None,
) -> list[MCSTopicConnection]:
    """Recursively walk dialog actions and extract BeginDialog connections."""
    connections: list[MCSTopicConnection] = []
    if not actions:
        return connections

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
                    MCSTopicConnection(
                        source_schema=source_schema,
                        source_display=source_display,
                        target_schema=target_schema,
                        target_display=target_display,
                        condition=condition,
                    )
                )

        elif kind == "ConditionGroup":
            for cond in action.get("conditions", []) or []:
                if not isinstance(cond, dict):
                    continue
                cond_expr = cond.get("condition")
                connections.extend(
                    _extract_begin_dialogs(
                        cond.get("actions", []) or [],
                        source_schema,
                        source_display,
                        schema_to_display,
                        condition=cond_expr,
                    )
                )
            connections.extend(
                _extract_begin_dialogs(
                    action.get("elseActions", []) or [],
                    source_schema,
                    source_display,
                    schema_to_display,
                    condition="else",
                )
            )

        if kind != "ConditionGroup":
            for key in ("actions", "elseActions"):
                nested = action.get(key)
                if isinstance(nested, list):
                    connections.extend(
                        _extract_begin_dialogs(
                            nested,
                            source_schema,
                            source_display,
                            schema_to_display,
                            condition=condition,
                        )
                    )

    return connections


def parse_yaml(path: Path) -> tuple[MCSBotProfile, dict[str, str]]:
    """Parse botContent.yml and return (MCSBotProfile, schema_to_display lookup)."""
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(sanitize_yaml(raw))

    entity = data.get("entity", {})
    config = entity.get("configuration", {})

    # Channels
    channels_raw = config.get("channels", []) or []
    channels = [ch.get("channelId", "") for ch in channels_raw if isinstance(ch, dict)]

    # AI settings
    ai_raw = config.get("aISettings", {}) or {}
    ai_settings = MCSAISettings(
        use_model_knowledge=ai_raw.get("useModelKnowledge", False),
        file_analysis=ai_raw.get("isFileAnalysisEnabled", False),
        semantic_search=ai_raw.get("isSemanticSearchEnabled", False),
        content_moderation=ai_raw.get("contentModeration", "Unknown"),
        opt_in_latest_models=ai_raw.get("optInUseLatestModels", False),
    )

    # Recognizer
    recognizer = config.get("recognizer", {}) or {}
    recognizer_kind = recognizer.get("kind", "Unknown")
    recognizer_id = (
        recognizer.get("recognizerId") or recognizer.get("projectName") or recognizer.get("applicationId") or ""
    )

    # Components + lookup table
    components: list[MCSComponentSummary] = []
    schema_to_display: dict[str, str] = {}
    is_orchestrator = False

    for comp in data.get("components", []) or []:
        kind = comp.get("kind", "Unknown")
        display_name = comp.get("displayName", "")
        schema_name = comp.get("schemaName", "")
        state = comp.get("state", "Active")
        description = comp.get("description")

        dialog = comp.get("dialog", {}) or {}
        dialog_kind = dialog.get("kind")
        trigger_kind = None
        trigger_queries: list[str] = []
        action_kind = None

        begin_dialog = dialog.get("beginDialog", {}) or {}
        if begin_dialog:
            trigger_kind = begin_dialog.get("kind")
            if trigger_kind == "OnRecognizedIntent":
                raw_queries = begin_dialog.get("triggerQueries", []) or []
                trigger_queries = [q for q in raw_queries if isinstance(q, str)]

        if dialog_kind in ("TaskDialog", "AgentDialog"):
            is_orchestrator = True
            action = dialog.get("action", {}) or {}
            action_kind = action.get("kind")

        if kind == "GptComponent" and not display_name:
            metadata = comp.get("metadata", {}) or {}
            display_name = metadata.get("displayName", schema_name)

        components.append(
            MCSComponentSummary(
                kind=kind,
                display_name=display_name,
                schema_name=schema_name,
                state=state,
                trigger_kind=trigger_kind,
                trigger_queries=trigger_queries,
                dialog_kind=dialog_kind,
                action_kind=action_kind,
                description=description,
            )
        )

        if schema_name and display_name:
            schema_to_display[schema_name] = display_name

    # Bot display name: prefer GptComponent, fallback to entity displayName, then schemaName
    bot_display_name = entity.get("displayName", "")
    if not bot_display_name:
        gpt_comps = [c for c in components if c.kind == "GptComponent"]
        if gpt_comps:
            bot_display_name = gpt_comps[0].display_name
    if not bot_display_name:
        bot_display_name = entity.get("schemaName", "Unknown Agent")

    # Second pass: extract GPT info and topic connections
    gpt_info: MCSGptInfo | None = None
    topic_connections: list[MCSTopicConnection] = []
    knowledge_sources = _extract_knowledge_sources(data)
    external_tools = _extract_external_tools(data)

    for comp in data.get("components", []) or []:
        kind = comp.get("kind", "")

        if kind == "GptComponent" and gpt_info is None:
            gpt_info = _extract_gpt_info(comp)

        if kind == "DialogComponent":
            comp_schema = comp.get("schemaName", "")
            comp_display = schema_to_display.get(comp_schema, comp.get("displayName", comp_schema))
            dialog = comp.get("dialog", {}) or {}
            begin_dialog = dialog.get("beginDialog", {}) or {}
            dialog_actions = begin_dialog.get("actions", []) or []
            topic_connections.extend(
                _extract_begin_dialogs(dialog_actions, comp_schema, comp_display or "", schema_to_display)
            )

    profile = MCSBotProfile(
        schema_name=entity.get("schemaName", ""),
        bot_id=entity.get("cdsBotId", ""),
        display_name=bot_display_name,
        channels=channels,
        ai_settings=ai_settings,
        recognizer_kind=recognizer_kind,
        recognizer_id=recognizer_id,
        components=components,
        is_orchestrator=is_orchestrator,
        gpt_info=gpt_info,
        topic_connections=topic_connections,
        knowledge_sources=knowledge_sources,
        external_tools=external_tools,
    )

    return profile, schema_to_display


def parse_dialog_json(path: Path) -> list[dict]:
    """Parse dialog.json and return activities sorted by position."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    activities = data.get("activities", [])

    def get_position(activity: dict) -> int:
        channel_data = activity.get("channelData", {}) or {}
        return channel_data.get("webchat:internal:position", 0)

    activities.sort(key=get_position)
    return activities


def resolve_topic_name(schema_name: str, lookup: dict[str, str]) -> str:
    """Resolve a schema name (e.g. 'copilots_xxx.topic.MyTopic') to a display name."""
    if schema_name in lookup:
        return lookup[schema_name]
    parts = schema_name.split(".")
    if len(parts) >= 2:
        return parts[-1]
    return schema_name
