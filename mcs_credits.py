"""Copilot Studio credit estimation from conversation activities.

The estimator maps observed activity types to Copilot Credits billing meters using
published rates from:
https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management

The output is intentionally heuristic: transcript/snapshot logs do not expose all
billing signals with perfect fidelity.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MCSCreditEstimate(BaseModel):
    """Estimated Copilot Credit usage breakdown for one analysed run."""

    classic_answers: int = 0
    generative_answers: int = 0
    agent_actions: int = 0
    tenant_graph_grounding_messages: int = 0
    agent_flow_actions: int = 0
    premium_tool_responses: int = 0

    classic_credits: float = 0.0
    generative_credits: float = 0.0
    agent_action_credits: float = 0.0
    tenant_graph_credits: float = 0.0
    agent_flow_credits: float = 0.0
    premium_tool_credits: float = 0.0

    total_credits: float = 0.0
    assumptions: list[str] = Field(default_factory=list)


def _is_reasoning_model(model_hint: str | None) -> bool:
    if not model_hint:
        return False
    hint = model_hint.lower()
    reasoning_markers = ("o1", "o3", "o4", "gpt5", "gpt-5", "reason")
    return any(marker in hint for marker in reasoning_markers)


def estimate_credits_from_activities(activities: list[dict], model_hint: str | None = None) -> MCSCreditEstimate:
    """Estimate Copilot Credits consumed by one conversation/activity run.

    Rates used (as of current docs):
    - Classic answer: 1
    - Generative answer: 2
    - Agent action: 5
    - Tenant graph grounding for messages: 10
    - Agent flow actions: 13 per 100 actions
    - Text/gen AI tools premium: 100 per 10 responses (applied for reasoning models)
    """

    bot_messages = 0
    generative_signals = 0
    tenant_graph_grounding_messages = 0
    agent_actions = 0
    agent_flow_actions = 0

    for activity in activities:
        act_type = activity.get("type", "")
        role = (activity.get("from", {}) or {}).get("role", "")
        value_type = activity.get("valueType", "") or activity.get("name", "")
        value = activity.get("value", {}) or {}

        if act_type == "message" and role == "bot":
            bot_messages += 1

        if act_type == "event":
            if value_type in {"DynamicPlanReceived", "DynamicPlanReceivedDebug", "DynamicPlanFinished"}:
                generative_signals += 1

            if value_type == "DynamicPlanStepTriggered":
                agent_actions += 1
                generative_signals += 1

            if value_type == "UniversalSearchToolTraceData":
                sources = value.get("knowledgeSources", []) or []
                if any("graph" in str(src).lower() for src in sources):
                    tenant_graph_grounding_messages += 1
                generative_signals += 1

            if value_type == "DialogTracingInfo":
                actions = value.get("actions", []) or []
                for action in actions:
                    action_type = (action or {}).get("actionType", "")
                    if action_type in {
                        "HttpRequestAction",
                        "InvokeFlowAction",
                        "BeginDialog",
                        "ConditionGroup",
                        "ConditionItem",
                        "SendActivity",
                    }:
                        agent_actions += 1
                    if action_type == "InvokeFlowAction":
                        agent_flow_actions += 1
                if actions:
                    generative_signals += 1

        if act_type == "trace" and value_type == "DialogRedirect":
            agent_actions += 1

    # Heuristic classification for bot responses.
    if generative_signals > 0 or agent_actions > 0 or tenant_graph_grounding_messages > 0:
        generative_answers = bot_messages
        classic_answers = 0
    else:
        classic_answers = bot_messages
        generative_answers = 0

    premium_tool_responses = generative_answers if _is_reasoning_model(model_hint) else 0

    classic_credits = float(classic_answers * 1)
    generative_credits = float(generative_answers * 2)
    agent_action_credits = float(agent_actions * 5)
    tenant_graph_credits = float(tenant_graph_grounding_messages * 10)
    agent_flow_credits = (agent_flow_actions / 100.0) * 13.0
    premium_tool_credits = (premium_tool_responses / 10.0) * 100.0

    total_credits = (
        classic_credits
        + generative_credits
        + agent_action_credits
        + tenant_graph_credits
        + agent_flow_credits
        + premium_tool_credits
    )

    assumptions = [
        "This is a prediction from observed transcript/snapshot events, not a billing export.",
        "Bot responses are classified as generative when dynamic-plan or tool/action signals are present.",
        "Tenant graph grounding is inferred from knowledge source identifiers containing 'graph'.",
        "Reasoning surcharge is added when model hint suggests a reasoning model (o1/o3/o4/gpt-5 family).",
    ]

    return MCSCreditEstimate(
        classic_answers=classic_answers,
        generative_answers=generative_answers,
        agent_actions=agent_actions,
        tenant_graph_grounding_messages=tenant_graph_grounding_messages,
        agent_flow_actions=agent_flow_actions,
        premium_tool_responses=premium_tool_responses,
        classic_credits=round(classic_credits, 2),
        generative_credits=round(generative_credits, 2),
        agent_action_credits=round(agent_action_credits, 2),
        tenant_graph_credits=round(tenant_graph_credits, 2),
        agent_flow_credits=round(agent_flow_credits, 2),
        premium_tool_credits=round(premium_tool_credits, 2),
        total_credits=round(total_credits, 2),
        assumptions=assumptions,
    )
