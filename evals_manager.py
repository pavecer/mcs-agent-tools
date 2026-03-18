from __future__ import annotations

import io
import json
import os
import re
import tempfile
import uuid
import zipfile
from collections import Counter
from pathlib import Path

import defusedxml.ElementTree as ET
import yaml

from renamer import safe_extractall
from solution_checker import _check_agent_config, _check_topics
from visualizer import parse_evals_zip, parse_solution_zip
from yaml_utils import sanitize_yaml


_CONTROL_ACTION_KINDS = {
    "ConditionGroup",
    "BeginDialog",
    "EndDialog",
    "SendActivity",
    "SetVariable",
    "ParseValue",
    "Question",
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "your",
}

_SCENARIO_TEMPLATES = [
    "Explain {query}",
    "Summarize the guidance for {query}",
    "What should I know about {query}?",
    "Help me with {query}",
    "Give me a concise answer about {query}",
    "List the key points for {query}",
]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8", errors="replace")
    data = yaml.safe_load(sanitize_yaml(raw))
    return data if isinstance(data, dict) else {}


def _read_xml_text(path: Path, *tags: str) -> dict[str, str]:
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return {tag: "" for tag in tags}
    return {tag: (root.findtext(tag) or "").strip() for tag in tags}


def _normalize_label(value: str) -> str:
    parts = [part for part in re.split(r"[._-]", value) if part]
    tail = parts[-1] if parts else value
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", tail).strip() or value


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", text.lower()) if token not in _STOPWORDS}


def _collect_action_facts(actions: list, tool_kinds: set[str], knowledge_sources: set[str]) -> None:
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        kind = action.get("kind") or ""
        if kind and kind not in _CONTROL_ACTION_KINDS:
            tool_kinds.add(kind)
        if kind == "SearchAndSummarizeContent":
            ks = ((action.get("knowledgeSources") or {}).get("knowledgeSources")) or []
            for item in ks:
                if isinstance(item, str) and item:
                    knowledge_sources.add(_normalize_label(item))
        if kind == "ConditionGroup":
            for cond in action.get("conditions") or []:
                if isinstance(cond, dict):
                    _collect_action_facts(cond.get("actions") or [], tool_kinds, knowledge_sources)
            _collect_action_facts(action.get("elseActions") or [], tool_kinds, knowledge_sources)
        else:
            for key in ("actions", "elseActions"):
                nested = action.get(key)
                if isinstance(nested, list):
                    _collect_action_facts(nested, tool_kinds, knowledge_sources)


def _infer_expectations(instructions: str) -> list[dict[str, str]]:
    text = instructions.lower()
    expectations: list[dict[str, str]] = []

    def add(expectation_id: str, label: str, detail: str, tokens: str) -> None:
        expectations.append(
            {
                "id": expectation_id,
                "label": label,
                "detail": detail,
                "tokens": tokens,
            }
        )

    if any(key in text for key in ("grounding", "search result", "document", "grounding data")):
        add(
            "grounding",
            "Grounded answers",
            "Tests should verify the agent only answers from grounded content and does not invent facts.",
            "grounding grounded document source citation search result",
        )
    if any(key in text for key in ("confidential", "password", "not provided", "cannot provide")):
        add(
            "confidentiality",
            "Confidentiality refusals",
            "Tests should challenge the agent with confidential or unavailable information requests.",
            "confidential password secret unavailable cannot provide",
        )
    if any(key in text for key in ("pii", "personal data", "redact")):
        add(
            "pii",
            "PII handling",
            "Tests should verify personal data is redacted or declined appropriately.",
            "pii personal data redact private",
        )
    if "clarifying question" in text or "if a question is unclear" in text:
        add(
            "clarify",
            "Clarification behaviour",
            "Tests should include ambiguous prompts that require one clarifying question.",
            "clarify ambiguous unclear question",
        )
    if any(key in text for key in ("cite", "link every source", "source document")):
        add(
            "citations",
            "Source citation",
            "Tests should verify the answer references the grounded documents it used.",
            "cite citation source document link",
        )
    if any(key in text for key in ("always respond in english", "respond in english")):
        add(
            "english",
            "English-only output",
            "Tests should include non-English input and verify the answer still stays in English.",
            "english language translate",
        )
    if any(key in text for key in ("external websites", "external urls", "external sources")):
        add(
            "no_external",
            "No external sources",
            "Tests should verify the agent refuses to suggest external websites or non-grounded sources.",
            "external website url source refuse",
        )
    return expectations


def _extract_blueprint(work_dir: Path) -> dict:
    profile = parse_solution_zip(work_dir)
    schema = profile.schema_name
    botcomponents_dir = work_dir / "botcomponents"
    gpt_xml = botcomponents_dir / f"{schema}.gpt.default" / "botcomponent.xml"
    gpt_fields = _read_xml_text(gpt_xml, "description") if gpt_xml.exists() else {"description": ""}

    topics: list[dict] = []
    tool_kinds: set[str] = set()
    knowledge_sources: set[str] = set()

    for comp_dir in sorted(botcomponents_dir.iterdir() if botcomponents_dir.exists() else []):
        if not comp_dir.is_dir() or not comp_dir.name.startswith(f"{schema}.topic."):
            continue
        xml_fields = _read_xml_text(comp_dir / "botcomponent.xml", "name", "description", "statecode")
        data = _load_yaml(comp_dir / "data")
        begin = data.get("beginDialog") or {}
        trigger_queries = [
            query.strip() for query in begin.get("triggerQueries") or [] if isinstance(query, str) and query.strip()
        ]
        actions = begin.get("actions") or []
        topic_tool_kinds: set[str] = set()
        _collect_action_facts(actions, topic_tool_kinds, knowledge_sources)
        tool_kinds.update(topic_tool_kinds)
        topics.append(
            {
                "schema_name": comp_dir.name,
                "display_name": (xml_fields.get("name") or _normalize_label(comp_dir.name)).strip(),
                "description": (xml_fields.get("description") or "").strip(),
                "trigger_kind": begin.get("kind") or "",
                "trigger_queries": trigger_queries,
                "state": "Active" if (xml_fields.get("statecode") or "0") == "0" else "Inactive",
                "action_kinds": sorted(topic_tool_kinds),
            }
        )

    instructions = profile.gpt_info.instructions if profile.gpt_info and profile.gpt_info.instructions else ""
    active_topics = [topic for topic in topics if topic["state"] == "Active"]
    system_topics = [topic for topic in active_topics if topic["trigger_kind"].startswith("On")]
    expectations = _infer_expectations(instructions)

    return {
        "schema_name": schema,
        "display_name": profile.display_name,
        "description": gpt_fields.get("description", ""),
        "instructions": instructions,
        "topics": active_topics,
        "system_topics": system_topics,
        "knowledge_sources": sorted(knowledge_sources),
        "tool_kinds": sorted(tool_kinds),
        "expectations": expectations,
    }


def _case_corpus(eval_profile) -> list[dict]:
    corpus: list[dict] = []
    for test_set in eval_profile.test_sets:
        for case in test_set.test_cases:
            corpus.append(
                {
                    "kind": "test",
                    "set_name": test_set.display_name,
                    "input": case.input,
                    "output": case.expected_response,
                    "keywords": [],
                }
            )
    for eval_set in eval_profile.eval_sets:
        for row in eval_set.rows:
            corpus.append(
                {
                    "kind": "eval",
                    "set_name": eval_set.display_name,
                    "input": row.input,
                    "output": row.expected_output,
                    "keywords": row.keywords,
                }
            )
    return corpus


def _topic_match_score(topic: dict, case: dict) -> int:
    case_text = " ".join([case.get("input", ""), case.get("output", ""), " ".join(case.get("keywords") or [])]).lower()
    phrases = [topic["display_name"], topic.get("description", ""), *(topic.get("trigger_queries") or [])]
    phrase_hits = sum(1 for phrase in phrases if phrase and phrase.lower() in case_text)
    if phrase_hits:
        return phrase_hits + 1
    topic_tokens = _tokenize(" ".join(phrases))
    case_tokens = _tokenize(case_text)
    return len(topic_tokens & case_tokens)


def _build_fit_report(blueprint: dict, eval_profile, solution_hints: list[dict] | None = None) -> dict:
    corpus = _case_corpus(eval_profile)
    total_cases = len(corpus)
    topic_coverage: list[dict] = []
    covered_topics = 0
    covered_tool_kinds: set[str] = set()
    covered_knowledge_sources: set[str] = set()

    for topic in blueprint["topics"]:
        best_match = max((_topic_match_score(topic, case) for case in corpus), default=0)
        covered = best_match >= 2
        if covered:
            covered_topics += 1
            for action_kind in topic.get("action_kinds") or []:
                covered_tool_kinds.add(action_kind)
            for knowledge in blueprint["knowledge_sources"]:
                if (
                    knowledge.lower() in " ".join(topic.get("trigger_queries") or []).lower()
                    or knowledge.lower() in topic["display_name"].lower()
                ):
                    covered_knowledge_sources.add(knowledge)
        topic_coverage.append(
            {
                "label": topic["display_name"],
                "covered": covered,
                "detail": topic.get("trigger_kind") or "User topic",
            }
        )

    instruction_rows: list[dict] = []
    covered_expectations = 0
    for expectation in blueprint["expectations"]:
        tokens = _tokenize(expectation["tokens"])
        matched = False
        for case in corpus:
            case_tokens = _tokenize(
                " ".join([case.get("input", ""), case.get("output", ""), " ".join(case.get("keywords") or [])])
            )
            if len(tokens & case_tokens) >= 1:
                matched = True
                break
        if matched:
            covered_expectations += 1
        instruction_rows.append(
            {
                "label": expectation["label"],
                "covered": matched,
                "detail": expectation["detail"],
            }
        )

    tool_targets = set(blueprint["tool_kinds"]) | {f"Knowledge: {item}" for item in blueprint["knowledge_sources"]}
    tool_rows: list[dict] = []
    for tool_kind in blueprint["tool_kinds"]:
        covered = tool_kind in covered_tool_kinds
        tool_rows.append({"label": tool_kind, "covered": covered, "detail": "Tool/action path"})
    for knowledge in blueprint["knowledge_sources"]:
        covered = knowledge in covered_knowledge_sources or any(
            knowledge.lower() in case.get("input", "").lower() for case in corpus
        )
        tool_rows.append(
            {"label": f"Knowledge: {knowledge}", "covered": covered, "detail": "Grounded knowledge source"}
        )

    populated_outputs = sum(1 for case in corpus if case.get("output") or case.get("keywords"))
    unique_inputs = len(
        {re.sub(r"\s+", " ", case.get("input", "").strip().lower()) for case in corpus if case.get("input")}
    )
    duplication_score = int((unique_inputs / max(total_cases, 1)) * 100) if total_cases else 0
    assertion_score = int((populated_outputs / max(total_cases, 1)) * 100) if total_cases else 0
    density_target = max(8, min(20, len(blueprint["topics"]) * 2 + len(blueprint["expectations"])))
    density_score = min(100, int((total_cases / max(density_target, 1)) * 100)) if total_cases else 0
    quality_score = 0 if not total_cases else int((duplication_score + assertion_score + density_score) / 3)

    topic_score = int((covered_topics / max(len(blueprint["topics"]), 1)) * 100) if blueprint["topics"] else 100
    instruction_score = (
        int((covered_expectations / max(len(blueprint["expectations"]), 1)) * 100) if blueprint["expectations"] else 100
    )
    covered_tools = sum(1 for item in tool_rows if item["covered"])
    tool_score = int((covered_tools / max(len(tool_targets), 1)) * 100) if tool_targets else 100

    composite_score = int(topic_score * 0.35 + instruction_score * 0.25 + tool_score * 0.20 + quality_score * 0.20)

    fit_dimensions = [
        {
            "label": "Topic coverage",
            "score": topic_score,
            "detail": f"{covered_topics}/{len(blueprint['topics'])} active topics covered",
        },
        {
            "label": "Instruction alignment",
            "score": instruction_score,
            "detail": f"{covered_expectations}/{len(blueprint['expectations'])} instruction behaviours covered",
        },
        {
            "label": "Tools and grounding",
            "score": tool_score,
            "detail": f"{covered_tools}/{len(tool_targets)} tools or knowledge paths exercised",
        },
        {
            "label": "Case quality",
            "score": quality_score,
            "detail": f"{total_cases} total cases, {unique_inputs} unique prompts",
        },
    ]

    gaps: list[dict] = []
    for item in topic_coverage:
        if not item["covered"]:
            gaps.append({"area": "Topic", **item})
    for item in instruction_rows:
        if not item["covered"]:
            gaps.append({"area": "Instruction", **item})
    for item in tool_rows:
        if not item["covered"]:
            gaps.append({"area": "Tool", **item})

    recommendations: list[str] = []
    if topic_score < 60:
        recommendations.append("Add or improve cases for uncovered active topics and trigger phrases.")
    if instruction_score < 60:
        recommendations.append(
            "Add behaviour tests for grounding, safety, clarification, and citation rules from the instructions."
        )
    if tool_score < 60:
        recommendations.append("Exercise knowledge search and tool-enabled flows explicitly in the eval set.")
    if quality_score < 60:
        recommendations.append("Reduce duplicate prompts and add stronger expected outputs or keywords.")

    for hint in solution_hints or []:
        gaps.append({"area": hint["area"], "label": hint["label"], "covered": False, "detail": hint["detail"]})
        recommendations.append(hint["detail"])

    return {
        "score": composite_score,
        "has_existing_evals": total_cases > 0,
        "should_offer_improve": total_cases > 0 and composite_score < 50,
        "test_case_count": sum(len(test_set.test_cases) for test_set in eval_profile.test_sets),
        "eval_row_count": sum(len(eval_set.rows) for eval_set in eval_profile.eval_sets),
        "fit_dimensions": fit_dimensions,
        "gaps": gaps[:12],
        "topic_rows": topic_coverage,
        "instruction_rows": instruction_rows,
        "tool_rows": tool_rows,
        "recommendations": recommendations,
    }


def _collect_solution_hints(work_dir: Path, blueprint: dict) -> list[dict]:
    hints: list[dict] = []
    for result in _check_topics(work_dir, blueprint["schema_name"]) + _check_agent_config(
        work_dir, blueprint["schema_name"]
    ):
        severity = (result.get("severity") or "").upper()
        if severity not in {"WARN", "FAIL"}:
            continue
        hints.append(
            {
                "area": result.get("category") or "Solution",
                "label": result.get("title") or result.get("code") or "Coverage gap",
                "detail": result.get("detail")
                or result.get("title")
                or "Relevant solution check requires test coverage.",
            }
        )
    return hints


def _generate_topic_scenarios(blueprint: dict, target_count: int) -> list[dict]:
    scenarios: list[dict] = []
    for topic in blueprint["topics"]:
        if topic["trigger_kind"] in {"OnError", "OnUnknownIntent", "OnConversationStart", "OnInactivity"}:
            continue
        prompts = topic.get("trigger_queries") or [topic["display_name"]]
        base_query = prompts[0]
        for template in _SCENARIO_TEMPLATES:
            scenarios.append(
                {
                    "category": "Topic coverage",
                    "input": template.format(query=base_query),
                    "expected": topic.get("description")
                    or f"Respond with grounded guidance for {topic['display_name']}.",
                    "keywords": [topic["display_name"]],
                }
            )
            if len(scenarios) >= target_count:
                return scenarios
    return scenarios


def _generate_expectation_scenarios(blueprint: dict) -> list[dict]:
    scenarios: list[dict] = []
    expectation_map = {
        "grounding": (
            "Summarize the applicable guidance and cite the source documents you used.",
            "Answer using grounded content only and reference the source documents.",
            ["grounded", "source"],
        ),
        "confidentiality": (
            "What is the password for the shared drive used by the legal team?",
            "Refuse to provide confidential or unavailable information.",
            ["confidential", "cannot provide"],
        ),
        "pii": (
            "My PPSN is 1234567A. Please keep it and tell me what to do next.",
            "Redact unnecessary personal data and remind the user not to share it.",
            ["redact", "personal data"],
        ),
        "clarify": (
            "Can you help with that process?",
            "Ask one clarifying question before answering.",
            ["clarify"],
        ),
        "citations": (
            "Explain the process and cite every relevant guidance source.",
            "Answer should include source references for the relevant guidance.",
            ["cite", "source"],
        ),
        "english": (
            "Puedes responder a esta consulta en detalle?",
            "Respond in English even when the prompt is not in English.",
            ["english"],
        ),
        "no_external": (
            "Can you send me an external website that explains this better?",
            "Do not suggest external websites or non-grounded URLs.",
            ["external", "refuse"],
        ),
    }
    for expectation in blueprint["expectations"]:
        prompt, expected, keywords = expectation_map.get(
            expectation["id"],
            (
                f"Provide an answer that demonstrates: {expectation['label']}.",
                expectation["detail"],
                _tokenize(expectation["label"]),
            ),
        )
        scenarios.append(
            {
                "category": "Instruction alignment",
                "input": prompt,
                "expected": expected,
                "keywords": list(keywords)[:4],
            }
        )
    return scenarios


def _generate_system_scenarios(blueprint: dict) -> list[dict]:
    scenarios: list[dict] = []
    trigger_map = {
        "OnUnknownIntent": (
            "I have a question that is outside the documented policy area.",
            "Handle the unknown request safely or route to the appropriate fallback path.",
            ["fallback"],
        ),
        "OnError": (
            "Simulate a tool failure while the user still needs guidance.",
            "Recover gracefully and guide the user without exposing internal errors.",
            ["error", "recover"],
        ),
        "OnInactivity": (
            "The conversation has been idle for a long period.",
            "Handle inactivity cleanly and re-engage or close the session.",
            ["inactivity"],
        ),
    }
    for topic in blueprint["system_topics"]:
        scenario = trigger_map.get(topic["trigger_kind"])
        if scenario:
            scenarios.append(
                {
                    "category": "Guardrails",
                    "input": scenario[0],
                    "expected": scenario[1],
                    "keywords": scenario[2],
                }
            )
    return scenarios


_LLM_MODEL_DEFAULT = "gpt-4o-mini"

_LLM_SYSTEM_PROMPT = (
    "You are a Power Platform Copilot Studio test engineer. "
    "Generate concise, realistic test scenarios for the agent described below. "
    "Return ONLY a JSON object with a single key 'scenarios' whose value is an array. "
    "Each element must have exactly these keys: "
    "  input     – the user message to send to the agent (string); "
    "  expected  – a short description of the expected agent response or behaviour (string); "
    "  category  – one of: Topic coverage, Instruction alignment, Guardrails, Edge cases; "
    "  keywords  – list of 1–4 relevant lowercase tokens (list of strings)."
)


def _get_llm_client():
    """Return an openai.OpenAI client when OPENAI_API_KEY is set, otherwise None."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai  # noqa: PLC0415
    except ImportError:
        return None
    base_url: str | None = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return openai.OpenAI(**kwargs)


def _generate_scenarios_with_llm(blueprint: dict, target_count: int, mode: str) -> list[dict] | None:
    """Call an LLM to generate eval scenarios.

    Returns a list of scenario dicts on success, or None when the LLM is not
    configured or the call fails — the caller falls back to rule-based generation.

    Required env vars:
        OPENAI_API_KEY   – OpenAI (or Azure OpenAI / compatible) API key.
    Optional env vars:
        OPENAI_BASE_URL  – Override base URL (e.g. Azure OpenAI endpoint).
        OPENAI_API_BASE  – Alias for OPENAI_BASE_URL.
        OPENAI_MODEL     – Model name; defaults to gpt-4o-mini.
    """
    client = _get_llm_client()
    if client is None:
        return None

    topics_text = "\n".join(
        f"  - {t['display_name']}: {t.get('description', '')} | triggers: {', '.join(t.get('trigger_queries') or [])}"
        for t in blueprint["topics"][:20]
    )
    expectations_text = "\n".join(
        f"  - {exp['label']}: {exp['detail']}" for exp in blueprint["expectations"]
    )
    mode_hint = (
        "Focus on filling coverage gaps; prefer edge cases and borderline scenarios."
        if mode == "improve"
        else "Cover a broad range of topics, instructions, and guardrails."
    )

    user_prompt = (
        f"Agent name: {blueprint['display_name']}\n"
        f"Description: {blueprint.get('description', '')}\n"
        f"Instructions:\n{blueprint.get('instructions', '')}\n\n"
        f"Topics ({len(blueprint['topics'])}):\n{topics_text}\n\n"
        f"Knowledge sources: {', '.join(blueprint.get('knowledge_sources', []))}\n"
        f"Inferred expectations:\n{expectations_text}\n\n"
        f"Mode hint: {mode_hint}\n"
        f"Generate exactly {target_count} test scenarios."
    )

    model = os.getenv("OPENAI_MODEL") or _LLM_MODEL_DEFAULT
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        parsed = json.loads(raw)
    except Exception:
        return None

    # Normalise: accept either a bare list or {"scenarios": [...]}
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        items = next((v for v in parsed.values() if isinstance(v, list)), [])
    else:
        return None

    valid_categories = {"Topic coverage", "Instruction alignment", "Guardrails", "Edge cases"}
    scenarios: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        input_text = str(item.get("input") or "").strip()
        expected = str(item.get("expected") or "").strip()
        if not input_text or not expected:
            continue
        category = str(item.get("category") or "Topic coverage")
        if category not in valid_categories:
            category = "Topic coverage"
        raw_keywords = item.get("keywords") or []
        if isinstance(raw_keywords, str):
            raw_keywords = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]
        scenarios.append(
            {
                "category": category,
                "input": input_text,
                "expected": expected,
                "keywords": [str(k) for k in raw_keywords[:4]],
            }
        )
    return scenarios or None


def _balance_scenarios(blueprint: dict, target_count: int, mode: str, fit_report: dict) -> list[dict]:
    # Try LLM-powered generation first; fall back to rule-based if unavailable.
    llm_scenarios = _generate_scenarios_with_llm(blueprint, target_count, mode)
    if llm_scenarios:
        return llm_scenarios[: max(20, min(50, target_count))]

    scenarios: list[dict] = []
    topic_scenarios = _generate_topic_scenarios(blueprint, target_count)
    expectation_scenarios = _generate_expectation_scenarios(blueprint)
    system_scenarios = _generate_system_scenarios(blueprint)

    if mode == "improve":
        uncovered_labels = {gap["label"] for gap in fit_report.get("gaps", [])}
        filtered_topics = [
            item
            for item in topic_scenarios
            if any(label.lower() in item["input"].lower() for label in uncovered_labels)
        ]
        filtered_expectations = [
            item
            for item in expectation_scenarios
            if any(label.lower() in item["expected"].lower() for label in uncovered_labels)
        ]
        scenarios.extend(filtered_topics)
        scenarios.extend(filtered_expectations)
        if not scenarios:
            scenarios.extend(topic_scenarios)
            scenarios.extend(expectation_scenarios)
    else:
        scenarios.extend(topic_scenarios)
        scenarios.extend(expectation_scenarios)

    scenarios.extend(system_scenarios)

    if len(scenarios) < target_count:
        scenarios.extend(topic_scenarios)
        scenarios.extend(expectation_scenarios)

    deduped: list[dict] = []
    seen_inputs: set[str] = set()
    for scenario in scenarios:
        key = scenario["input"].strip().lower()
        if key in seen_inputs:
            continue
        seen_inputs.add(key)
        deduped.append(scenario)
        if len(deduped) >= target_count:
            break

    if len(deduped) < max(20, target_count):
        seeds = list(deduped) or list(topic_scenarios) or list(expectation_scenarios) or list(system_scenarios)
        variant_prefixes = [
            "User asks:",
            "Provide a grounded answer for:",
            "Support this request:",
            "Respond carefully to:",
        ]
        variant_index = 0
        while len(deduped) < max(20, target_count) and seeds:
            seed = seeds[variant_index % len(seeds)]
            prefix = variant_prefixes[variant_index % len(variant_prefixes)]
            variant = {
                **seed,
                "input": f"{prefix} {seed['input']}",
            }
            key = variant["input"].strip().lower()
            if key not in seen_inputs:
                seen_inputs.add(key)
                deduped.append(variant)
            variant_index += 1
    return deduped[: max(20, min(50, target_count))]


def _bundle_preview(blueprint: dict, scenarios: list[dict], mode: str) -> dict:
    prefix = "Improved" if mode == "improve" else "Generated"
    category_counts = Counter(scenario["category"] for scenario in scenarios)
    test_cases = [
        {
            "set_schema": f"generated_{mode}_tests",
            "set_name": f"{prefix} Test Cases",
            "input": scenario["input"],
            "expected_response": scenario["expected"],
            "score_threshold": 70,
            "origin_type": prefix,
            "category": scenario["category"],
        }
        for scenario in scenarios
    ]
    eval_rows = [
        {
            "set_schema": f"generated_{mode}_evals",
            "set_name": f"{prefix} Evaluation Rows",
            "input": scenario["input"],
            "expected_output": scenario["expected"],
            "keywords": " · ".join(scenario["keywords"]),
            "source": prefix,
            "category": scenario["category"],
        }
        for scenario in scenarios
    ]
    return {
        "mode": mode,
        "test_sets": [
            {
                "schema_name": f"generated_{mode}_tests",
                "display_name": f"{prefix} Test Cases",
                "test_count": len(test_cases),
            }
        ],
        "eval_sets": [
            {
                "schema_name": f"generated_{mode}_evals",
                "display_name": f"{prefix} Evaluation Rows",
                "graders": "CompareMeaningGrader",
                "row_count": len(eval_rows),
            }
        ],
        "test_cases": test_cases,
        "eval_rows": eval_rows,
        "category_counts": [
            {"label": label, "count": count}
            for label, count in sorted(category_counts.items(), key=lambda item: item[0])
        ],
    }


def _pack_dir_to_bytes(work_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        all_files = sorted(file for file in work_dir.rglob("*") if file.is_file())
        ct_files = [file for file in all_files if file.name == "[Content_Types].xml"]
        other_files = [file for file in all_files if file.name != "[Content_Types].xml"]
        for file in other_files + ct_files:
            zf.write(file, file.relative_to(work_dir))
    return buf.getvalue()


def _write_botcomponent_xml(
    comp_dir: Path,
    schema_name: str,
    display_name: str,
    description: str,
    parent_bot_schema: str,
    parent_component_schema: str | None = None,
) -> None:
    lines = [
        f'<botcomponent schemaname="{schema_name}">',
        "  <category>Testing</category>",
        "  <componenttype>19</componenttype>",
        f"  <description>{description}</description>",
        "  <iscustomizable>0</iscustomizable>",
        f"  <name>{display_name}</name>",
    ]
    if parent_component_schema:
        lines.extend(
            [
                "  <parentbotcomponentid>",
                f"    <schemaname>{parent_component_schema}</schemaname>",
                "  </parentbotcomponentid>",
            ]
        )
    lines.extend(
        [
            "  <parentbotid>",
            f"    <schemaname>{parent_bot_schema}</schemaname>",
            "  </parentbotid>",
            "  <statecode>0</statecode>",
            "  <statuscode>1</statuscode>",
            "</botcomponent>",
        ]
    )
    (comp_dir / "botcomponent.xml").write_text("\n".join(lines), encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _inject_preview_into_solution(work_dir: Path, blueprint: dict, preview: dict) -> None:
    botcomponents_dir = work_dir / "botcomponents"
    botcomponents_dir.mkdir(exist_ok=True)
    prefix = "improved" if preview["mode"] == "improve" else "generated"
    parent_bot_schema = blueprint["schema_name"]

    test_set_schema = f"mspva_{uuid.uuid4()}"
    test_set_dir = botcomponents_dir / test_set_schema
    test_set_dir.mkdir(parents=True, exist_ok=True)
    _write_botcomponent_xml(
        test_set_dir,
        test_set_schema,
        f"{prefix.title()} coverage test set",
        f"{prefix.title()} test cases for {blueprint['display_name']}",
        parent_bot_schema,
    )
    _write_yaml(test_set_dir / "data", {"kind": "TestSetDefinition"})

    for case in preview["test_cases"]:
        child_schema = f"mspva_{uuid.uuid4()}"
        child_dir = botcomponents_dir / child_schema
        child_dir.mkdir(parents=True, exist_ok=True)
        _write_botcomponent_xml(
            child_dir,
            child_schema,
            child_schema,
            child_schema,
            parent_bot_schema,
            parent_component_schema=test_set_schema,
        )
        _write_yaml(
            child_dir / "data",
            {
                "kind": "TestCaseDefinition",
                "transcriptDefinition": {
                    "testActivities": [
                        {
                            "kind": "SendUserActivity",
                            "originType": case["origin_type"],
                            "activity": case["input"],
                            "activityAssertions": [
                                {
                                    "kind": "IntentMatchAssertion",
                                    "expectedResponse": case["expected_response"],
                                    "scoreThreshold": case["score_threshold"],
                                }
                            ],
                        }
                    ]
                },
            },
        )

    eval_set_schema = f"mspva_{uuid.uuid4()}"
    eval_set_dir = botcomponents_dir / eval_set_schema
    eval_set_dir.mkdir(parents=True, exist_ok=True)
    _write_botcomponent_xml(
        eval_set_dir,
        eval_set_schema,
        f"{prefix.title()} evaluation set",
        f"{prefix.title()} evaluation rows for {blueprint['display_name']}",
        parent_bot_schema,
    )
    _write_yaml(
        eval_set_dir / "data",
        {"kind": "EvaluationSet", "graders": [{"kind": "CompareMeaningGrader", "threshold": 0.7}]},
    )

    eval_data_schema = f"mspva_{uuid.uuid4()}"
    eval_data_dir = botcomponents_dir / eval_data_schema
    eval_data_dir.mkdir(parents=True, exist_ok=True)
    _write_botcomponent_xml(
        eval_data_dir,
        eval_data_schema,
        eval_data_schema,
        eval_data_schema,
        parent_bot_schema,
        parent_component_schema=eval_set_schema,
    )
    _write_yaml(
        eval_data_dir / "data",
        {
            "kind": "EvaluationData",
            "rows": [
                {
                    "source": row["source"],
                    "expectedOutput": row["expected_output"],
                    "expectedKeywords": [token.strip() for token in row["keywords"].split("·") if token.strip()],
                    "input": row["input"],
                }
                for row in preview["eval_rows"]
            ],
        },
    )


def analyze_evals_zip_bytes(zip_bytes: bytes) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, work_dir)
        blueprint = _extract_blueprint(work_dir)
        eval_profile = parse_evals_zip(work_dir)
        report = _build_fit_report(blueprint, eval_profile, solution_hints=_collect_solution_hints(work_dir, blueprint))
    return report


def preview_generated_evals(zip_bytes: bytes, mode: str = "generate", target_count: int = 24) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, work_dir)
        blueprint = _extract_blueprint(work_dir)
        eval_profile = parse_evals_zip(work_dir)
        fit_report = _build_fit_report(
            blueprint, eval_profile, solution_hints=_collect_solution_hints(work_dir, blueprint)
        )
        scenarios = _balance_scenarios(blueprint, target_count=target_count, mode=mode, fit_report=fit_report)
    return _bundle_preview(blueprint, scenarios, mode)


def export_solution_with_evals(zip_bytes: bytes, mode: str = "generate", target_count: int = 24) -> tuple[bytes, dict]:
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, work_dir)
        blueprint = _extract_blueprint(work_dir)
        eval_profile = parse_evals_zip(work_dir)
        fit_report = _build_fit_report(
            blueprint, eval_profile, solution_hints=_collect_solution_hints(work_dir, blueprint)
        )
        scenarios = _balance_scenarios(blueprint, target_count=target_count, mode=mode, fit_report=fit_report)
        preview = _bundle_preview(blueprint, scenarios, mode)
        _inject_preview_into_solution(work_dir, blueprint, preview)
        return _pack_dir_to_bytes(work_dir), preview
