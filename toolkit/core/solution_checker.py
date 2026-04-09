"""Solution Checker — static analysis for Power Platform Copilot Studio solution exports.

Mirrors the intent of the Power Platform Solution Checker (pac solution check) but
focuses on Copilot Studio agent-specific rules that the generic checker does not cover.

Rules are grouped into five categories:

  - Solution   : solution.xml metadata health
  - Agent      : bot configuration.json settings
  - Topics     : topic coverage and quality
  - Knowledge  : knowledge sources and capabilities
  - Security   : security and injection risks

Check parameters, patterns, required system topics, and rule message templates are
loaded from ``solution_checks.yaml`` (co-located with this module). Edit that file
to update check behaviour without touching Python code.

Returns a structured result dict suitable for storing in Reflex state.
"""

from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path

import defusedxml.ElementTree as ET
import yaml as _yaml  # type: ignore[import-untyped]

from toolkit.core.renamer import safe_extractall

try:
    _YAML_AVAILABLE = True
except Exception:  # pragma: no cover
    _YAML_AVAILABLE = True  # yaml is a hard dependency; always available


# ── Category labels ────────────────────────────────────────────────────────────

CATEGORIES: list[str] = ["Solution", "Agent", "Topics", "Knowledge", "Security", "Dependencies"]

_CAT_ICONS: dict[str, str] = {
    "Solution": "file-text",
    "Agent": "bot",
    "Topics": "list",
    "Knowledge": "database",
    "Security": "shield-alert",
    "Dependencies": "link",
}


# ── Load solution_checks.yaml config ──────────────────────────────────────────

_CHECKS_CONFIG_PATH = Path(__file__).parent / "solution_checks.yaml"


def _load_checks_config() -> dict:
    """Load and return the solution checks configuration from solution_checks.yaml."""
    try:
        raw = _CHECKS_CONFIG_PATH.read_text(encoding="utf-8")
        config = _yaml.safe_load(raw)
        if not isinstance(config, dict):  # pragma: no cover
            raise ValueError("solution_checks.yaml must contain a top-level mapping")
        return config
    except FileNotFoundError as exc:  # pragma: no cover
        raise FileNotFoundError(
            f"solution_checks.yaml not found at {_CHECKS_CONFIG_PATH}. This file is required by the solution checker."
        ) from exc


_CHECKS_CONFIG: dict = _load_checks_config()

# ── Derived constants from YAML config ────────────────────────────────────────

_PARAMS: dict = _CHECKS_CONFIG.get("parameters", {})

# System topics that every production agent should have
# Loaded from required_system_topics in solution_checks.yaml.
# Each entry: trigger → {label, rule_id, missing_outcome}
_REQUIRED_SYSTEM_TOPICS: dict[str, dict] = _CHECKS_CONFIG.get("required_system_topics", {})

# Trigger kinds treated as system topics (not counted towards user-topic totals)
_SYSTEM_TOPIC_TRIGGERS: set[str] = set(_CHECKS_CONFIG.get("system_topic_triggers", []))

# Compiled regex patterns from YAML (all injection patterns use IGNORECASE)
_INJECTION_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in _CHECKS_CONFIG.get("injection_patterns", [])]

# Secret patterns include their own inline (?i) flags where needed
_SECRET_PATTERNS: list[re.Pattern] = [re.compile(p) for p in _CHECKS_CONFIG.get("secret_patterns", [])]

# Rule definitions: rule_id → {category, outcomes: {outcome_name: {severity, title, detail}}}
_RULES: dict[str, dict] = _CHECKS_CONFIG.get("rules", {})


# ── Internal helpers ───────────────────────────────────────────────────────────


def _read_xml(path: Path, *tags: str) -> dict[str, str]:
    """Return {tag: text} from an XML file; empty string on any parse failure."""
    try:
        root = ET.parse(path).getroot()
        return {tag: root.findtext(tag) or "" for tag in tags}
    except Exception:
        return {tag: "" for tag in tags}


def _load_yaml(path: Path) -> dict:
    """Load a Power Platform YAML 'data' file; return {} on any failure."""
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        # Fix common PP YAML quirks
        raw = raw.replace("\t", "    ")
        raw = re.sub(r"^(\s*)(@[a-zA-Z0-9_.]+)(\s*:)", r'\1"\2"\3', raw, flags=re.MULTILINE)
        raw = re.sub(
            r"(:\s+)(@[^\n]+)$",
            lambda m: m.group(1) + '"' + m.group(2) + '"',
            raw,
            flags=re.MULTILINE,
        )
        result = _yaml.safe_load(raw)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _rule(rule_id: str, outcome: str, **kwargs: object) -> dict:
    """Build a result dict from the YAML rule definition.

    Looks up ``rule_id`` and ``outcome`` in the loaded ``_RULES`` config,
    formats title/detail templates with ``kwargs``, and returns a result dict
    suitable for inclusion in the check results list.
    """
    rule_def = _RULES.get(rule_id, {})
    outcome_def = rule_def.get("outcomes", {}).get(outcome, {})
    severity = outcome_def.get("severity", "info")
    category = rule_def.get("category", "")
    title_tpl: str = outcome_def.get("title", rule_id)
    detail_tpl: str = outcome_def.get("detail", "")
    try:
        title = title_tpl.format_map(kwargs)
    except (KeyError, ValueError):
        title = title_tpl
    try:
        detail = detail_tpl.format_map(kwargs)
    except (KeyError, ValueError):
        detail = detail_tpl
    return {"rule_id": rule_id, "category": category, "title": title, "severity": severity, "detail": detail}


# ── Dependency type lookup (used by _check_dependencies) ──────────────────────

_DEP_TYPE_CODES: dict[str, int] = {
    "connectionreference": 10066,
    "environmentvariable": 44,
    "environmentvariabledefinition": 44,
    "cloudflow": 30,
    "workflow": 30,
    "canvasapp": 300,
    "bot": 430,
    "botcomponent": 431,
}

_DEP_TYPE_NAMES: dict[int, str] = {
    1: "Table",
    30: "Cloud Flow",
    44: "Environment Variable",
    300: "Canvas App",
    400: "Custom Connector",
    401: "AI Model",
    430: "Copilot Studio Agent",
    431: "Bot Component",
    10066: "Connection Reference",
}


def _dep_type_name(raw: str) -> str:
    """Return a human-readable type label for a dependency type value."""
    if raw.isdigit():
        return _DEP_TYPE_NAMES.get(int(raw), f"Component ({raw})")
    normalized = re.sub(r"[^a-z0-9]", "", raw.lower())
    code = _DEP_TYPE_CODES.get(normalized)
    if code:
        return _DEP_TYPE_NAMES.get(code, raw)
    return raw or "Unknown"


# ── Rule implementations ───────────────────────────────────────────────────────


def _check_solution_xml(work_dir: Path) -> list[dict]:
    results: list[dict] = []
    sol_path = work_dir / "solution.xml"

    if not sol_path.exists():
        results.append(_rule("SOL001", "missing"))
        # No point running further solution checks
        return results

    try:
        root = ET.parse(sol_path).getroot()
    except Exception as exc:
        results.append(_rule("SOL001", "unparseable", error=str(exc)))
        return results

    results.append(_rule("SOL001", "pass"))

    # SOL002 — Publisher prefix not "new" (default publisher)
    manifest = root.find("SolutionManifest")
    if manifest is not None:
        prefix = (manifest.findtext("Publisher/CustomizationPrefix") or "").strip().lower()
        if prefix in ("new", "default", ""):
            results.append(_rule("SOL002", "warn", prefix=prefix or "empty"))
        else:
            results.append(_rule("SOL002", "pass", prefix=prefix))

    # SOL003 — Version is still 1.0.0.0
    version = (manifest.findtext("Version") if manifest is not None else None) or ""
    if version == "1.0.0.0":
        results.append(_rule("SOL003", "warn"))
    elif version:
        results.append(_rule("SOL003", "pass", version=version))

    # SOL004 — Solution description
    if manifest is not None:
        desc_node = manifest.find("Descriptions/Description")
        desc = (desc_node.get("description") or "").strip() if desc_node is not None else ""
        if not desc:
            results.append(_rule("SOL004", "warn"))
        else:
            results.append(_rule("SOL004", "pass", desc=desc))

    # SOL005 — Managed vs unmanaged
    managed = (manifest.findtext("Managed") if manifest is not None else None) or "0"
    if managed == "1":
        results.append(_rule("SOL005", "managed"))
    else:
        results.append(_rule("SOL005", "unmanaged"))

    return results


def _check_agent_config(work_dir: Path, schema: str) -> list[dict]:  # noqa: C901
    results: list[dict] = []
    config_path = work_dir / "bots" / schema / "configuration.json"

    if not config_path.exists():
        results.append(_rule("AGT001", "no_config", schema=schema))
        return results

    try:
        import json

        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        results.append(_rule("AGT001", "unparseable", schema=schema, error=str(exc)))
        return results

    # AGT001 — Agent has a description (pulled from gpt.default/botcomponent.xml)
    gpt_xml_path = work_dir / "botcomponents" / f"{schema}.gpt.default" / "botcomponent.xml"
    if gpt_xml_path.exists():
        fields = _read_xml(gpt_xml_path, "description")
        desc = fields.get("description", "").strip()
        if desc:
            results.append(_rule("AGT001", "pass", desc=desc))
        else:
            results.append(_rule("AGT001", "warn"))
    else:
        results.append(_rule("AGT001", "no_gpt", schema=schema))

    # AGT002 — Content moderation level
    ai_settings = config.get("aISettings", {}) or {}
    moderation = (ai_settings.get("contentModeration") or "").strip()
    if moderation.lower() in ("none", "off", "disabled", ""):
        results.append(_rule("AGT002", "fail", moderation=moderation or "not set"))
    elif moderation.lower() == "low":
        results.append(_rule("AGT002", "warn"))
    elif moderation:
        results.append(_rule("AGT002", "pass", moderation=moderation))

    # AGT003 — useModelKnowledge risk
    use_model_knowledge = bool(ai_settings.get("useModelKnowledge", False))
    # Check if grounding rules appear in instructions
    gpt_data_path = work_dir / "botcomponents" / f"{schema}.gpt.default" / "data"
    gpt_data = _load_yaml(gpt_data_path)
    instructions = gpt_data.get("instructions") or ""
    has_grounding = bool(
        re.search(
            r"\bground(ed|ing)?\b|\bexclusively from\b|\bonly (from|based on)\b|\bsearch result\b",
            instructions,
            re.I,
        )
    )

    if use_model_knowledge and not has_grounding:
        results.append(_rule("AGT003", "warn"))
    elif use_model_knowledge and has_grounding:
        results.append(_rule("AGT003", "pass_grounded"))
    else:
        results.append(_rule("AGT003", "pass_disabled"))

    # AGT004 — Recognizer type (Generative AI is modern best practice)
    recognizer = config.get("recognizer", {}) or {}
    recognizer_kind = recognizer.get("$kind", "")
    if "GenerativeAI" in recognizer_kind or "Generative" in recognizer_kind:
        results.append(_rule("AGT004", "pass", recognizer_kind=recognizer_kind))
    elif recognizer_kind:
        results.append(_rule("AGT004", "warn", recognizer_kind=recognizer_kind))

    # AGT005 — publishOnImport
    publish_on_import = config.get("publishOnImport", None)
    if publish_on_import is True:
        results.append(_rule("AGT005", "auto_publish"))
    elif publish_on_import is False:
        results.append(_rule("AGT005", "manual_publish"))

    # AGT006 — isAgentConnectable (exposes agent as a plugin/connector)
    is_connectable = config.get("isAgentConnectable", False)
    if is_connectable:
        results.append(_rule("AGT006", "warn"))
    else:
        results.append(_rule("AGT006", "pass"))

    # AGT007 — Authentication mode
    auth_settings = config.get("authSettings", {}) or {}
    auth_mode = (
        auth_settings.get("authMode") or auth_settings.get("authType") or ""
    ).strip().lower()
    if not auth_mode or auth_mode in ("none", "no_auth", "nonauthenticated"):
        results.append(_rule("AGT007", "no_auth"))
    elif auth_mode in ("aad", "azuread", "microsoftaad", "azureaad", "teamssso"):
        results.append(_rule("AGT007", "aad"))
    elif "oauth" in auth_mode or auth_mode == "generic":
        results.append(_rule("AGT007", "oauth2"))
    else:
        results.append(_rule("AGT007", "manual", auth_mode=auth_mode))

    # AGT008 — Multi-agent orchestration (other agents used as tools)
    botcomponents_dir = work_dir / "botcomponents"
    agent_tool_names: list[str] = []
    if botcomponents_dir.exists():
        for comp_dir in sorted(botcomponents_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            parts = folder.split(".", 2)
            # Agent-tool components: belong to this agent (.agent. marker) and reference
            # a different agent schema (the 3rd part is not "default")
            if (
                len(parts) >= 3
                and parts[0] == schema
                and parts[1] == "agent"
                and parts[2].lower() != "default"
            ):
                xml_path = comp_dir / "botcomponent.xml"
                name = parts[2]
                if xml_path.exists():
                    fields = _read_xml(xml_path, "name")
                    name = fields.get("name") or name
                agent_tool_names.append(name)

    # Normalize for deterministic, testable output: de-duplicate and sort case-insensitively.
    unique_agent_tool_names = sorted(dict.fromkeys(agent_tool_names), key=str.lower) if agent_tool_names else []

    if unique_agent_tool_names:
        names_str = ", ".join(f"'{n}'" for n in unique_agent_tool_names[:5])
        if len(unique_agent_tool_names) > 5:
            names_str += f" and {len(unique_agent_tool_names) - 5} more"
        results.append(
            _rule(
                "AGT008",
                "has_agent_tools",
                count=len(unique_agent_tool_names),
                names=names_str,
            )
        )
    else:
        results.append(_rule("AGT008", "pass"))

    return results


def _check_topics(work_dir: Path, schema: str) -> list[dict]:
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    if not botcomponents_dir.exists():
        results.append(_rule("TOP000", "no_botcomponents"))
        return results

    # Collect all topic components for this bot schema
    topics: list[dict] = []  # list of {folder, display_name, trigger_kind, state, has_actions}
    for comp_dir in sorted(botcomponents_dir.iterdir()):
        if not comp_dir.is_dir():
            continue
        folder = comp_dir.name
        if folder.startswith("mspva_"):
            continue
        parts = folder.split(".", 2)
        if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
            continue

        xml_path = comp_dir / "botcomponent.xml"
        if not xml_path.exists():
            continue
        fields = _read_xml(xml_path, "name", "statecode")
        name = fields.get("name") or folder
        state = "active" if fields.get("statecode", "0") == "0" else "inactive"

        data = _load_yaml(comp_dir / "data")
        begin = data.get("beginDialog") or {}
        trigger_kind = begin.get("kind") or ""
        has_actions = bool(begin.get("actions"))
        topics.append(
            {
                "folder": folder,
                "display_name": name,
                "trigger_kind": trigger_kind,
                "state": state,
                "has_actions": has_actions,
            }
        )

    # TOP001 / TOP002 — Required system topics
    found_triggers = {t["trigger_kind"] for t in topics}
    for trigger, topic_cfg in _REQUIRED_SYSTEM_TOPICS.items():
        label = topic_cfg["label"]
        rule_id = topic_cfg.get("rule_id", "TOP002")
        if trigger in found_triggers:
            results.append(_rule(rule_id, "pass", label=label, trigger=trigger))
        else:
            missing_outcome = topic_cfg.get("missing_outcome", "warn")
            results.append(_rule(rule_id, missing_outcome, label=label, trigger=trigger))

    # TOP003 — Inactive topics
    inactive = [t for t in topics if t["state"] == "inactive"]
    if inactive:
        names_list = ", ".join(t["display_name"] for t in inactive[:5])
        suffix = f" and {len(inactive) - 5} more" if len(inactive) > 5 else ""
        results.append(_rule("TOP003", "warn", count=len(inactive), names=f"{names_list}{suffix}"))
    else:
        results.append(_rule("TOP003", "pass"))

    # TOP004 — Empty topics (no actions in beginDialog)
    empty = [t for t in topics if not t["has_actions"] and t["trigger_kind"]]
    if empty:
        names_list = ", ".join(t["display_name"] for t in empty[:5])
        suffix = f" and {len(empty) - 5} more" if len(empty) > 5 else ""
        results.append(_rule("TOP004", "warn", count=len(empty), names=f"{names_list}{suffix}"))
    else:
        results.append(_rule("TOP004", "pass"))

    # TOP005 — Large topic count
    very_high = int(_PARAMS.get("topic_very_high_count_threshold", 100))
    high = int(_PARAMS.get("topic_high_count_threshold", 50))
    user_topics = [t for t in topics if t["trigger_kind"] and t["trigger_kind"] not in _SYSTEM_TOPIC_TRIGGERS]
    user_count = len(user_topics)
    if user_count > very_high:
        results.append(_rule("TOP005", "very_high", count=user_count, very_high_threshold=very_high))
    elif user_count > high:
        results.append(_rule("TOP005", "high", count=user_count))
    else:
        results.append(_rule("TOP005", "pass", count=user_count))

    return results


def _check_knowledge(work_dir: Path, schema: str, config: dict) -> list[dict]:
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    # KNO001 — Has at least one knowledge source
    knowledge_dirs: list[Path] = []
    if botcomponents_dir.exists():
        for comp_dir in botcomponents_dir.iterdir():
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            parts = folder.split(".", 2)
            if len(parts) >= 2 and parts[0] == schema and parts[1] in ("file", "knowledge", "entity"):
                knowledge_dirs.append(comp_dir)

    if knowledge_dirs:
        results.append(_rule("KNO001", "pass", count=len(knowledge_dirs)))
    else:
        results.append(_rule("KNO001", "info"))

    # KNO002 — Oversized file attachments
    max_mb = int(_PARAMS.get("max_knowledge_file_mb", 20))
    max_file_bytes = max_mb * 1024 * 1024
    large_files: list[tuple[str, int]] = []
    if botcomponents_dir.exists():
        for fdir in knowledge_dirs:
            filedata_dir = fdir / "filedata"
            if filedata_dir.exists():
                for f in filedata_dir.iterdir():
                    if f.is_file():
                        size = f.stat().st_size
                        if size > max_file_bytes:
                            large_files.append((f.name, size))

    if large_files:
        details = "; ".join(f"{name} ({sz // 1024 // 1024} MB)" for name, sz in large_files[:5])
        results.append(_rule("KNO002", "warn", count=len(large_files), details=details, max_mb=max_mb))
    else:
        results.append(_rule("KNO002", "pass", max_mb=max_mb))

    # KNO003 — Semantic search enabled
    ai_settings = config.get("aISettings", {}) or {}
    semantic_search = bool(ai_settings.get("isSemanticSearchEnabled", False))
    if semantic_search:
        results.append(_rule("KNO003", "pass"))
    else:
        results.append(_rule("KNO003", "warn"))

    # KNO004 — Web browsing enabled
    web_browsing = False
    settings = config.get("settings", {}) or {}
    for _key, sv in settings.items():
        if isinstance(sv, dict):
            caps = (sv.get("content") or {}).get("capabilities") or {}
            if caps.get("webBrowsing"):
                web_browsing = True
                break

    if web_browsing:
        results.append(_rule("KNO004", "warn"))
    else:
        results.append(_rule("KNO004", "pass"))

    return results


def _check_dependencies(work_dir: Path) -> list[dict]:  # noqa: C901
    """Check DEP001-DEP004: connection references, env vars, missing deps, cloud flows."""
    results: list[dict] = []
    import json as _json

    # DEP001 — Connection references (connectionreferences/ folder or solution.xml type 10066)
    cr_schemas: list[str] = []
    cr_dir = work_dir / "connectionreferences"
    if cr_dir.is_dir():
        for item in sorted(cr_dir.iterdir()):
            if item.is_dir():
                cr_schemas.append(item.name)

    if not cr_schemas:
        sol_path = work_dir / "solution.xml"
        if sol_path.exists():
            try:
                root = ET.parse(sol_path).getroot()
                manifest = root.find("SolutionManifest")
                if manifest is not None:
                    rc_el = manifest.find("RootComponents")
                    for rc in (rc_el.findall("RootComponent") if rc_el is not None else []):
                        try:
                            if int(rc.get("type", "0")) == 10066:
                                sname = (rc.get("schemaName") or "").strip()
                                if sname and sname not in cr_schemas:
                                    cr_schemas.append(sname)
                        except (ValueError, AttributeError):
                            pass
            except Exception:
                pass

    if cr_schemas:
        names_str = ", ".join(f"`{s}`" for s in cr_schemas[:6])
        if len(cr_schemas) > 6:
            names_str += f" and {len(cr_schemas) - 6} more"
        results.append(_rule("DEP001", "has_refs", count=len(cr_schemas), names=names_str))
    else:
        results.append(_rule("DEP001", "none"))

    # DEP002 — Environment variables (environmentvariabledefinitions/ folder)
    ev_schemas: list[str] = []
    ev_dir = work_dir / "environmentvariabledefinitions"
    if ev_dir.is_dir():
        for item in sorted(ev_dir.iterdir()):
            if item.is_dir():
                # Prefer display name from the XML if available
                xml_path = item / "environmentvariabledefinition.xml"
                display = item.name
                if xml_path.exists():
                    try:
                        xroot = ET.parse(xml_path).getroot()
                        dn = xroot.findtext("displayname") or xroot.get("displayname") or ""
                        if dn:
                            display = dn.strip()
                    except Exception:
                        pass
                ev_schemas.append(display)

    if ev_schemas:
        names_str = ", ".join(f"`{s}`" for s in ev_schemas[:6])
        if len(ev_schemas) > 6:
            names_str += f" and {len(ev_schemas) - 6} more"
        results.append(_rule("DEP002", "has_vars", count=len(ev_schemas), names=names_str))
    else:
        results.append(_rule("DEP002", "none"))

    # DEP003 — Missing dependencies from solution.xml <MissingDependencies>
    missing_items: list[tuple[str, str]] = []
    sol_path = work_dir / "solution.xml"
    if sol_path.exists():
        try:
            root = ET.parse(sol_path).getroot()
            manifest = root.find("SolutionManifest")
            if manifest is not None:
                miss_el = manifest.find("MissingDependencies")
                if miss_el is not None:
                    seen_keys: set[str] = set()
                    for md in miss_el.findall("MissingDependency"):
                        req = md.find("Required")
                        if req is None:
                            continue
                        req_type_raw = req.get("type") or ""
                        req_name = (
                            req.get("displayName")
                            or req.get("schemaName")
                            or req.get("name")
                            or "Unknown"
                        )
                        # Simplify key=value style names
                        if "=" in req_name:
                            for part in req_name.split(","):
                                k, _, v = part.partition("=")
                                if any(x in k.lower() for x in ("name", "schema", "logicalname")):
                                    clean = v.strip().strip("{}")
                                    if clean:
                                        req_name = clean
                                    break
                        key = f"{req_type_raw}:{req_name.lower()}"
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        missing_items.append((req_name, _dep_type_name(req_type_raw)))
        except Exception:
            pass

    if missing_items:
        names_str = "; ".join(f"`{n}` ({t})" for n, t in missing_items[:5])
        if len(missing_items) > 5:
            names_str += f" and {len(missing_items) - 5} more"
        results.append(_rule("DEP003", "has_missing", count=len(missing_items), names=names_str))
    else:
        results.append(_rule("DEP003", "pass"))

    # DEP004 — Cloud flows in Workflows/ folder
    flow_names: list[str] = []
    wf_dir = work_dir / "Workflows"
    if wf_dir.is_dir():
        for wf_file in sorted(wf_dir.iterdir()):
            if not wf_file.is_file() or wf_file.suffix.lower() != ".json":
                continue
            name = ""
            try:
                data = _json.loads(wf_file.read_text(encoding="utf-8", errors="replace"))
                name = (data.get("properties") or {}).get("displayName") or data.get("name") or ""
            except Exception:
                pass
            if not name and "-" in wf_file.stem:
                name = wf_file.stem.rsplit("-", 1)[0].replace("_", " ")
            if name:
                flow_names.append(name)

    if flow_names:
        names_str = ", ".join(f"`{n}`" for n in flow_names[:5])
        if len(flow_names) > 5:
            names_str += f" and {len(flow_names) - 5} more"
        results.append(_rule("DEP004", "has_flows", count=len(flow_names), names=names_str))
    else:
        results.append(_rule("DEP004", "none"))

    return results


def _check_security(work_dir: Path, schema: str) -> list[dict]:  # noqa: C901
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    # SEC001 — Prompt injection patterns in topic data files
    injection_hits: list[tuple[str, str]] = []  # (topic_name, matched_pattern)
    if botcomponents_dir.exists():
        for comp_dir in sorted(botcomponents_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            if folder.startswith("mspva_"):
                continue
            parts = folder.split(".", 2)
            if len(parts) < 2 or parts[0] != schema:
                continue
            data_path = comp_dir / "data"
            if not data_path.exists():
                continue
            try:
                text = data_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pat in _INJECTION_PATTERNS:
                m = pat.search(text)
                if m:
                    xml_fields = _read_xml(comp_dir / "botcomponent.xml", "name")
                    name = xml_fields.get("name") or folder
                    injection_hits.append((name, m.group(0)[:60]))
                    break  # one hit per component is enough

    if injection_hits:
        details_str = "; ".join(f"'{n}' (matched: \"{s}\")" for n, s in injection_hits[:3])
        suffix = f" and {len(injection_hits) - 3} more" if len(injection_hits) > 3 else ""
        results.append(_rule("SEC001", "fail", count=len(injection_hits), details=f"{details_str}{suffix}"))
    else:
        results.append(_rule("SEC001", "pass"))

    # SEC002 — Hardcoded secrets / credentials in topic data
    secret_hits: list[tuple[str, str]] = []
    if botcomponents_dir.exists():
        for comp_dir in sorted(botcomponents_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            if folder.startswith("mspva_"):
                continue
            parts = folder.split(".", 2)
            if len(parts) < 2 or parts[0] != schema:
                continue
            data_path = comp_dir / "data"
            if not data_path.exists():
                continue
            try:
                text = data_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pat in _SECRET_PATTERNS:
                m = pat.search(text)
                if m:
                    xml_fields = _read_xml(comp_dir / "botcomponent.xml", "name")
                    name = xml_fields.get("name") or folder
                    # Only flag high-confidence patterns (skip long base64 if it's in known-safe contexts)
                    matched = m.group(0)
                    # Skip base64 blobs that appear inside filedata (legitimate binary encoding)
                    if len(matched) > 100 and "filedata" in str(comp_dir):
                        continue
                    secret_hits.append((name, matched[:40]))
                    break

    if secret_hits:
        names_str = ", ".join(f"'{n}'" for n, _ in secret_hits[:3])
        suffix = f" and {len(secret_hits) - 3} more" if len(secret_hits) > 3 else ""
        results.append(_rule("SEC002", "warn", count=len(secret_hits), names=f"{names_str}{suffix}"))
    else:
        results.append(_rule("SEC002", "pass"))

    # SEC003 — File analysis enabled (can process uploaded files from users)
    config_path = work_dir / "bots" / schema / "configuration.json"
    file_analysis_enabled = False
    if config_path.exists():
        try:
            import json

            config = json.loads(config_path.read_text(encoding="utf-8"))
            ai_settings = config.get("aISettings", {}) or {}
            file_analysis_enabled = bool(ai_settings.get("isFileAnalysisEnabled", False))
        except Exception:
            pass

    if file_analysis_enabled:
        results.append(_rule("SEC003", "warn"))
    else:
        results.append(_rule("SEC003", "pass"))

    return results


# ── Main entry point ───────────────────────────────────────────────────────────


def check_solution_zip(zip_bytes: bytes) -> dict:
    """Run all solution checks against a Power Platform solution ZIP.

    Args:
        zip_bytes: Raw bytes of the solution ZIP file.

    Returns:
        A dict with keys:
          - ``results``: list of check result dicts (rule_id, category, title, severity, detail)
          - ``agent_name``: detected agent display name
          - ``solution_name``: detected solution unique name
          - ``pass_count``, ``warn_count``, ``fail_count``, ``info_count``: summary counts
          - ``error``: non-empty string if the ZIP could not be parsed at all
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        return {
            "results": [],
            "agent_name": "",
            "solution_name": "",
            "pass_count": 0,
            "warn_count": 0,
            "fail_count": 0,
            "info_count": 0,
            "error": f"Invalid ZIP file: {exc}",
        }

    # Ensure it looks like a solution ZIP
    has_solution = any(n == "bots" or n.startswith("bots/") for n in names)
    if not has_solution:
        return {
            "results": [],
            "agent_name": "",
            "solution_name": "",
            "pass_count": 0,
            "warn_count": 0,
            "fail_count": 0,
            "info_count": 0,
            "error": (
                "Uploaded file does not appear to be a Power Platform solution ZIP "
                "(no bots/ directory found). Solution check requires a solution export."
            ),
        }

    results: list[dict] = []
    agent_name = ""
    solution_name = ""
    bot_config: dict = {}

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, work_dir)

        # Detect bot schema
        bots_dir = work_dir / "bots"
        bot_folders = [d for d in bots_dir.iterdir() if d.is_dir()] if bots_dir.exists() else []
        schema = bot_folders[0].name if bot_folders else ""

        # Detect agent / solution names for the summary header
        if schema:
            gpt_xml = work_dir / "botcomponents" / f"{schema}.gpt.default" / "botcomponent.xml"
            if gpt_xml.exists():
                agent_name = _read_xml(gpt_xml, "name").get("name", schema)
            else:
                agent_name = schema

            config_path = work_dir / "bots" / schema / "configuration.json"
            if config_path.exists():
                try:
                    import json

                    bot_config = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        sol_xml = work_dir / "solution.xml"
        if sol_xml.exists():
            try:
                root = ET.parse(sol_xml).getroot()
                manifest = root.find("SolutionManifest")
                if manifest is not None:
                    solution_name = manifest.findtext("UniqueName") or ""
            except Exception:
                pass

        # ── Run all check groups ────────────────────────────────────────
        results.extend(_check_solution_xml(work_dir))
        if schema:
            results.extend(_check_agent_config(work_dir, schema))
            results.extend(_check_topics(work_dir, schema))
            results.extend(_check_knowledge(work_dir, schema, bot_config))
            results.extend(_check_security(work_dir, schema))
        else:
            results.append(_rule("AGT000", "no_schema"))
        results.extend(_check_dependencies(work_dir))

    pass_count = sum(1 for r in results if r["severity"] == "pass")
    warn_count = sum(1 for r in results if r["severity"] == "warning")
    fail_count = sum(1 for r in results if r["severity"] == "fail")
    info_count = sum(1 for r in results if r["severity"] == "info")

    _severity_order = {"fail": 0, "warning": 1, "info": 2, "pass": 3}
    results.sort(key=lambda r: _severity_order.get(r["severity"], 99))

    return {
        "results": results,
        "agent_name": agent_name,
        "solution_name": solution_name,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "info_count": info_count,
        "error": "",
    }
