"""MCS Dynamic Planner Trace Analysis.

Extracts, assembles and quality-scores the trace events emitted by the
Copilot Studio Dynamic Planner during a conversation:

  DynamicPlanReceivedDebug     → user ask (plan level)
  DynamicPlanStepTriggered     → planner reasoning thought, step type
  DynamicPlanStepBindUpdate    → generated search query and keywords
  UniversalSearchToolTraceData → knowledge-source routing (candidate / output)
  DynamicPlanStepFinished      → retrieved documents, execution time, step state

Scoring uses deterministic lexical term-overlap (transparent and testable):
  - query_fidelity_pct   : % of normalised ask-terms found in generated query+keywords
  - item_hit_rate_pct    : % of returned documents whose name/URL contains ask terms
  - source_fidelity_pct  : % of candidate knowledge sources that returned results
  - overall_success_pct  : 45 × query_fidelity + 35 × item_hit_rate + 20 × source_fidelity

Text normalisation strips diacritics (NFKD → ASCII), lowercases, removes punctuation,
and filters English stop-words, so "Croí Cónaithe" and "croi conaithe" both reduce
to overlapping token sets for reliable matching.
"""

from __future__ import annotations

import re
import unicodedata

from toolkit.mcs.models import MCSPlannerAnalysis, MCSPlannerStepTrace, MCSSearchResultItem

# ── Text normalisation helpers ────────────────────────────────────────────────

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "am",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "down",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "me",
        "might",
        "more",
        "my",
        "no",
        "nor",
        "not",
        "of",
        "on",
        "or",
        "our",
        "out",
        "she",
        "should",
        "so",
        "than",
        "that",
        "the",
        "them",
        "then",
        "they",
        "this",
        "to",
        "up",
        "us",
        "was",
        "we",
        "were",
        "what",
        "which",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "after",
        "also",
        "before",
        "tell",
        "also",
    }
)

_MIN_TERM_LEN: int = 3


def _normalize(text: str) -> str:
    """Lowercase, strip diacritics (NFKD ASCII fold), collapse to letters/digits/spaces."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9\s]", " ", ascii_only.lower())


def _extract_terms(text: str) -> list[str]:
    """Return ordered, deduplicated content terms (min 3 chars, no stop words)."""
    seen: set[str] = set()
    result: list[str] = []
    for word in _normalize(text).split():
        if len(word) >= _MIN_TERM_LEN and word not in _STOP_WORDS and word not in seen:
            seen.add(word)
            result.append(word)
    return result


# ── Item scoring ──────────────────────────────────────────────────────────────


def _score_item(item: MCSSearchResultItem, query_terms: list[str]) -> float:
    """Return term-overlap fraction (0.0–1.0) between result item text and query terms."""
    if not query_terms:
        return 0.0
    haystack = _normalize(f"{item.name} {item.url or ''}")
    matched = sum(1 for t in query_terms if t in haystack)
    return matched / len(query_terms)


# ── Execution time parser ─────────────────────────────────────────────────────


def _parse_execution_time(raw: str | None) -> float:
    """Parse a .NET TimeSpan string 'H:MM:SS.ffffff' into milliseconds."""
    if not raw:
        return 0.0
    try:
        parts = raw.split(":")
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return (hours * 3600 + minutes * 60 + seconds) * 1000
    except (ValueError, IndexError):
        pass
    return 0.0


# ── Step quality scoring ──────────────────────────────────────────────────────


def _score_step(step: MCSPlannerStepTrace) -> None:
    """Compute all quality scores for a planner step (mutates step in-place).

    Scoring components
    ------------------
    query_fidelity_pct : % of normalised ask-terms found in generated query+keywords
    item_hit_rate_pct  : % of retrieved documents that contain at least one ask term
    source_fidelity_pct: % of candidate knowledge sources that returned results
    overall_success_pct: 45 × fidelity + 35 × item_hit + 20 × source_fidelity

    score_flags (string labels, never raw internal names in UI)
    -----------
    NO_RESULTS          — no documents returned
    TOP_RESULT_RELEVANT — first returned document score >= 0.3
    SOURCES_FILTERED    — some candidate sources were filtered out
    ALL_SOURCES_RETURNED— all candidate sources returned results
    HIGH_QUALITY        — overall >= 65 %
    PARTIAL_QUALITY     — overall 35–64 %
    LOW_QUALITY         — overall < 35 %
    """
    flags: list[str] = []

    ask_terms = _extract_terms(step.user_ask)
    gen_terms = _extract_terms(f"{step.search_query} {step.search_keywords}")
    # Combined term set used for item scoring (ask terms + generated query terms)
    all_query_terms: list[str] = list(dict.fromkeys([*ask_terms, *gen_terms]))

    # ── 1. Query generation fidelity ─────────────────────────────────────────
    step.ask_term_count = len(ask_terms)
    if ask_terms and gen_terms:
        gen_term_set = set(gen_terms)
        matched_in_gen = sum(1 for t in ask_terms if t in gen_term_set)
        step.query_matched_term_count = matched_in_gen
        step.query_fidelity_pct = round(matched_in_gen / len(ask_terms) * 100, 1)
    else:
        step.query_matched_term_count = 0
        step.query_fidelity_pct = 0.0

    # ── 2. Item hit rate ──────────────────────────────────────────────────────
    if step.result_items:
        matched_count = 0
        for item in step.result_items:
            score = _score_item(item, all_query_terms)
            item.relevance_score = round(score, 2)
            if score > 0.0:
                matched_count += 1
        step.matched_item_count = matched_count
        step.item_hit_rate_pct = round(matched_count / len(step.result_items) * 100, 1)
    else:
        flags.append("NO_RESULTS")
        step.item_hit_rate_pct = 0.0
        step.matched_item_count = 0

    # ── 3. Source coverage ────────────────────────────────────────────────────
    if step.knowledge_sources_candidate:
        step.source_fidelity_pct = round(
            len(step.knowledge_sources_output) / len(step.knowledge_sources_candidate) * 100, 1
        )
        if len(step.knowledge_sources_output) < len(step.knowledge_sources_candidate):
            flags.append("SOURCES_FILTERED")
        else:
            flags.append("ALL_SOURCES_RETURNED")
    else:
        step.source_fidelity_pct = 100.0  # no sources specified → no penalty

    # ── 4. Top result relevance ───────────────────────────────────────────────
    if step.result_items and step.result_items[0].relevance_score >= 0.3:
        flags.append("TOP_RESULT_RELEVANT")

    # ── 5. Weighted overall score ─────────────────────────────────────────────
    step.overall_success_pct = round(
        step.query_fidelity_pct * 0.45
        + step.item_hit_rate_pct * 0.35
        + step.source_fidelity_pct * 0.20,
        1,
    )

    if step.overall_success_pct >= 65.0:
        flags.append("HIGH_QUALITY")
    elif step.overall_success_pct >= 35.0:
        flags.append("PARTIAL_QUALITY")
    else:
        flags.append("LOW_QUALITY")

    step.score_flags = flags


# ── Main extraction function ──────────────────────────────────────────────────


def build_planner_analysis(activities: list[dict]) -> MCSPlannerAnalysis:
    """Extract Dynamic Planner trace events from activities and compute quality scores.

    Processes these event valueType values (in activity order per step):
      DynamicPlanReceivedDebug     → user ask (shared across all steps in the plan)
      DynamicPlanStepTriggered     → planner thought and step metadata
      DynamicPlanStepBindUpdate    → generated search query and keywords
      UniversalSearchToolTraceData → knowledge-source routing (candidate / output)
      DynamicPlanStepFinished      → retrieved documents, execution time, step state

    Returns an MCSPlannerAnalysis with one MCSPlannerStepTrace per planner step,
    all quality scores populated.
    """
    # plan_identifier → user ask text
    asks: dict[str, str] = {}
    # (plan_identifier, step_id) → MCSPlannerStepTrace
    steps_map: dict[tuple[str, str], MCSPlannerStepTrace] = {}
    # ordered insertion list for matching UniversalSearchToolTraceData (no step_id there)
    step_order: list[tuple[str, str]] = []

    for activity in activities:
        if activity.get("type") != "event":
            continue

        value_type = activity.get("valueType", "") or activity.get("name", "")
        value = activity.get("value", {}) or {}

        if value_type == "DynamicPlanReceivedDebug":
            plan_id = value.get("planIdentifier", "")
            ask = value.get("ask", "")
            if plan_id:
                asks[plan_id] = ask

        elif value_type == "DynamicPlanStepTriggered":
            plan_id = value.get("planIdentifier", "")
            step_id = value.get("stepId", "")
            if not plan_id or not step_id:
                continue
            key = (plan_id, step_id)
            step = MCSPlannerStepTrace(
                step_id=step_id,
                plan_identifier=plan_id,
                tool_id=value.get("taskDialogId", ""),
                step_type=value.get("type", ""),
                planner_thought=value.get("thought", ""),
                user_ask=asks.get(plan_id, ""),
            )
            steps_map[key] = step
            step_order.append(key)

        elif value_type == "DynamicPlanStepBindUpdate":
            plan_id = value.get("planIdentifier", "")
            step_id = value.get("stepId", "")
            key = (plan_id, step_id)
            if key not in steps_map:
                continue
            args = value.get("arguments", {}) or {}
            step = steps_map[key]
            step.search_query = str(args.get("search_query", "") or "")
            kw = args.get("search_keywords", "")
            step.search_keywords = str(kw) if kw else ""
            step.enable_summarization = bool(args.get("enable_summarization", False))

        elif value_type == "UniversalSearchToolTraceData":
            # This event has no planIdentifier/stepId — match to the first pending step
            # whose tool_id matches and has not yet had knowledge sources filled in.
            tool_id = value.get("toolId", "")
            ks_candidate = value.get("knowledgeSources", []) or []
            ks_output = value.get("outputKnowledgeSources", []) or []
            for key in step_order:
                step = steps_map[key]
                if step.tool_id == tool_id and not step.knowledge_sources_candidate:
                    step.knowledge_sources_candidate = list(ks_candidate)
                    step.knowledge_sources_output = list(ks_output)
                    break

        elif value_type == "DynamicPlanStepFinished":
            plan_id = value.get("planIdentifier", "")
            step_id = value.get("stepId", "")
            key = (plan_id, step_id)
            if key not in steps_map:
                continue
            step = steps_map[key]
            step.step_state = value.get("state", "")
            step.execution_time_ms = _parse_execution_time(value.get("executionTime", ""))

            # Backfill user_ask if trigger came before DynamicPlanReceivedDebug
            if not step.user_ask:
                step.user_ask = asks.get(plan_id, "")

            observation = value.get("observation", {}) or {}
            search_result = observation.get("search_result", {}) or {}
            step.search_errors = list(search_result.get("search_errors", []) or [])

            raw_results = search_result.get("search_results", []) or []
            items: list[MCSSearchResultItem] = []
            for r in raw_results:
                if isinstance(r, dict):
                    name = str(r.get("Name", r.get("name", "")) or "")
                    url_raw = str(r.get("Url", r.get("url", "")) or "")
                    items.append(
                        MCSSearchResultItem(
                            name=name,
                            url=url_raw or None,
                            file_type=str(r.get("FileType", r.get("fileType", "")) or "") or None,
                            source_id=str(r.get("SourceId", r.get("sourceId", "")) or "") or None,
                        )
                    )
            step.result_items = items

    # Backfill user_ask for any steps whose ask arrived after trigger was recorded
    for (plan_id, _), step in steps_map.items():
        if not step.user_ask:
            step.user_ask = asks.get(plan_id, "")

    # Score all steps
    for step in steps_map.values():
        _score_step(step)

    steps_list = [steps_map[key] for key in step_order]
    has_events = bool(steps_list) or bool(asks)

    return MCSPlannerAnalysis(
        plan_count=len({plan_id for plan_id, _ in step_order}),
        step_count=len(steps_list),
        steps=steps_list,
        has_planner_events=has_events,
    )
