from mcs_credits import estimate_credits_from_activities


def test_estimate_classic_only_conversation() -> None:
    activities = [
        {"type": "message", "from": {"role": "user"}, "text": "Hello"},
        {"type": "message", "from": {"role": "bot"}, "text": "Hi there"},
    ]

    estimate = estimate_credits_from_activities(activities)

    assert estimate.classic_answers == 1
    assert estimate.generative_answers == 0
    assert estimate.agent_actions == 0
    assert estimate.total_credits == 1.0


def test_estimate_generational_actions_and_graph_grounding() -> None:
    activities = [
        {"type": "message", "from": {"role": "user"}, "text": "Get me order status"},
        {
            "type": "event",
            "valueType": "DynamicPlanReceived",
            "value": {"steps": ["topic.A", "topic.B"]},
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepTriggered",
            "value": {"stepId": "1", "taskDialogId": "topic.A"},
        },
        {
            "type": "event",
            "valueType": "DialogTracingInfo",
            "value": {"actions": [{"actionType": "InvokeFlowAction"}]},
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "value": {"knowledgeSources": ["microsoft.graph.sales"]},
        },
        {"type": "message", "from": {"role": "bot"}, "text": "Order shipped"},
    ]

    estimate = estimate_credits_from_activities(activities)

    assert estimate.classic_answers == 0
    assert estimate.generative_answers == 1
    assert estimate.agent_actions == 2
    assert estimate.tenant_graph_grounding_messages == 1
    assert estimate.agent_flow_actions == 1
    assert estimate.total_credits == 22.13


def test_estimate_adds_premium_for_reasoning_models() -> None:
    activities = [
        {"type": "message", "from": {"role": "user"}, "text": "Reason deeply"},
        {"type": "event", "valueType": "DynamicPlanReceived", "value": {}},
        {"type": "message", "from": {"role": "bot"}, "text": "Done"},
    ]

    estimate = estimate_credits_from_activities(activities, model_hint="gpt-5")

    # 1 generative response => 2 credits + 10 premium surcharge per response
    assert estimate.generative_credits == 2.0
    assert estimate.premium_tool_credits == 10.0
    assert estimate.total_credits == 12.0
