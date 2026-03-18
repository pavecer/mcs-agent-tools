"""Multi-model comparison capability for Copilot Studio agents.

Provides:
- A model catalogue describing Copilot Studio-compatible models.
- ``build_comparison_markdown`` to produce a Markdown "Model Performance Comparison"
  section for an agent report.
- An optional API-backed comparison controlled by the ``MCS_ENABLE_MODEL_COMPARISON``
  environment variable (requires ``OPENAI_API_KEY`` to be set as well).

When ``MCS_ENABLE_MODEL_COMPARISON`` is not set or is falsy the feature gracefully
skips the live test and only reports the configured model plus static guidance.
"""

from __future__ import annotations

import os

from toolkit.mcs.models import MCSBotProfile

# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------

# Internal model key → descriptive metadata used for the comparison report.
# Keys align with those in validator._HINT_TO_KEY / _MODEL_META.
_MODEL_CATALOGUE: dict[str, dict] = {
    "gpt41": {
        "display": "GPT-4.1",
        "tier": "Flagship",
        "context_window": "1 M tokens",
        "cost_tier": "Standard",
        "strengths": [
            "Precise, complex instruction following",
            "Excellent for multi-step reasoning and tool use",
            "1 M-token context — ideal for large knowledge bases",
            "Strong persona adherence",
        ],
        "limitations": [
            "Higher cost than Mini/Nano variants",
            "May be slower than compact variants for simple queries",
        ],
        "recommendation": (
            "Good default choice for most enterprise agents. "
            "If cost is a concern, evaluate GPT-4.1 Mini for comparable accuracy at lower cost."
        ),
    },
    "gpt41mini": {
        "display": "GPT-4.1 Mini",
        "tier": "Standard",
        "context_window": "1 M tokens",
        "cost_tier": "Low",
        "strengths": [
            "Strong balance of quality and cost",
            "Faster response times than GPT-4.1",
            "Suitable for well-scoped, focused agents",
        ],
        "limitations": [
            "Less precise on very complex, multi-layered instructions than GPT-4.1",
            "May require shorter, more explicit instructions",
        ],
        "recommendation": (
            "Consider GPT-4.1 if the agent handles complex queries or nuanced instructions. "
            "GPT-4.1 Mini is a cost-effective choice for agents with clear, well-defined scope."
        ),
    },
    "gpt41nano": {
        "display": "GPT-4.1 Nano",
        "tier": "Compact",
        "context_window": "1 M tokens",
        "cost_tier": "Very Low",
        "strengths": [
            "Lowest cost in the GPT-4.1 family",
            "Fastest response times",
            "Suitable for simple FAQ or routing agents",
        ],
        "limitations": [
            "Less capable for nuanced or multi-step tasks",
            "Requires concise, simple instructions (< 1 500 chars recommended)",
            "May miss subtle context or implicit intent",
        ],
        "recommendation": (
            "Upgrade to GPT-4.1 Mini or GPT-4.1 if answer quality is insufficient. "
            "GPT-4.1 Nano is best for high-volume, low-complexity use cases."
        ),
    },
    "gpt5": {
        "display": "GPT-5",
        "tier": "Frontier",
        "context_window": "200 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Most capable model in the Copilot Studio catalogue",
            "Exceptional complex reasoning and synthesis",
            "Best-in-class instruction adherence and accuracy",
            "Suitable for research, legal, financial, or compliance agents",
        ],
        "limitations": [
            "Highest cost — validate ROI before deploying at scale",
            "Very long system instructions benefit from careful structuring",
        ],
        "recommendation": (
            "Using the most capable available model. "
            "Ensure cost aligns with business expectations; "
            "consider GPT-4.1 for lower-complexity topics."
        ),
    },
    "gpt5chat": {
        "display": "GPT-5 Chat",
        "tier": "Frontier / Conversational",
        "context_window": "128 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Optimised for conversational agents and dialogue flow",
            "High-quality, natural responses",
            "Strong grounding and factuality in conversational contexts",
        ],
        "limitations": [
            "Premium cost tier",
            "Slightly narrower context than GPT-5 base model",
        ],
        "recommendation": (
            "Using a premium conversational model. Evaluate whether GPT-4.1 meets quality requirements at lower cost."
        ),
    },
    "o1": {
        "display": "o1",
        "tier": "Reasoning",
        "context_window": "128 K tokens",
        "cost_tier": "High",
        "strengths": [
            "Step-by-step deliberate reasoning",
            "Excellent for math, coding, logic, and analytical tasks",
            "Reduced hallucination on structured problem-solving",
        ],
        "limitations": [
            "Slower responses due to reasoning process",
            "Not optimised for conversational / FAQ agents",
            "Higher latency may affect user experience",
        ],
        "recommendation": (
            "o1 is ideal for agents that solve structured problems (e.g., data analysis, code review). "
            "For conversational or FAQ agents, GPT-4.1 typically provides better latency and cost."
        ),
    },
    "o3": {
        "display": "o3",
        "tier": "Reasoning (Advanced)",
        "context_window": "200 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Most advanced reasoning capabilities",
            "Excellent for scientific, legal, or highly analytical tasks",
            "Broader context window than o1",
        ],
        "limitations": [
            "Premium cost and higher latency",
            "Overkill for general-purpose FAQ or customer service agents",
        ],
        "recommendation": (
            "Reserve for agents requiring expert-level analytical reasoning. "
            "Consider o1 or GPT-4.1 for most enterprise scenarios."
        ),
    },
    "o4mini": {
        "display": "o4-mini",
        "tier": "Reasoning (Compact)",
        "context_window": "128 K tokens",
        "cost_tier": "Medium",
        "strengths": [
            "Compact reasoning model at reduced cost vs. o3",
            "Good for moderate analytical tasks",
            "Faster than o3 while retaining reasoning quality",
        ],
        "limitations": [
            "Less capable than o3 for highly complex analytical problems",
            "Not optimised for general conversational use",
        ],
        "recommendation": (
            "Good balance of reasoning ability and cost. "
            "Evaluate GPT-4.1 if conversational quality is more important than reasoning depth."
        ),
    },
    "gpt5reasoning": {
        "display": "GPT-5 Reasoning",
        "tier": "Deep / Reasoning (GA)",
        "context_window": "400 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Most capable reasoning model in Copilot Studio (replaces o3, Dec 2025)",
            "Advanced chain-of-thought reasoning for complex analytical tasks",
            "400 K-token context enables very large knowledge bases",
            "Excellent for legal, financial, scientific, and compliance agents",
        ],
        "limitations": [
            "No temperature control — fixed sampling",
            "Premium cost and higher latency than conversational models",
            "Overkill for FAQ or simple customer-service agents",
        ],
        "recommendation": (
            "Use for agents requiring expert-level analytical reasoning on private data. "
            "Consider GPT-5 Chat or GPT-4.1 for conversational or lower-complexity scenarios."
        ),
    },
    "gpt52chat": {
        "display": "GPT-5.2 Chat",
        "tier": "General (Experimental)",
        "context_window": "128 K tokens",
        "cost_tier": "Standard",
        "strengths": [
            "Improved conversational quality over GPT-5 Chat",
            "Strong instruction adherence and factual grounding",
            "Standard rate — cost-effective for conversational agents",
        ],
        "limitations": [
            "Experimental — not suitable for production without thorough evaluation",
            "Performance and availability may vary",
        ],
        "recommendation": (
            "Evaluate against GPT-5 Chat (GA) before considering for rollout. "
            "Do not deploy in production without systematic evaluation."
        ),
    },
    "gpt52reasoning": {
        "display": "GPT-5.2 Reasoning",
        "tier": "Deep / Reasoning (Experimental)",
        "context_window": "400 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Highest available reasoning depth in Copilot Studio",
            "400 K-token context for very large analytical workloads",
            "Exceeds GPT-5 Reasoning on complex multi-step problems",
        ],
        "limitations": [
            "Experimental — not for production; subject to availability and quality variability",
            "No temperature control",
            "Highest latency of all available models",
        ],
        "recommendation": (
            "Reserve for advanced experimental exploration. "
            "Compare systematically against GPT-5 Reasoning (GA) before any rollout."
        ),
    },
    "claudesonnet45": {
        "display": "Claude Sonnet 4.5",
        "tier": "General (Experimental / External)",
        "context_window": "200 K tokens",
        "cost_tier": "Standard",
        "strengths": [
            "Strong conversational quality and nuanced writing",
            "200 K-token context for large knowledge sets",
            "Anthropic built-in safety policies",
        ],
        "limitations": [
            "External model — Anthropic data terms apply; content moderation control unavailable",
            "Experimental — not for production",
            "Requires Enable External Models in Power Platform admin centre",
        ],
        "recommendation": (
            "Evaluate against GPT-5 Chat for conversational quality. "
            "Review Anthropic data terms before using with regulated or customer data."
        ),
    },
    "claudeopus45": {
        "display": "Claude Opus 4.5",
        "tier": "Deep (Experimental / External)",
        "context_window": "200 K tokens",
        "cost_tier": "Premium",
        "strengths": [
            "Anthropic's most capable model — advanced analysis and nuanced reasoning",
            "Excellent writing quality and ethical reasoning",
            "200 K-token context for large documents",
        ],
        "limitations": [
            "External model — Anthropic data terms apply; content moderation control unavailable",
            "Experimental — not for production; replaces Claude Opus 4.1 (retired Feb 2026)",
            "Premium cost; requires Enable External Models in Power Platform admin centre",
        ],
        "recommendation": (
            "Compare against GPT-5 Reasoning (GA) for deep-analysis use cases. "
            "Review Anthropic terms before processing regulated data."
        ),
    },
}

# Map from Copilot Studio modelNameHint to OpenAI API model name for API comparison.
_HINT_TO_OPENAI_MODEL: dict[str, str] = {
    "GPT41": "gpt-4.1",
    "gpt-4.1": "gpt-4.1",
    "gpt41": "gpt-4.1",
    "GPT41Mini": "gpt-4.1-mini",
    "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt41mini": "gpt-4.1-mini",
    "GPT41Nano": "gpt-4.1-nano",
    "gpt-4.1-nano": "gpt-4.1-nano",
    "gpt41nano": "gpt-4.1-nano",
    "GPT5": "gpt-5",
    "gpt-5": "gpt-5",
    "gpt5": "gpt-5",
    "GPT5Chat": "gpt-5-chat",
    "gpt-5-chat": "gpt-5-chat",
    "gpt5chat": "gpt-5-chat",
    "GPT5Reasoning": "gpt-5-reasoning",
    "gpt-5-reasoning": "gpt-5-reasoning",
    "gpt5reasoning": "gpt-5-reasoning",
    "GPT52Chat": "gpt-5.2-chat",
    "gpt-5.2-chat": "gpt-5.2-chat",
    "gpt52chat": "gpt-5.2-chat",
    "GPT52Reasoning": "gpt-5.2-reasoning",
    "gpt-5.2-reasoning": "gpt-5.2-reasoning",
    "gpt52reasoning": "gpt-5.2-reasoning",
    "ClaudeSonnet45": "claude-sonnet-4-5",
    "claude-sonnet-4.5": "claude-sonnet-4-5",
    "claudesonnet45": "claude-sonnet-4-5",
    "ClaudeOpus45": "claude-opus-4-5",
    "claude-opus-4.5": "claude-opus-4-5",
    "claudeopus45": "claude-opus-4-5",
    "o1": "o1",
    "o1-preview": "o1-preview",
    "o1-mini": "o1-mini",
    "o3": "o3",
    "o3-mini": "o3-mini",
    "o4-mini": "o4-mini",
    "o4mini": "o4-mini",
    "GPT4o": "gpt-4o",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4": "gpt-4",
    "GPT4": "gpt-4",
}

# Model keys that are below the GPT-4.1 threshold or retired (legacy / not in active catalogue).
_LEGACY_HINTS = {
    "GPT4o",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4",
    "GPT4",
    "gpt-35-turbo",
    "gpt-3.5-turbo",
    "o1",
    "o1-preview",
    "o1-mini",
    "o3",
    "o3-mini",
    "o4-mini",
    "o4mini",
}

# Generic sample queries used for API-based comparison.
_SAMPLE_QUERIES: list[str] = [
    "What can you help me with?",
    "How do I contact support?",
    "What are your main capabilities?",
    "Can you summarise the key policies relevant to my request?",
    "What should I do if I encounter an error?",
]

# Max tokens for sample query responses (kept short to limit cost).
_MAX_TOKENS = 200


def _get_openai_client(api_key: str):
    """Return an OpenAI client configured like the eval generator path."""
    try:
        import openai  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise RuntimeError("openai package is not installed") from exc

    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return openai.OpenAI(**kwargs)


def _resolve_comparison_models(configured_openai_model: str) -> list[str]:
    """Choose comparison models, respecting custom base URL / deployment configuration."""
    custom_models = os.getenv("MCS_COMPARISON_MODELS", "").strip()
    if custom_models:
        models = [item.strip() for item in custom_models.split(",") if item.strip()]
        deduped: list[str] = []
        for model in models:
            if model not in deduped:
                deduped.append(model)
        return deduped[:5]

    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    explicit_model = os.getenv("OPENAI_MODEL", "").strip()
    if base_url:
        chosen = explicit_model or configured_openai_model or "gpt-4o"
        return [chosen]

    return _choose_comparison_models(None, configured_openai_model)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_catalogue_key(hint: str | None) -> str | None:
    """Return the catalogue key for a model hint, or None if not in catalogue."""
    if not hint:
        return None
    normalized = hint.strip()
    # Direct lookup
    if normalized in _MODEL_CATALOGUE:
        return normalized
    # Try normalising hint to catalogue key via the validator mapping
    from validator import _HINT_TO_KEY  # type: ignore[attr-defined]

    key = _HINT_TO_KEY.get(normalized)
    if key and key in _MODEL_CATALOGUE:
        return key
    return None


def _call_openai_chat(
    model: str,
    system: str,
    user: str,
    api_key: str,
    timeout_s: float = 30.0,
) -> dict:
    """Call OpenAI chat completions API and return content/error details."""
    try:
        client = _get_openai_client(api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system or "You are a helpful assistant. Keep answers concise."},
                {"role": "user", "content": user},
            ],
            timeout=timeout_s,
        )
        content = response.choices[0].message.content or ""
        return {
            "content": content.strip() or None,
            "error": None,
            "model": getattr(response, "model", model) or model,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "content": None,
            "error": str(exc),
            "model": model,
        }


def _run_api_comparison(
    instructions: str,
    comparison_models: list[str],
    api_key: str,
) -> list[dict]:
    """Run sample queries against each model and return a list of result dicts.

    Each result dict has keys: ``model``, ``query``, ``response``, ``length``.
    """
    results: list[dict] = []
    system = instructions.strip() if instructions else "You are a helpful assistant."
    for query in _SAMPLE_QUERIES:
        for model in comparison_models:
            result = _call_openai_chat(model, system, query, api_key)
            response = result["content"]
            results.append(
                {
                    "model": result.get("model") or model,
                    "query": query,
                    "response": response or "",
                    "length": len(response) if response else 0,
                    "success": bool(response),
                    "error": result.get("error") or "",
                }
            )
    return results


def _summarise_api_results(results: list[dict], comparison_models: list[str]) -> str:
    """Produce a Markdown summary table from API comparison results."""
    if not results:
        return "_No API comparison results available._\n"

    lines: list[str] = []

    # Per-model aggregate stats
    model_stats: dict[str, dict] = {
        m: {"total_len": 0, "count": 0, "failures": 0, "last_error": ""} for m in comparison_models
    }
    for r in results:
        m = r["model"]
        if m not in model_stats:
            continue
        if not r.get("success"):
            model_stats[m]["failures"] += 1
            if r.get("error"):
                model_stats[m]["last_error"] = r["error"]
        else:
            model_stats[m]["total_len"] += r["length"]
            model_stats[m]["count"] += 1

    lines += ["### API Comparison Summary", ""]
    lines += [
        f"We ran {len(_SAMPLE_QUERIES)} sample queries on each model using the agent's system instructions as context.",
        "",
    ]

    lines += [
        "| Model | Avg response length | Successes | Failures | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in comparison_models:
        stats = model_stats[m]
        avg = stats["total_len"] // stats["count"] if stats["count"] > 0 else 0
        successes = stats["count"]
        if successes > 0:
            status = '<span style="color: #1b6b2f; font-weight: 600;">OK</span>'
        else:
            error_msg = stats["last_error"][:60] or "No response"
            status = f'<span style="color: #c62828; font-weight: 600;">Failed: {error_msg}</span>'
        lines.append(
            f"| {m} | {avg} chars | {successes}/{len(_SAMPLE_QUERIES)} | {stats['failures']}/{len(_SAMPLE_QUERIES)} | {status} |"
        )
    lines.append("")

    # Determine best model by average response length (simple heuristic)
    ranked = sorted(
        [
            (m, model_stats[m]["total_len"] // model_stats[m]["count"] if model_stats[m]["count"] > 0 else 0)
            for m in comparison_models
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    if ranked:
        best_model, best_avg = ranked[0]
        other_avgs = [avg for _, avg in ranked[1:] if avg > 0]
        if best_avg == 0:
            lines.append(
                "> Live comparison did not return any successful model responses. Review the status column above for the API error details."
            )
        elif other_avgs:
            pct_diff = round(((best_avg - other_avgs[0]) / other_avgs[0]) * 100) if other_avgs[0] > 0 else 0
            lines.append(
                f"> **{best_model}** produced the longest responses on average ({best_avg} chars), "
                f"{pct_diff}% more than the next model. Longer responses tend to be more thorough, "
                "but may also be more verbose — review sample outputs for quality."
            )
        else:
            lines.append(f"> **{best_model}** produced the longest responses on average ({best_avg} chars).")
        lines.append("")

    # Sample Q&A table
    lines += ["### Sample Query Comparison", ""]
    lines += [
        "| Query | Model | Status | Preview |",
        "| --- | --- | --- | --- |",
    ]
    for query in _SAMPLE_QUERIES:
        for m in comparison_models:
            row = next((r for r in results if r["model"] == m and r["query"] == query), None)
            if row and row.get("success"):
                status = '<span style="color: #1b6b2f; font-weight: 600;">Success</span>'
            else:
                status = '<span style="color: #c62828; font-weight: 600;">Failed</span>'
            preview_source = (row.get("response") if row else "") or (row.get("error") if row else "") or "No response"
            short = preview_source[:180] + "…" if len(preview_source) > 180 else preview_source
            safe_query = query.replace("|", "\\|")
            safe_short = short.replace("|", "\\|")
            lines.append(f"| {safe_query} | {m} | {status} | {safe_short} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_comparison_markdown(profile: MCSBotProfile) -> str:
    """Return a Markdown string for the 'Model Performance Comparison' section.

    If ``MCS_ENABLE_MODEL_COMPARISON=true`` (env) and ``OPENAI_API_KEY`` is set,
    live API queries are run against multiple models.  Otherwise static guidance
    based on the configured model is returned.

    Args:
        profile: Parsed ``MCSBotProfile`` containing GPT info and AI settings.

    Returns:
        Markdown string suitable for inclusion in an agent analysis report.
    """
    lines: list[str] = ["## Model Performance Comparison", ""]

    gpt_info = profile.gpt_info
    hint = (gpt_info.model_hint or "").strip() if gpt_info else ""
    catalogue_key = _resolve_catalogue_key(hint or None)
    model_data = _MODEL_CATALOGUE.get(catalogue_key) if catalogue_key else None

    # ── 1. Model Identification ─────────────────────────────────────────────
    lines += ["### Configured Model", ""]

    if model_data:
        display = model_data["display"]
        tier = model_data["tier"]
        ctx = model_data["context_window"]
        cost = model_data["cost_tier"]
        lines += [
            "| Field | Value |",
            "| --- | --- |",
            f"| **Model** | {display} |",
            f"| **Tier** | {tier} |",
            f"| **Context window** | {ctx} |",
            f"| **Cost tier** | {cost} |",
            "",
        ]
    elif hint and hint in _LEGACY_HINTS:
        lines += [
            f"The agent is configured with **{hint}** — a legacy model that is not part of the "
            "current Copilot Studio GPT-4.1+ catalogue.",
            "",
            "> ⚠️ **Upgrade recommended.** Migrating to GPT-4.1 (or GPT-4.1 Mini for cost savings) "
            "will improve instruction-following accuracy, increase the context window, and align the "
            "agent with actively maintained model generations.",
            "",
        ]
    elif hint:
        lines += [
            f"Configured model hint: **{hint}**  ",
            "_Model not found in the Copilot Studio catalogue.  "
            "Verify the model name in the agent's GPT component configuration._",
            "",
        ]
    else:
        lines += [
            "_No model configuration detected in this snapshot. "
            "Open the agent in Copilot Studio and check Settings → AI Capabilities → Model._",
            "",
        ]

    # ── 2. Model Catalogue Overview ─────────────────────────────────────────
    lines += ["### Available Copilot Studio Models", ""]
    lines += [
        "| Model | Tier | Context Window | Cost Tier | Best For |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key, meta in _MODEL_CATALOGUE.items():
        strengths_str = meta["strengths"][0] if meta["strengths"] else "—"
        active = " ✅ *(current)*" if key == catalogue_key else ""
        lines.append(
            f"| {meta['display']}{active} | {meta['tier']} | {meta['context_window']} "
            f"| {meta['cost_tier']} | {strengths_str} |"
        )
    lines.append("")

    # ── 3. Recommendation for the configured model ──────────────────────────
    lines += ["### Recommendation", ""]
    if model_data:
        lines += [
            f"**Current model:** {model_data['display']}",
            "",
            f"{model_data['recommendation']}",
            "",
            "**Strengths**",
            "",
            "| Area | Detail |",
            "| --- | --- |",
        ]
        for s in model_data["strengths"]:
            lines.append(f"| Strength | {s} |")
        lines += ["", "**Considerations**", "", "| Area | Detail |", "| --- | --- |"]
        for lim in model_data["limitations"]:
            lines.append(f"| Consideration | {lim} |")
        lines.append("")
    elif hint and hint in _LEGACY_HINTS:
        lines += [
            "**Upgrade path:**",
            "",
            "- **GPT-4.1** — best accuracy, 1 M-token context. Recommended for complex agents.",
            "- **GPT-4.1 Mini** — good balance of quality and cost for well-scoped agents.",
            "- **GPT-4.1 Nano** — lowest cost, fastest. Ideal for simple FAQ / routing agents.",
            "",
            "Evaluate agent behaviour after model migration with Copilot Studio's built-in "
            "[evaluation feature](https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/"
            "build-smarter-test-smarter-agent-evaluation-in-microsoft-copilot-studio/).",
            "",
        ]
    else:
        lines += [
            "Configure the agent's foundation model in Copilot Studio under "
            "**Settings → AI Capabilities → Model** before evaluating model performance.",
            "",
        ]

    # ── 4. API-Based Comparison (optional) ──────────────────────────────────
    enable_api = os.getenv("MCS_ENABLE_MODEL_COMPARISON", "").strip().lower() in ("1", "true", "yes")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    lines += ["### Live API Comparison", ""]

    if not enable_api:
        lines += [
            "_Live model comparison is disabled._  ",
            "Set `MCS_ENABLE_MODEL_COMPARISON=true` and `OPENAI_API_KEY=<key>` in the environment "
            "to run sample queries against multiple models and compare responses automatically.",
            "",
            "Alternatively, use [Copilot Studio's evaluation feature]"
            "(https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/"
            "build-smarter-test-smarter-agent-evaluation-in-microsoft-copilot-studio/) to compare "
            "agent performance across model configurations.",
            "",
        ]
    elif not api_key:
        lines += [
            "> ⚠️ `MCS_ENABLE_MODEL_COMPARISON` is set but `OPENAI_API_KEY` is not provided. "
            "Provide a valid OpenAI API key to enable live comparison.",
            "",
        ]
    else:
        # Determine which models to compare
        configured_openai = _HINT_TO_OPENAI_MODEL.get(hint, "gpt-4o") if hint else "gpt-4o"
        comparison_models = _resolve_comparison_models(configured_openai)

        instructions = (gpt_info.instructions or "") if gpt_info else ""

        lines += [
            f"Running {len(_SAMPLE_QUERIES)} sample queries on "
            f"{', '.join('**' + m + '**' for m in comparison_models)} …",
            "",
        ]

        base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
        if base_url:
            lines += [
                f"> Using configured custom OpenAI base URL: `{base_url}`",
                "",
            ]
        if os.getenv("MCS_COMPARISON_MODELS", "").strip():
            lines += [
                "> Comparison model list provided via `MCS_COMPARISON_MODELS`.",
                "",
            ]

        try:
            results = _run_api_comparison(instructions, comparison_models, api_key)
            lines.append(_summarise_api_results(results, comparison_models))
        except Exception as exc:  # noqa: BLE001
            lines += [
                f"> ⚠️ API comparison failed: {exc}",
                "",
            ]

    return "\n".join(lines)


def _choose_comparison_models(catalogue_key: str | None, configured_openai_model: str) -> list[str]:
    """Choose a small set of OpenAI API models to compare against the configured one."""
    # Always include the configured model as the baseline
    models: list[str] = []
    if configured_openai_model and configured_openai_model not in ("gpt-4o",):
        models.append(configured_openai_model)
    # Add gpt-4o as a reference point if not already the configured model
    if "gpt-4o" not in models:
        models.append("gpt-4o")
    # Add gpt-4o-mini as a cost-efficient alternative if not already present
    if "gpt-4o-mini" not in models and len(models) < 3:
        models.append("gpt-4o-mini")
    # Ensure uniqueness and cap at 3 models to limit cost
    seen: list[str] = []
    for m in models:
        if m not in seen:
            seen.append(m)
    return seen[:3]
