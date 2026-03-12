"""Dependency Analyzer — parse a Power Platform solution ZIP and generate
a visual dependency map from solution.xml component metadata.

Inspects:
  - RootComponents in solution.xml (all component types / counts)
  - MissingDependencies in solution.xml (external components required but absent)
  - Component artefact files for display-name enrichment

Returns segments compatible with ``viz_segments`` (list[dict]) so they can be
rendered by the existing Mermaid / Markdown frontend pipeline.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import defusedxml.ElementTree as ET

from renamer import safe_extractall

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element as XmlElement

# ── Component type registry ────────────────────────────────────────────────────

# (display_name, group)
_COMP_TYPES: dict[int, tuple[str, str]] = {
    1: ("Table", "data"),
    2: ("Column", "data"),
    3: ("Relationship", "data"),
    4: ("Attribute Picklist Map", "data"),
    9: ("Option Set", "data"),
    10: ("Entity Relationship", "data"),
    14: ("Table Key", "data"),
    26: ("Web Resource", "ui"),
    29: ("Canvas App", "app"),
    30: ("Cloud Flow", "automation"),
    33: ("Dialog (Legacy)", "ui"),
    34: ("Security Role", "security"),
    38: ("Form", "ui"),
    40: ("View", "ui"),
    44: ("Environment Variable", "config"),
    45: ("Env Variable Value", "config"),
    50: ("Plugin Assembly", "code"),
    51: ("SDK Step", "code"),
    52: ("SDK Step Image", "code"),
    60: ("System Form", "ui"),
    61: ("Security Role", "security"),
    64: ("Report", "reporting"),
    65: ("Report Entity", "reporting"),
    70: ("Report", "reporting"),
    80: ("Site Map", "ui"),
    300: ("Canvas App", "app"),
    380: ("PCF Control", "ui"),
    400: ("Custom Connector", "integration"),
    401: ("AI Model", "ai"),
    402: ("AI Configuration", "ai"),
    408: ("AI Builder Model", "ai"),
    430: ("Copilot Studio Agent", "agent"),
    431: ("Bot Component", "agent"),
    432: ("Bot Component Collection", "agent"),
    10066: ("Connection Reference", "integration"),
    10067: ("AI Builder Model", "ai"),
    10068: ("Dataflow", "data"),
}

_GROUP_LABELS: dict[str, tuple[str, str]] = {
    # group → (icon, tab label)
    "agent": ("🤖", "Agent"),
    "automation": ("⚡", "Cloud Flows"),
    "integration": ("🔗", "Connections"),
    "config": ("⚙️", "Environment Variables"),
    "data": ("🗃", "Data Components"),
    "app": ("📱", "Canvas Apps"),
    "ui": ("🖥", "UI Components"),
    "code": ("🔌", "Code Components"),
    "ai": ("🧠", "AI Components"),
    "security": ("🔒", "Security"),
    "reporting": ("📊", "Reporting"),
    "other": ("📦", "Other"),
}

_MISSING_TYPE_NAME_TO_CODE: dict[str, int] = {
    "bot": 430,
    "botcomponent": 431,
    "botcomponentcollection": 432,
    "cloudflow": 30,
    "workflow": 30,
    "canvasapp": 300,
    "connectionreference": 10066,
    "environmentvariable": 44,
    "environmentvariablevalue": 45,
    "table": 1,
    "entity": 1,
}

_BOT_COMPONENT_TYPES: dict[int, tuple[str, str]] = {
    9: ("Topic", "agent"),
    10: ("Subtopic", "agent"),
    11: ("Entity", "data"),
    12: ("Variable", "config"),
    13: ("Connector Tool", "integration"),
    14: ("Knowledge File", "agent"),
    15: ("GPT Configuration", "ai"),
    16: ("Knowledge Source", "agent"),
    17: ("Action / Tool", "integration"),
    18: ("Bot Settings", "config"),
    19: ("Trigger / Example Utterance", "agent"),
}

# Maximum individual nodes before collapsing to a summary node
_MAX_INDIVIDUAL = 5
_MAX_DETAILED_MISSING_RELATIONS = 18
_MAX_DETAILED_REQUIRED_NODES = 12
_GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _type_info(code: int) -> tuple[str, str]:
    return _COMP_TYPES.get(code, (f"Component ({code})", "other"))


def _normalize_guid(text: str) -> str:
    """Return lowercase GUID without braces, or empty string if not GUID-like."""
    raw = (text or "").strip().strip("{}").lower()
    return raw if _GUID_RE.fullmatch(raw) else ""


def _extract_guid(text: str) -> str:
    """Extract first GUID-like token from a string, normalized to lowercase."""
    m = _GUID_RE.search(text or "")
    return m.group(0).lower() if m else ""


def _safe_node_id(text: str, prefix: str = "N") -> str:
    """Return a globally-unique, Mermaid-safe node ID."""
    clean = re.sub(r"[^A-Za-z0-9_]", "_", text).strip("_")
    base = clean[:28] if clean else "X"
    return f"{prefix}_{base}"


# ── Internal data classes ─────────────────────────────────────────────────────


class _Component:
    __slots__ = (
        "type_code",
        "comp_id",
        "schema_name",
        "display_name",
        "type_name_override",
        "group_override",
        "source_hint",
        "kind_hint",
    )

    def __init__(
        self,
        type_code: int,
        comp_id: str,
        schema_name: str = "",
        display_name: str = "",
        type_name_override: str = "",
        group_override: str = "",
        source_hint: str = "solution.xml",
        kind_hint: str = "",
    ) -> None:
        self.type_code = type_code
        self.comp_id = comp_id
        self.schema_name = schema_name
        self.display_name = display_name
        self.type_name_override = type_name_override
        self.group_override = group_override
        self.source_hint = source_hint
        self.kind_hint = kind_hint

    @property
    def label(self) -> str:
        return self.display_name or self.schema_name or self.comp_id[:12] or "?"

    @property
    def stripped_id(self) -> str:
        return self.comp_id.strip("{}").lower()


class _MissingDep:
    __slots__ = (
        "req_type",
        "req_type_name",
        "req_name",
        "req_schema",
        "req_identifier",
        "req_solution",
        "req_package",
        "dep_type",
        "dep_type_name",
        "dep_name",
        "dep_schema",
        "dep_identifier",
        "dep_id",
    )

    def __init__(
        self,
        req_type: int,
        req_type_name: str,
        req_name: str,
        req_schema: str,
        req_identifier: str,
        req_solution: str,
        req_package: str,
        dep_type: int,
        dep_type_name: str,
        dep_name: str,
        dep_schema: str,
        dep_identifier: str,
        dep_id: str,
    ) -> None:
        self.req_type = req_type
        self.req_type_name = req_type_name
        self.req_name = req_name or req_schema or req_identifier or "Unknown"
        self.req_schema = req_schema
        self.req_identifier = req_identifier
        self.req_solution = req_solution
        self.req_package = req_package

        self.dep_type = dep_type
        self.dep_type_name = dep_type_name
        self.dep_name = dep_name or dep_schema or dep_identifier or "Unknown"
        self.dep_schema = dep_schema
        self.dep_identifier = dep_identifier
        self.dep_id = dep_id.strip("{}")

    @property
    def type_label(self) -> str:
        if self.req_type > 0:
            return _type_info(self.req_type)[0]
        if self.req_type_name:
            return self.req_type_name
        return "Unknown"

    @property
    def dedup_key(self) -> str:
        req_ref = (self.req_schema or self.req_identifier or self.req_name).lower()
        return f"{self.req_type}:{self.req_type_name.lower()}:{req_ref}"

    @property
    def relation_key(self) -> str:
        dep_ref = (self.dep_schema or self.dep_identifier or self.dep_name).lower()
        return f"{dep_ref}->{self.dedup_key}"


def _first_attr(el: "XmlElement | None", candidates: list[str]) -> str:
    if el is None:
        return ""
    lower_map = {k.lower(): v for k, v in el.attrib.items()}
    for key in candidates:
        if key in el.attrib and el.attrib[key]:
            return el.attrib[key]
        v = lower_map.get(key.lower())
        if v:
            return v
    return ""


def _parse_missing_type(type_value: str) -> tuple[int, str]:
    """Parse MissingDependency type into (numeric_code, display_name)."""
    raw = (type_value or "").strip()
    if not raw:
        return 0, ""
    if raw.isdigit():
        code = int(raw)
        return code, _type_info(code)[0]

    normalized = re.sub(r"[^a-z0-9]", "", raw.lower())
    mapped = _MISSING_TYPE_NAME_TO_CODE.get(normalized)
    if mapped is not None:
        return mapped, _type_info(mapped)[0]

    # Pattern-based fallbacks seen in dependency payloads.
    if "workflow" in normalized:
        return 30, _type_info(30)[0]
    if "connectionreference" in normalized:
        return 10066, _type_info(10066)[0]
    if "environmentvariabledefinition" in normalized or "environmentvariable" in normalized:
        return 44, _type_info(44)[0]
    if "msdynaimodel" in normalized or normalized.endswith("aimodel"):
        return 401, _type_info(401)[0]
    if normalized.startswith("botcomponent"):
        return 431, _type_info(431)[0]

    # Keep original symbolic type when no numeric mapping exists.
    return 0, raw


def _first_data_kind(data_path: Path) -> str:
    """Return first detected kind marker from data file (YAML or JSON-ish)."""
    try:
        text = data_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

    # YAML: kind: Something
    m = re.search(r"(?m)^kind:\s*([^\n]+)$", text)
    if m:
        return m.group(1).strip()

    # JSON: "kind": "Something" or "$kind": "Something"
    m = re.search(r'"\$?kind"\s*:\s*"([^"]+)"', text)
    if m:
        return m.group(1).strip()
    return ""


def _infer_botcomponent_type(
    schema_name: str,
    componenttype: int,
    data_kind: str,
) -> tuple[str, str]:
    """Infer readable type/group for Copilot botcomponents."""
    schema = (schema_name or "").lower()
    kind = (data_kind or "").strip()
    kind_l = kind.lower()

    # Explicit schema markers are most reliable for Copilot exports.
    if ".agent." in schema:
        return "Agent", "agent"
    if ".topic." in schema or kind_l.endswith("dialog"):
        return "Topic", "agent"
    if ".gpt." in schema or "gpt" in kind_l:
        return "GPT Configuration", "ai"
    if ".file." in schema:
        return "Knowledge File", "agent"
    if ".entity." in schema or "entity" in kind_l:
        return "Entity", "data"
    if ".globalvariablecomponent." in schema:
        return "Variable", "config"
    if "settingscomponent" in schema:
        return "Bot Settings", "config"

    # Fallback to raw componenttype mapping when schema does not identify kind.
    if componenttype in _BOT_COMPONENT_TYPES:
        return _BOT_COMPONENT_TYPES[componenttype]

    return "Bot Component", "agent"


def _split_botcomponent_schema(schema: str) -> tuple[str, str]:
    """Return (short_name, readable_type) for botcomponent-like schema names."""
    raw = (schema or "").strip().strip("{}")
    low = raw.lower()

    markers: list[tuple[str, str]] = [
        (".topic.", "Topic"),
        (".agent.", "Agent"),
        (".globalvariablecomponent.", "Variable"),
        (".gpt.", "GPT Configuration"),
        (".entity.", "Entity"),
        (".file.", "Knowledge File"),
    ]
    for marker, type_name in markers:
        idx = low.find(marker)
        if idx >= 0:
            short = raw[idx + len(marker) :].strip()
            return (short or raw, type_name)

    if "." in raw:
        # Generic fallback: keep final token as friendly label.
        return raw.split(".")[-1], "Bot Component"
    return raw, "Bot Component"


def _friendly_component_name(name: str, schema: str = "", identifier: str = "") -> str:
    """Create short readable names for long component identifiers."""
    candidate = (name or schema or identifier or "").strip().strip("{}")
    if not candidate:
        return "Unknown"

    # Prefer explicit schema for botcomponents where possible.
    for probe in (schema, candidate):
        short, _kind = _split_botcomponent_schema(probe)
        if short != (probe or "") and short:
            return short

    # Keep GUIDs as-is.
    if _normalize_guid(candidate):
        return candidate.lower()

    return candidate


def _friendly_botcomponent_type(schema: str, fallback: str) -> str:
    """Promote generic Bot Component into specific schema-based type when available."""
    short, inferred = _split_botcomponent_schema(schema)
    _ = short
    if inferred != "Bot Component":
        return inferred
    return fallback or "Bot Component"


def _workflow_name_map(work_dir: Path) -> dict[str, str]:
    """Map workflow GUID -> friendly display name from Workflows/*.json files."""
    out: dict[str, str] = {}
    wf_dir = work_dir / "Workflows"
    if not wf_dir.is_dir():
        return out

    for wf_file in wf_dir.iterdir():
        if not wf_file.is_file() or wf_file.suffix.lower() != ".json":
            continue
        guid = _extract_guid(wf_file.stem)
        if not guid:
            continue
        friendly = ""
        try:
            data = json.loads(wf_file.read_text(encoding="utf-8", errors="replace"))
            friendly = (data.get("properties") or {}).get("displayName") or data.get("name") or ""
        except Exception:
            friendly = ""
        if not friendly and "-" in wf_file.stem:
            friendly = wf_file.stem.rsplit("-", 1)[0].replace("_", " ")
        out[guid] = friendly or guid
    return out


def _build_asset_relation_rows(work_dir: Path) -> list[dict]:
    """Build explicit dependency relations from Assets/*set.xml mappings."""
    rows: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    assets_dir = work_dir / "Assets"
    if not assets_dir.is_dir():
        return rows

    flow_names = _workflow_name_map(work_dir)

    def _add(
        dep_schema: str,
        req_name: str,
        req_type: str,
        source: str,
    ) -> None:
        dep_short, dep_kind = _split_botcomponent_schema(dep_schema)
        key = (dep_short.lower(), dep_kind.lower(), req_name.lower(), req_type.lower(), source.lower())
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "dependent": _truncate_middle(dep_short or dep_schema or "Unknown", 64),
                "dependent_type": dep_kind,
                "required": _truncate_middle(req_name or "Unknown", 64),
                "required_type": req_type,
                "source": source,
            }
        )

    wf_set = assets_dir / "botcomponent_workflowset.xml"
    if wf_set.exists():
        try:
            root = ET.parse(wf_set).getroot()
            if root is not None:
                for row in root.findall("botcomponent_workflow"):
                    dep_schema = _first_attr(row, ["botcomponentid.schemaname"])
                    wf_id = _first_attr(row, ["workflowid.workflowid"]).strip("{}").lower()
                    if dep_schema and wf_id:
                        _add(dep_schema, flow_names.get(wf_id, wf_id), "Cloud Flow", "Assets/workflowset")
        except Exception:
            pass

    cr_set = assets_dir / "botcomponent_connectionreferenceset.xml"
    if cr_set.exists():
        try:
            root = ET.parse(cr_set).getroot()
            if root is not None:
                for row in root.findall("botcomponent_connectionreference"):
                    dep_schema = _first_attr(row, ["botcomponentid.schemaname"])
                    cr_name = _first_attr(row, ["connectionreferenceid.connectionreferencelogicalname"])
                    if dep_schema and cr_name:
                        _add(dep_schema, cr_name, "Connection Reference", "Assets/connectionreferenceset")
        except Exception:
            pass

    ev_set = assets_dir / "botcomponent_environmentvariabledefinitionset.xml"
    if ev_set.exists():
        try:
            root = ET.parse(ev_set).getroot()
            if root is not None:
                for row in root.findall("botcomponent_environmentvariabledefinition"):
                    dep_schema = _first_attr(row, ["botcomponentid.schemaname"])
                    ev_name = _first_attr(row, ["environmentvariabledefinitionid.schemaname"])
                    if dep_schema and ev_name:
                        _add(dep_schema, ev_name, "Environment Variable", "Assets/environmentvariabledefinitionset")
        except Exception:
            pass

    ai_set = assets_dir / "botcomponent_msdyn_aimodelset.xml"
    if ai_set.exists():
        try:
            root = ET.parse(ai_set).getroot()
            if root is not None:
                for row in root.findall("botcomponent_msdyn_aimodel"):
                    dep_schema = _first_attr(row, ["botcomponentid.schemaname"])
                    model_id = _first_attr(row, ["msdyn_aimodelid.msdyn_aimodelid"]).strip("{}").lower()
                    if dep_schema and model_id:
                        _add(dep_schema, model_id, "AI Model", "Assets/msdyn_aimodelset")
        except Exception:
            pass

    return rows


def _merge_relation_rows(primary: list[dict], extra: list[dict]) -> list[dict]:
    """Merge and de-duplicate relation rows while preserving stable ordering."""
    merged: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in [*primary, *extra]:
        key = (
            (row.get("dependent") or "").lower(),
            (row.get("dependent_type") or "").lower(),
            (row.get("required") or "").lower(),
            (row.get("required_type") or "").lower(),
            (row.get("source") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _discover_components_from_artifacts(work_dir: Path) -> list[_Component]:
    """Discover components from folder artefacts for exports with sparse solution.xml."""
    discovered: list[_Component] = []

    # Bot-level metadata
    bots_dir = work_dir / "bots"
    if bots_dir.is_dir():
        for bot_dir in bots_dir.iterdir():
            if not bot_dir.is_dir():
                continue
            schema = bot_dir.name
            name = ""
            bot_xml = bot_dir / "bot.xml"
            if bot_xml.exists():
                try:
                    root = ET.parse(bot_xml).getroot()
                    if root is not None:
                        schema = root.get("schemaname") or schema
                        name = root.findtext("name") or ""
                except Exception:
                    pass
            if not name:
                cfg = bot_dir / "configuration.json"
                if cfg.exists():
                    try:
                        data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
                        name = data.get("displayName") or data.get("name") or ""
                    except Exception:
                        pass
            discovered.append(
                _Component(
                    type_code=430,
                    comp_id=schema,
                    schema_name=schema,
                    display_name=name,
                    type_name_override="Copilot Studio Agent",
                    group_override="agent",
                    source_hint="bots/",
                )
            )

    # Bot components (topic, knowledge, entities, settings, tools, etc.)
    for bot_xml in work_dir.rglob("botcomponent.xml"):
        parent = bot_xml.parent
        schema_default = parent.name
        schema = schema_default
        name = ""
        componenttype = 0
        try:
            root = ET.parse(bot_xml).getroot()
            if root is not None:
                schema = root.get("schemaname") or schema_default
                name = root.findtext("name") or root.findtext("displayname") or ""
                ct_text = (root.findtext("componenttype") or "").strip()
                if ct_text.isdigit():
                    componenttype = int(ct_text)
                parent_bot_schema = (root.findtext("parentbotid/schemaname") or "").strip()
                if parent_bot_schema:
                    discovered.append(
                        _Component(
                            type_code=430,
                            comp_id=parent_bot_schema,
                            schema_name=parent_bot_schema,
                            type_name_override="Copilot Studio Agent",
                            group_override="agent",
                            source_hint="botcomponents/parentbot",
                        )
                    )
        except Exception:
            pass

        data_path = parent / "data"
        data_kind = _first_data_kind(data_path) if data_path.exists() else ""
        type_name, group = _infer_botcomponent_type(schema, componenttype, data_kind)

        discovered.append(
            _Component(
                type_code=431,
                comp_id=schema,
                schema_name=schema,
                display_name=name,
                type_name_override=type_name,
                group_override=group,
                source_hint="botcomponents/",
                kind_hint=data_kind,
            )
        )

    # Assets set files can contain referenced components that are not represented
    # as RootComponents in solution.xml for managed exports.
    assets_dir = work_dir / "Assets"
    if assets_dir.is_dir():
        # botcomponent_workflowset.xml
        wf_set = assets_dir / "botcomponent_workflowset.xml"
        if wf_set.exists():
            try:
                root = ET.parse(wf_set).getroot()
                if root is not None:
                    for row in root.findall("botcomponent_workflow"):
                        wf_id = _first_attr(row, ["workflowid.workflowid"])
                        if wf_id:
                            discovered.append(
                                _Component(
                                    type_code=30,
                                    comp_id=wf_id,
                                    schema_name=wf_id.strip("{}"),
                                    type_name_override="Cloud Flow",
                                    group_override="automation",
                                    source_hint="Assets/workflowset",
                                )
                            )
            except Exception:
                pass

        # botcomponent_connectionreferenceset.xml
        cr_set = assets_dir / "botcomponent_connectionreferenceset.xml"
        if cr_set.exists():
            try:
                root = ET.parse(cr_set).getroot()
                if root is not None:
                    for row in root.findall("botcomponent_connectionreference"):
                        logical = _first_attr(row, ["connectionreferenceid.connectionreferencelogicalname"])
                        if logical:
                            discovered.append(
                                _Component(
                                    type_code=10066,
                                    comp_id=logical,
                                    schema_name=logical,
                                    type_name_override="Connection Reference",
                                    group_override="integration",
                                    source_hint="Assets/connectionreferenceset",
                                )
                            )
            except Exception:
                pass

        # botcomponent_environmentvariabledefinitionset.xml
        ev_set = assets_dir / "botcomponent_environmentvariabledefinitionset.xml"
        if ev_set.exists():
            try:
                root = ET.parse(ev_set).getroot()
                if root is not None:
                    for row in root.findall("botcomponent_environmentvariabledefinition"):
                        schema = _first_attr(row, ["environmentvariabledefinitionid.schemaname"])
                        if schema:
                            discovered.append(
                                _Component(
                                    type_code=44,
                                    comp_id=schema,
                                    schema_name=schema,
                                    type_name_override="Environment Variable",
                                    group_override="config",
                                    source_hint="Assets/environmentvariabledefinitionset",
                                )
                            )
            except Exception:
                pass

        # botcomponent_msdyn_aimodelset.xml
        ai_set = assets_dir / "botcomponent_msdyn_aimodelset.xml"
        if ai_set.exists():
            try:
                root = ET.parse(ai_set).getroot()
                if root is not None:
                    for row in root.findall("botcomponent_msdyn_aimodel"):
                        model_id = _first_attr(row, ["msdyn_aimodelid.msdyn_aimodelid"])
                        if model_id:
                            discovered.append(
                                _Component(
                                    type_code=401,
                                    comp_id=model_id,
                                    schema_name=model_id.strip("{}"),
                                    type_name_override="AI Model",
                                    group_override="ai",
                                    source_hint="Assets/msdyn_aimodelset",
                                )
                            )
            except Exception:
                pass

    # Workflows directory may include flow JSON files with GUID suffixes.
    workflows_dir = work_dir / "Workflows"
    if workflows_dir.is_dir():
        for wf_file in workflows_dir.iterdir():
            if not wf_file.is_file() or wf_file.suffix.lower() != ".json":
                continue
            wf_id = _extract_guid(wf_file.stem)
            if not wf_id:
                continue
            discovered.append(
                _Component(
                    type_code=30,
                    comp_id=wf_id,
                    schema_name=wf_id,
                    type_name_override="Cloud Flow",
                    group_override="automation",
                    source_hint="Workflows/",
                )
            )

    return discovered


def _merge_components(base: list[_Component], extra: list[_Component]) -> list[_Component]:
    """Merge components de-duplicated by schema or id, preserving richer metadata."""
    merged = list(base)
    by_key: dict[str, _Component] = {}

    def _key(c: _Component) -> str:
        if c.schema_name:
            return f"schema:{c.schema_name.lower()}"
        if c.comp_id:
            return f"id:{c.comp_id.strip('{}').lower()}"
        return f"obj:{id(c)}"

    for c in merged:
        by_key[_key(c)] = c

    for c in extra:
        k = _key(c)
        existing = by_key.get(k)
        if existing is None:
            merged.append(c)
            by_key[k] = c
            continue
        if not existing.display_name and c.display_name:
            existing.display_name = c.display_name
        if not existing.type_name_override and c.type_name_override:
            existing.type_name_override = c.type_name_override
        if not existing.group_override and c.group_override:
            existing.group_override = c.group_override
        if existing.source_hint == "solution.xml" and c.source_hint:
            existing.source_hint = c.source_hint
        if not existing.kind_hint and c.kind_hint:
            existing.kind_hint = c.kind_hint

    return merged


def _extract_ref_value(text: str, preferred_keys: tuple[str, ...]) -> str:
    """Extract a readable value from key=value,key2=value2 style references."""
    if not text or "=" not in text:
        return text

    pairs: dict[str, str] = {}
    for part in text.split(","):
        key, sep, value = part.partition("=")
        if not sep:
            continue
        k = key.strip().lower()
        v = value.strip().strip("{}")
        if k and v:
            pairs[k] = v

    for key in preferred_keys:
        if key in pairs:
            return pairs[key]

    # Fallback to first available parsed value.
    return next(iter(pairs.values()), text)


def _pretty_missing_label(name: str, schema: str, identifier: str) -> str:
    """Prefer human-readable schema/identifier over verbose dependency descriptors."""
    for candidate in (schema, identifier, name):
        if candidate:
            break
    else:
        return "Unknown"

    text = candidate.strip()
    if "=" in text:
        text = _extract_ref_value(
            text,
            (
                "id.schemaname",
                "schemaname",
                "id.connectionreferenceid.connectionreferencelogicalname",
                "connectionreferenceid.connectionreferencelogicalname",
                "id.connectionreferencelogicalname",
                "connectionreferencelogicalname",
                "id.environmentvariabledefinitionid.schemaname",
                "environmentvariabledefinitionid.schemaname",
                "id.workflowid.workflowid",
                "workflowid.workflowid",
                "id.msdyn_aimodelid.msdyn_aimodelid",
                "msdyn_aimodelid.msdyn_aimodelid",
                "id.uniquename",
                "id.name",
            ),
        )
    return text or "Unknown"


# ── solution.xml parser ───────────────────────────────────────────────────────


def _parse_solution_xml(sol_path: Path) -> tuple[dict, list[_Component], list[_MissingDep]]:
    """Parse solution.xml. Returns (metadata_dict, components, missing_deps)."""
    metadata: dict = {
        "solution_name": "",
        "solution_display": "",
        "version": "1.0.0.0",
        "managed": False,
        "publisher": "",
    }
    components: list[_Component] = []
    missing: list[_MissingDep] = []

    try:
        root = ET.parse(sol_path).getroot()
    except Exception:
        return metadata, components, missing
    if root is None:
        return metadata, components, missing

    manifest = root.find("SolutionManifest")
    if manifest is None:
        return metadata, components, missing

    metadata["solution_name"] = manifest.findtext("UniqueName") or ""
    desc_node = manifest.find("Descriptions/Description")
    metadata["solution_display"] = (desc_node.get("description") or "") if desc_node is not None else ""
    if not metadata["solution_display"]:
        metadata["solution_display"] = metadata["solution_name"]

    metadata["version"] = manifest.findtext("Version") or "1.0.0.0"
    metadata["managed"] = (manifest.findtext("Managed") or "0") == "1"
    metadata["publisher"] = manifest.findtext("Publisher/UniqueName") or ""

    # Root components (the actual solution contents)
    rc_el = manifest.find("RootComponents")
    if rc_el is not None:
        for rc in rc_el.findall("RootComponent"):
            try:
                tc = int(rc.get("type") or "0")
            except ValueError:
                continue
            if tc == 0:
                continue
            components.append(
                _Component(
                    type_code=tc,
                    comp_id=rc.get("id") or "",
                    schema_name=rc.get("schemaName") or "",
                )
            )

    # Missing dependencies (required but not present in this ZIP)
    miss_el = manifest.find("MissingDependencies")
    if miss_el is not None:
        for md in miss_el.findall("MissingDependency"):
            req = md.find("Required")
            dep = md.find("Dependent")
            if req is None:
                continue
            rt, rt_name = _parse_missing_type(req.get("type") or "")
            rname = _first_attr(req, ["displayName", "parentDisplayName", "name"])
            rschema = _first_attr(req, ["schemaName", "id.schemaname"])
            rid = _first_attr(
                req,
                [
                    "id",
                    "id.schemaname",
                    "id.uniquename",
                    "id.msdyn_uniquename",
                    "id.name",
                ],
            )
            rsolution = _first_attr(req, ["solution"])
            rpackage = (req.findtext("package") or "").strip()

            dt, dt_name = _parse_missing_type((dep.get("type") or "") if dep is not None else "")
            dname = _first_attr(dep, ["displayName", "parentDisplayName", "name"])
            dschema = _first_attr(dep, ["schemaName", "id.schemaname"])
            did = _first_attr(
                dep,
                [
                    "id",
                    "id.schemaname",
                    "id.uniquename",
                    "id.msdyn_uniquename",
                    "id.name",
                ],
            )
            dep_id = _first_attr(dep, ["id"]) if dep is not None else ""
            missing.append(
                _MissingDep(
                    rt,
                    rt_name,
                    _pretty_missing_label(rname, rschema, rid),
                    rschema,
                    rid,
                    rsolution,
                    rpackage,
                    dt,
                    dt_name,
                    _pretty_missing_label(dname, dschema, did),
                    dschema,
                    did,
                    dep_id,
                )
            )

    return metadata, components, missing


# ── Display-name enrichment from component files ──────────────────────────────


def _enrich_from_files(components: list[_Component], work_dir: Path) -> None:
    """Fill in missing display names from artefact files where possible."""
    by_schema: dict[str, _Component] = {c.schema_name.lower(): c for c in components if c.schema_name}

    def _set(comp: _Component, name: str) -> None:
        if name and not comp.display_name:
            comp.display_name = name.strip()

    # Bots → configuration.json
    bots_dir = work_dir / "bots"
    if bots_dir.is_dir():
        for bot_dir in bots_dir.iterdir():
            if not bot_dir.is_dir():
                continue
            cfg = bot_dir / "configuration.json"
            if cfg.exists():
                try:
                    data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
                    name = data.get("DisplayName") or data.get("displayName") or ""
                    schema = bot_dir.name.lower()
                    if schema in by_schema:
                        _set(by_schema[schema], name)
                    else:
                        for c in components:
                            if c.type_code == 430 and not c.display_name:
                                _set(c, name)
                                break
                except Exception:
                    pass

    # Botcomponents → botcomponent.xml
    botcomp_dir = work_dir / "botcomponents"
    if botcomp_dir.is_dir():
        for comp_dir in botcomp_dir.iterdir():
            if not comp_dir.is_dir():
                continue
            xml_path = comp_dir / "botcomponent.xml"
            if xml_path.exists():
                try:
                    xroot = ET.parse(xml_path).getroot()
                    if xroot is None:
                        continue
                    name = xroot.findtext("name") or xroot.findtext("displayname") or ""
                    schema = comp_dir.name.lower()
                    if schema in by_schema:
                        _set(by_schema[schema], name)
                except Exception:
                    pass

    # Connection references → folder name as label
    cr_dir = work_dir / "connectionreferences"
    if cr_dir.is_dir():
        for item in cr_dir.iterdir():
            if not item.is_dir():
                continue
            schema = item.name.lower()
            if schema in by_schema:
                _set(by_schema[schema], item.name)

    # Environment variable definitions → folder name
    ev_dir = work_dir / "environmentvariabledefinitions"
    if ev_dir.is_dir():
        for item in ev_dir.iterdir():
            if not item.is_dir():
                continue
            schema = item.name.lower()
            if schema in by_schema:
                _set(by_schema[schema], item.name)

    # Workflows → try JSON displayName
    wf_dir = work_dir / "Workflows"
    if wf_dir.is_dir():
        flow_by_guid: dict[str, _Component] = {}
        for c in components:
            if c.type_code != 30:
                continue
            gid = _normalize_guid(c.comp_id) or _normalize_guid(c.schema_name)
            if gid:
                flow_by_guid[gid] = c

        for wf_file in wf_dir.iterdir():
            if not wf_file.is_file():
                continue
            schema = wf_file.stem.lower()
            guid = _extract_guid(schema)
            if schema in by_schema:
                try:
                    data = json.loads(wf_file.read_text(encoding="utf-8", errors="replace"))
                    name = (data.get("properties") or {}).get("displayName") or data.get("name") or ""
                    _set(by_schema[schema], name)
                except Exception:
                    pass
            if guid and guid in flow_by_guid:
                comp = flow_by_guid[guid]
                try:
                    data = json.loads(wf_file.read_text(encoding="utf-8", errors="replace"))
                    name = (data.get("properties") or {}).get("displayName") or data.get("name") or ""
                    if not name and "-" in wf_file.stem:
                        name = wf_file.stem.rsplit("-", 1)[0].replace("_", " ")
                    _set(comp, name)
                except Exception:
                    if "-" in wf_file.stem:
                        _set(comp, wf_file.stem.rsplit("-", 1)[0].replace("_", " "))


# ── Mermaid helpers ───────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    """Sanitise a string for use inside a Mermaid double-quoted label."""
    if not text:
        return ""
    return text.replace('"', "'").replace("\n", " ").replace("\r", "").strip()[:140]


def _truncate_middle(text: str, max_len: int = 52) -> str:
    """Compact very long labels while preserving both prefix and suffix context."""
    clean = (text or "").strip()
    if max_len < 5:
        return clean[:max_len]
    if len(clean) <= max_len:
        return clean
    keep = max_len - 1
    left = keep // 2
    right = keep - left
    return f"{clean[:left]}…{clean[-right:]}"


def _node(nid: str, label: str, shape: str = "rect") -> str:
    """Return a Mermaid node definition line (indented 4 spaces)."""
    esc_label = _esc(label)
    if shape == "stadium":
        return f'    {nid}(["{esc_label}"])'
    if shape == "diamond":
        return f'    {nid}{{"{esc_label}"}}'
    return f'    {nid}["{esc_label}"]'


# ── Mermaid diagram builder ───────────────────────────────────────────────────


def _build_mermaid(
    metadata: dict,
    components: list[_Component],
    missing: list[_MissingDep],
    detailed_missing_map: bool = False,
) -> str:
    lines: list[str] = [
        '%%{init: {"flowchart": {"nodeSpacing": 40, "rankSpacing": 55, "diagramPadding": 8}, "themeVariables": {"fontSize": "14px"}} }%%',
        "flowchart TD",
    ]

    # ── Classify components ────────────────────────────────────────────────────
    agents = [c for c in components if c.type_code == 430]
    bot_comps = [c for c in components if c.type_code in (431, 432)]
    flows = [c for c in components if c.type_code == 30]
    conn_refs = [c for c in components if c.type_code in (10066, 400)]
    env_vars = [c for c in components if c.type_code == 44]
    canvas_apps = [c for c in components if c.type_code in (29, 300)]
    tables = [c for c in components if c.type_code == 1]
    known_types = {430, 431, 432, 30, 10066, 400, 44, 29, 300, 1}
    others = [c for c in components if c.type_code not in known_types]

    sol_label = _esc(metadata.get("solution_display") or metadata.get("solution_name") or "Solution")
    sol_version = _esc(metadata.get("version") or "")
    managed_str = "Managed" if metadata.get("managed") else "Unmanaged"

    # Map comp stripped_id → mermaid node ID (for missing dep edge lookup)
    id_to_nid: dict[str, str] = {}

    # ── Solution subgraph ──────────────────────────────────────────────────────
    lines.append(f'    subgraph SOL["{sol_label}  ·  v{sol_version}  ({managed_str})"]')
    lines.append("        direction TB")

    # Agent node(s)
    agent_nids: list[str] = []
    for i, ag in enumerate(agents):
        nid = f"AGT{i}"
        agent_nids.append(nid)
        if ag.stripped_id:
            id_to_nid[ag.stripped_id] = nid
        lbl = f"🤖 {_esc(_truncate_middle(ag.label, 54))}"
        lines.append(f'        {nid}["{lbl}"]')

    # Bot components collapsed into one summary node
    bc_nid: str | None = None
    if bot_comps:
        bc_nid = "BCTOPICS"
        cnt = len(bot_comps)
        lines.append(f'        {bc_nid}["💬 {cnt} Bot Component{"s" if cnt != 1 else ""}"]')

    # Cloud flows — show individually up to _MAX_INDIVIDUAL, else summarise
    flow_nids: list[str] = []
    if flows:
        if len(flows) <= _MAX_INDIVIDUAL:
            for i, f in enumerate(flows):
                nid = f"FLW{i}"
                flow_nids.append(nid)
                if f.stripped_id:
                    id_to_nid[f.stripped_id] = nid
                lbl = f"⚡ {_esc(_truncate_middle(f.label, 54))}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "FLWS"
            flow_nids.append(nid)
            for f in flows:
                if f.stripped_id:
                    id_to_nid[f.stripped_id] = nid
            lines.append(f'        {nid}["⚡ {len(flows)} Cloud Flows"]')

    # Connection references
    cr_nids: list[str] = []
    if conn_refs:
        if len(conn_refs) <= _MAX_INDIVIDUAL:
            for i, cr in enumerate(conn_refs):
                nid = f"CR{i}"
                cr_nids.append(nid)
                if cr.stripped_id:
                    id_to_nid[cr.stripped_id] = nid
                lbl = f"🔗 {_esc(_truncate_middle(cr.label, 54))}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "CRS"
            cr_nids.append(nid)
            for cr in conn_refs:
                if cr.stripped_id:
                    id_to_nid[cr.stripped_id] = nid
            lines.append(f'        {nid}["🔗 {len(conn_refs)} Connection References"]')

    # Environment variables
    ev_nids: list[str] = []
    if env_vars:
        if len(env_vars) <= _MAX_INDIVIDUAL:
            for i, ev in enumerate(env_vars):
                nid = f"EV{i}"
                ev_nids.append(nid)
                if ev.stripped_id:
                    id_to_nid[ev.stripped_id] = nid
                lbl = f"⚙️ {_esc(_truncate_middle(ev.label, 54))}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "EVS"
            ev_nids.append(nid)
            lines.append(f'        {nid}["⚙️ {len(env_vars)} Environment Variables"]')

    # Canvas apps
    ca_nids: list[str] = []
    if canvas_apps:
        if len(canvas_apps) <= _MAX_INDIVIDUAL:
            for i, ca in enumerate(canvas_apps):
                nid = f"CA{i}"
                ca_nids.append(nid)
                if ca.stripped_id:
                    id_to_nid[ca.stripped_id] = nid
                lbl = f"📱 {_esc(_truncate_middle(ca.label, 54))}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "CAS"
            ca_nids.append(nid)
            lines.append(f'        {nid}["📱 {len(canvas_apps)} Canvas Apps"]')

    # Tables
    tbl_nids: list[str] = []
    if tables:
        if len(tables) <= _MAX_INDIVIDUAL:
            for i, t in enumerate(tables):
                nid = f"TBL{i}"
                tbl_nids.append(nid)
                if t.stripped_id:
                    id_to_nid[t.stripped_id] = nid
                lbl = f"🗃 {_esc(_truncate_middle(t.label, 54))}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "TBLS"
            tbl_nids.append(nid)
            lines.append(f'        {nid}["🗃 {len(tables)} Tables"]')

    # All other component types — one summary node per type group
    if others:
        type_buckets: dict[int, list[_Component]] = defaultdict(list)
        for o in others:
            type_buckets[o.type_code].append(o)
        for ti, (tc, items) in enumerate(sorted(type_buckets.items())):
            type_name, _ = _type_info(tc)
            nid = f"OTH{ti}"
            if len(items) == 1:
                short_label = _truncate_middle(items[0].label, 40)
                lbl = f"📦 {_esc(short_label)} ({type_name})"
            else:
                lbl = f"📦 {len(items)} {type_name}s"
            lines.append(f'        {nid}["{lbl}"]')

    lines.append("    end")  # close SOL subgraph

    # ── Missing dependencies map (Dependent -> Required) ─────────────────────
    required_seen: set[str] = set()
    required_unique: list[_MissingDep] = []
    for m in missing:
        if m.dedup_key not in required_seen:
            required_seen.add(m.dedup_key)
            required_unique.append(m)

    relation_seen: set[str] = set()
    relation_unique: list[_MissingDep] = []
    for m in missing:
        if m.relation_key not in relation_seen:
            relation_seen.add(m.relation_key)
            relation_unique.append(m)

    miss_key_to_nid: dict[str, str] = {}
    dep_key_to_nid: dict[str, str] = {}
    use_detailed_missing_map = detailed_missing_map or len(relation_unique) <= _MAX_DETAILED_MISSING_RELATIONS
    if relation_unique:
        lines.append('    subgraph MISS["⚠️ Missing Dependency Map  (Dependent -> Required)"]')
        lines.append("        direction LR")
        if use_detailed_missing_map:
            lines.append('        subgraph MISS_DEP["Dependent Components in this solution"]')
            lines.append("            direction TB")
            for i, m in enumerate(relation_unique):
                dep_key = (m.dep_schema or m.dep_identifier or m.dep_name).lower()
                if dep_key in dep_key_to_nid:
                    continue
                dnid = f"MDEP_SRC{i}"
                dep_key_to_nid[dep_key] = dnid
                dep_type = _type_info(m.dep_type)[0] if m.dep_type > 0 else (m.dep_type_name or "Component")
                dep_name_short = _truncate_middle(m.dep_name, 42)
                dlabel = f"{_esc(dep_name_short)} ({_esc(dep_type)})"
                lines.append(f'            {dnid}["{dlabel}"]')
            lines.append("        end")

            lines.append('        subgraph MISS_REQ["Required Components missing in target environment"]')
            lines.append("            direction TB")
            for i, m in enumerate(required_unique):
                rnid = f"MDEP_REQ{i}"
                miss_key_to_nid[m.dedup_key] = rnid
                req_label = m.req_name or m.req_schema or m.req_identifier
                req_name_short = _truncate_middle(req_label, 42)
                lbl = f"❌ {_esc(req_name_short)} ({_esc(m.type_label)})"
                lines.append(f'            {rnid}["{lbl}"]')
            lines.append("        end")
        else:
            dep_count = len({(m.dep_schema or m.dep_identifier or m.dep_name).lower() for m in relation_unique})
            summary_nid = "MDEP_SUM"
            lines.append(
                f'        {summary_nid}["⚠️ Aggregated view: {len(relation_unique)} dependency relations from {dep_count} dependents"]'
            )
            for i, m in enumerate(required_unique[:_MAX_DETAILED_REQUIRED_NODES]):
                rnid = f"MDEP_REQ{i}"
                miss_key_to_nid[m.dedup_key] = rnid
                req_label = m.req_name or m.req_schema or m.req_identifier
                req_name_short = _truncate_middle(req_label, 42)
                lbl = f"❌ {_esc(req_name_short)} ({_esc(m.type_label)})"
                lines.append(f'        {rnid}["{lbl}"]')
                lines.append(f"        {summary_nid} -.->|requires| {rnid}")
            hidden = len(required_unique) - _MAX_DETAILED_REQUIRED_NODES
            if hidden > 0:
                lines.append(f'        MDEP_MORE["+ {hidden} more required components"]')
                lines.append(f"        {summary_nid} -.-> MDEP_MORE")
        lines.append("    end")

    # ── Edges ──────────────────────────────────────────────────────────────────
    for aid in agent_nids:
        if bc_nid:
            lines.append(f"    {aid} --> {bc_nid}")
        for fid in flow_nids:
            lines.append(f"    {aid} --> {fid}")
        for evid in ev_nids:
            lines.append(f"    {aid} --> {evid}")
        for caid in ca_nids:
            lines.append(f"    {aid} --> {caid}")

    # Flows → connection references
    for fid in flow_nids:
        for crid in cr_nids:
            lines.append(f"    {fid} --> {crid}")

    # Missing dependency relation edges: dependent -> required
    if use_detailed_missing_map:
        for m in relation_unique:
            mnid = miss_key_to_nid.get(m.dedup_key)
            dkey = (m.dep_schema or m.dep_identifier or m.dep_name).lower()
            dnid = dep_key_to_nid.get(dkey)
            if dnid and mnid:
                lines.append(f"    {dnid} -.->|requires| {mnid}")

    # If dependent ID maps to an already known component node, connect it as context.
    if use_detailed_missing_map:
        for m in relation_unique:
            dep_id_clean = m.dep_id.lower()
            source = id_to_nid.get(dep_id_clean)
            dkey = (m.dep_schema or m.dep_identifier or m.dep_name).lower()
            dnid = dep_key_to_nid.get(dkey)
            if source and dnid:
                lines.append(f"    {source} -.->|dependency| {dnid}")

    # ── Node styles ────────────────────────────────────────────────────────────
    for i in range(len(agents)):
        lines.append(f"    style AGT{i} fill:#0078d4,color:white,stroke:#005a9e,stroke-width:2px")
    if bc_nid:
        lines.append(f"    style {bc_nid} fill:#deecf9,color:#201f1e,stroke:#0078d4")
    if len(flows) <= _MAX_INDIVIDUAL:
        for i in range(len(flows)):
            lines.append(f"    style FLW{i} fill:#e8f4e8,color:#0a5c0a,stroke:#107c10")
    elif flows:
        lines.append("    style FLWS fill:#e8f4e8,color:#0a5c0a,stroke:#107c10")
    if len(conn_refs) <= _MAX_INDIVIDUAL:
        for i in range(len(conn_refs)):
            lines.append(f"    style CR{i} fill:#f3e5f5,color:#4a108a,stroke:#8764b8")
    elif conn_refs:
        lines.append("    style CRS fill:#f3e5f5,color:#4a108a,stroke:#8764b8")
    if len(env_vars) <= _MAX_INDIVIDUAL:
        for i in range(len(env_vars)):
            lines.append(f"    style EV{i} fill:#fff4ce,color:#4d3800,stroke:#d29200")
    elif env_vars:
        lines.append("    style EVS fill:#fff4ce,color:#4d3800,stroke:#d29200")
    if len(canvas_apps) <= _MAX_INDIVIDUAL:
        for i in range(len(canvas_apps)):
            lines.append(f"    style CA{i} fill:#fce8e8,color:#601010,stroke:#d13438")
    elif canvas_apps:
        lines.append("    style CAS fill:#fce8e8,color:#601010,stroke:#d13438")
    for nid in dep_key_to_nid.values():
        lines.append(f"    style {nid} fill:#fff4ce,color:#4d3800,stroke:#d29200,stroke-dasharray:3 3")
    for nid in miss_key_to_nid.values():
        lines.append(f"    style {nid} fill:#fde7e9,color:#a4262c,stroke:#a4262c,stroke-dasharray:5 5")
    if not use_detailed_missing_map and relation_unique:
        lines.append("    style MDEP_SUM fill:#fff4ce,color:#4d3800,stroke:#d29200,stroke-width:2px")
        if len(required_unique) > _MAX_DETAILED_REQUIRED_NODES:
            lines.append("    style MDEP_MORE fill:#f3f2f1,color:#605e5c,stroke:#8a8886,stroke-dasharray:3 3")

    return "\n".join(lines)


# ── Markdown summary builder ──────────────────────────────────────────────────


def _build_summary_md(
    metadata: dict,
    components: list[_Component],
    missing: list[_MissingDep],
) -> str:
    sol_name = metadata.get("solution_display") or metadata.get("solution_name") or "Unknown"
    version = metadata.get("version") or "1.0.0.0"
    managed = "**Managed** ✔" if metadata.get("managed") else "Unmanaged"
    publisher = metadata.get("publisher") or "—"

    # De-duplicate missing required components and relations
    seen: set[str] = set()
    unique_missing: list[_MissingDep] = []
    for m in missing:
        if m.dedup_key not in seen:
            seen.add(m.dedup_key)
            unique_missing.append(m)

    rel_seen: set[str] = set()
    unique_relations: list[_MissingDep] = []
    for m in missing:
        if m.relation_key not in rel_seen:
            rel_seen.add(m.relation_key)
            unique_relations.append(m)

    # Tally by type
    type_counts: dict[int, int] = defaultdict(int)
    for c in components:
        type_counts[c.type_code] += 1
    relation_total = len(unique_relations)

    lines: list[str] = [
        f"## Solution: {sol_name}",
        "",
        f"- Version: `{version}`",
        f"- State: {managed}",
        f"- Publisher: `{publisher}`",
        f"- Total Components: **{len(components)}**",
        f"- Missing Dependencies: **{len(unique_missing)}**",
        "",
        "### Component Breakdown",
        "",
    ]

    if relation_total > _MAX_DETAILED_MISSING_RELATIONS:
        lines += [
            "> ℹ️ Dependency diagram is shown in an aggregated mode for readability due to high relation count.",
            "",
        ]

    if type_counts:
        for tc, cnt in sorted(type_counts.items(), key=lambda x: (-x[1], x[0])):
            type_name, _ = _type_info(tc)
            lines.append(f"- {type_name}: **{cnt}**")
    else:
        lines.append("- _No RootComponents in solution.xml_")

    if unique_missing:
        lines += [
            "",
            "### Missing Dependencies",
            "",
            "> ⚠️ These components are required by this solution but are not included in the ZIP. "
            "They must exist in the target environment before import succeeds.",
            "",
        ]
        for m in unique_missing:
            type_name = m.type_label
            dep_ref = f"`{m.dep_id[:8]}…`" if m.dep_id else "—"
            req = m.req_name or m.req_schema
            lines.append(f"- `{req}` ({type_name}) · referenced by dependent {dep_ref}")
        lines += [
            "",
            "### Dependency Relations",
            "",
            "_Detailed relations are shown in the table below the diagram for better readability._",
        ]
    else:
        lines += [
            "",
            "> ✅ **No missing dependencies detected** — all required components appear to be "
            "included in this solution or have no external dependencies.",
        ]

    return "\n".join(lines)


def _build_relation_rows(missing: list[_MissingDep]) -> list[dict]:
    """Build a de-duplicated, UI-friendly relation row list for tabular rendering."""
    relation_seen: set[str] = set()
    rows: list[dict] = []
    for m in missing:
        if m.relation_key in relation_seen:
            continue
        relation_seen.add(m.relation_key)
        dep_type = _type_info(m.dep_type)[0] if m.dep_type > 0 else (m.dep_type_name or "Component")
        dep_type = _friendly_botcomponent_type(m.dep_schema or m.dep_name, dep_type)
        req_type = m.type_label
        req_type = _friendly_botcomponent_type(m.req_schema or m.req_name, req_type)
        rows.append(
            {
                "dependent": _truncate_middle(_friendly_component_name(m.dep_name, m.dep_schema, m.dep_identifier), 64),
                "dependent_type": dep_type,
                "required": _truncate_middle(_friendly_component_name(m.req_name, m.req_schema, m.req_identifier), 64),
                "required_type": req_type,
                "source": m.req_solution or m.req_package or "Active",
            }
        )
    return rows


def _build_component_rows(components: list[_Component]) -> list[dict]:
    """Build a readable component inventory from all discovered component sources."""
    rows: list[dict] = []
    for c in components:
        if c.type_name_override:
            type_name = c.type_name_override
        else:
            type_name, _group = _type_info(c.type_code)
        group = c.group_override or _type_info(c.type_code)[1]
        group_label = _GROUP_LABELS.get(group, _GROUP_LABELS["other"])[1]
        rows.append(
            {
                "name": _truncate_middle(_friendly_component_name(c.label, c.schema_name, c.comp_id), 72),
                "schema": _truncate_middle(c.schema_name or "—", 72),
                "type": type_name,
                "type_code": str(c.type_code),
                "group": group_label,
                "kind": _truncate_middle(c.kind_hint or "—", 44),
                "source": c.source_hint or "solution.xml",
            }
        )
    rows.sort(key=lambda r: (r["type"].lower(), r["name"].lower()))
    return rows


def analyze_deps_zip_bytes_report(zip_bytes: bytes, detailed_diagram: bool = False) -> dict:
    """Analyze solution ZIP and return a structured dependency report.

    Returns keys:
      - ``summary_markdown``: textual overview
      - ``mermaid``: diagram source
      - ``relation_rows``: de-duplicated rows for table rendering
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                safe_extractall(zf, work_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError("Uploaded file is not a valid ZIP archive.") from exc

        sol_path = work_dir / "solution.xml"
        if not sol_path.exists():
            raise ValueError("No solution.xml found — this does not appear to be a Power Platform solution export.")

        metadata, components, missing = _parse_solution_xml(sol_path)
        discovered = _discover_components_from_artifacts(work_dir)
        components = _merge_components(components, discovered)
        _enrich_from_files(components, work_dir)
        asset_relation_rows = _build_asset_relation_rows(work_dir)

        if not components and not missing:
            raise ValueError(
                "No components were discovered from solution.xml or artifact folders (e.g., bots/, botcomponents/)."
            )

        return {
            "summary_markdown": _build_summary_md(metadata, components, missing),
            "mermaid": _build_mermaid(metadata, components, missing, detailed_missing_map=detailed_diagram),
            "relation_rows": _merge_relation_rows(_build_relation_rows(missing), asset_relation_rows),
            "component_rows": _build_component_rows(components),
        }


# ── Public API ────────────────────────────────────────────────────────────────


def analyze_deps_zip_bytes(zip_bytes: bytes) -> list[dict]:
    """Analyze a Power Platform solution ZIP and return dependency segments.

    Returns a list of render segments compatible with ``viz_segments``:
    ``[{"type": "text", "content": markdown}, {"type": "mermaid", "content": mermaid}]``

    Raises ``ValueError`` for clearly invalid input (not a ZIP, no solution.xml).
    """
    report = analyze_deps_zip_bytes_report(zip_bytes, detailed_diagram=False)
    return [
        {"type": "text", "content": report["summary_markdown"]},
        {"type": "mermaid", "content": report["mermaid"]},
    ]
