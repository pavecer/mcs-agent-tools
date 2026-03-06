"""MCS Agent Analyser — build a ConversationTimeline from dialog activities.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcs_models import (
    MCSConversationTimeline,
    MCSEventType,
    MCSExecutionPhase,
    MCSTimelineEvent,
)


def _parse_timestamp(ts: str | None) -> datetime | None:
    """Parse ISO timestamp string to datetime."""
    if not ts:
        return None
    try:
        ts_stripped = ts.rstrip("Z")
        if "+" in ts_stripped and ts_stripped.count("+") > 0:
            ts_part = ts_stripped.rsplit("+", 1)[0]
        else:
            ts_part = ts_stripped

        if "." in ts_part:
            main, frac = ts_part.split(".", 1)
            frac = frac[:6]
            ts_part = f"{main}.{frac}"

        return datetime.fromisoformat(ts_part).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _epoch_to_iso(epoch_ms: int | float | None) -> str | None:
    """Convert epoch milliseconds to ISO string."""
    if epoch_ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _get_timestamp(activity: dict) -> str | None:
    """Get best available timestamp from activity."""
    ts = activity.get("timestamp")
    if ts:
        return ts
    channel_data = activity.get("channelData", {}) or {}
    received_at = channel_data.get("webchat:internal:received-at")
    if received_at:
        return _epoch_to_iso(received_at)
    return None


def _extract_adaptive_card_text(attachments: list) -> str:
    """Extract readable text from Adaptive Card attachments."""
    texts: list[str] = []

    def _extract_from_elements(elements: list) -> None:
        for el in elements:
            if len(texts) >= 2:
                return
            if el.get("type") == "TextBlock" and el.get("text"):
                texts.append(el["text"])
            for child_key in ("items", "columns", "body"):
                children = el.get(child_key, []) or []
                if children:
                    _extract_from_elements(children)

    for att in attachments:
        if len(texts) >= 2:
            break
        content = att.get("content", {}) or {}
        body = content.get("body", []) or []
        _extract_from_elements(body)

    if texts:
        combined = " | ".join(texts)
        return combined[:150] + "..." if len(combined) > 150 else combined
    return "[Adaptive Card]"


def _ms_between(start: str | None, end: str | None) -> float:
    """Calculate milliseconds between two ISO timestamps."""
    dt_start = _parse_timestamp(start)
    dt_end = _parse_timestamp(end)
    if dt_start and dt_end:
        return (dt_end - dt_start).total_seconds() * 1000
    return 0.0


def build_timeline(activities: list[dict], schema_lookup: dict[str, str]) -> MCSConversationTimeline:
    """Build an MCSConversationTimeline from sorted activities and schema name lookup."""
    from mcs_parser import resolve_topic_name

    events: list[MCSTimelineEvent] = []
    phases: list[MCSExecutionPhase] = []
    errors: list[str] = []
    bot_name = ""
    conversation_id = ""
    user_query = ""
    first_timestamp: str | None = None
    last_timestamp: str | None = None

    # Track step triggers for duration calculation
    step_triggers: dict[str, str] = {}  # step_id -> trigger timestamp

    for activity in activities:
        act_type = activity.get("type", "")
        value_type = activity.get("valueType", "") or activity.get("name", "")
        from_info = activity.get("from", {}) or {}
        role = from_info.get("role", "")
        timestamp = _get_timestamp(activity)
        channel_data = activity.get("channelData", {}) or {}
        position = channel_data.get("webchat:internal:position", 0)

        # Track bot name and conversation id
        if not bot_name and from_info.get("name") and role == "bot":
            bot_name = from_info["name"]
        conv = activity.get("conversation", {}) or {}
        if not conversation_id and conv.get("id"):
            conversation_id = conv["id"]

        # Track time range
        if timestamp:
            if not first_timestamp:
                first_timestamp = timestamp
            last_timestamp = timestamp

        # Skip typing indicators
        if act_type == "typing":
            continue

        # User message
        if act_type == "message" and role == "user":
            text = activity.get("text", "")
            if not user_query and text:
                user_query = text
            events.append(
                MCSTimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=MCSEventType.USER_MESSAGE,
                    summary=f'User: "{text}"' if text else "User message",
                )
            )
            continue

        # Bot message
        if act_type == "message" and role == "bot":
            text = activity.get("text", "")
            attachments = activity.get("attachments", []) or []
            if not text and attachments:
                text = _extract_adaptive_card_text(attachments)
            clean_text = text.replace("\n", " ").replace("\r", "")
            summary = clean_text[:120] + "..." if len(clean_text) > 120 else clean_text
            events.append(
                MCSTimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=MCSEventType.BOT_MESSAGE,
                    summary=f"Bot: {summary}" if summary else "Bot message",
                )
            )
            continue

        # Event types
        if act_type == "event":
            value = activity.get("value", {}) or {}

            if value_type == "DynamicPlanReceived":
                steps = value.get("steps", [])
                step_names = [resolve_topic_name(s, schema_lookup) for s in steps]
                tools_summary = ", ".join(step_names) if step_names else "unknown"
                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.PLAN_RECEIVED,
                        summary=f"Plan: [{tools_summary}]",
                        plan_identifier=value.get("planIdentifier"),
                    )
                )

            elif value_type == "DynamicPlanReceivedDebug":
                ask = value.get("ask", "")
                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.PLAN_RECEIVED_DEBUG,
                        summary=f'Ask: "{ask}"',
                        plan_identifier=value.get("planIdentifier"),
                    )
                )

            elif value_type == "DynamicPlanStepTriggered":
                task_dialog_id = value.get("taskDialogId", "")
                topic = resolve_topic_name(task_dialog_id, schema_lookup)
                step_type = value.get("type", "")
                step_id = value.get("stepId", "")

                if step_id and timestamp:
                    step_triggers[step_id] = timestamp

                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.STEP_TRIGGERED,
                        topic_name=topic,
                        summary=f"Step start: {topic} ({step_type})",
                        state="inProgress",
                        step_id=step_id,
                        plan_identifier=value.get("planIdentifier"),
                    )
                )

            elif value_type == "DynamicPlanStepFinished":
                task_dialog_id = value.get("taskDialogId", "")
                topic = resolve_topic_name(task_dialog_id, schema_lookup)
                state = value.get("state", "")
                step_id = value.get("stepId", "")
                error = value.get("error")

                duration_ms = 0.0
                trigger_ts = step_triggers.get(step_id)
                if trigger_ts and timestamp:
                    duration_ms = _ms_between(trigger_ts, timestamp)

                error_msg = None
                if error and isinstance(error, dict):
                    error_msg = error.get("message", str(error))
                    errors.append(f"{topic}: {error_msg}")
                elif state == "failed":
                    error_msg = "Step failed"
                    errors.append(f"{topic}: failed")

                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.STEP_FINISHED,
                        topic_name=topic,
                        summary=f"Step end: {topic} [{state}]" + (f" ({duration_ms:.0f}ms)" if duration_ms > 0 else ""),
                        state=state,
                        error=error_msg,
                        step_id=step_id,
                        plan_identifier=value.get("planIdentifier"),
                    )
                )

                phases.append(
                    MCSExecutionPhase(
                        label=topic,
                        phase_type=value.get("type", "") if "type" in value else "",
                        start=trigger_ts,
                        end=timestamp,
                        duration_ms=duration_ms,
                        state=state,
                    )
                )

            elif value_type == "DynamicPlanFinished":
                was_cancelled = value.get("wasCancelled", False)
                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.PLAN_FINISHED,
                        summary=f"Plan finished (cancelled={was_cancelled})",
                        plan_identifier=value.get("planId"),
                    )
                )

            elif value_type == "DialogTracingInfo":
                ACTION_TYPE_MAP = {
                    "HttpRequestAction": MCSEventType.ACTION_HTTP_REQUEST,
                    "InvokeFlowAction": MCSEventType.ACTION_HTTP_REQUEST,
                    "BeginDialog": MCSEventType.ACTION_BEGIN_DIALOG,
                    "SendActivity": MCSEventType.ACTION_SEND_ACTIVITY,
                    "ConditionGroup": MCSEventType.ACTION_TRIGGER_EVAL,
                    "ConditionItem": MCSEventType.ACTION_TRIGGER_EVAL,
                }

                SUMMARY_TEMPLATES = {
                    MCSEventType.ACTION_HTTP_REQUEST: "HTTP call in {topic}",
                    MCSEventType.ACTION_QA: "QA in {topic}",
                    MCSEventType.ACTION_TRIGGER_EVAL: "Evaluate: {topic}",
                    MCSEventType.ACTION_BEGIN_DIALOG: "Call to {topic}",
                    MCSEventType.ACTION_SEND_ACTIVITY: "Send response in {topic}",
                }

                actions = value.get("actions", [])
                for action in actions:
                    topic_id = action.get("topicId", "")
                    action_type = action.get("actionType", "")
                    exception = action.get("exception", "")
                    topic = resolve_topic_name(topic_id, schema_lookup)

                    if exception:
                        errors.append(f"{topic}.{action_type}: {exception}")

                    event_type = ACTION_TYPE_MAP.get(action_type, MCSEventType.DIALOG_TRACING)
                    template = SUMMARY_TEMPLATES.get(event_type)
                    summary = template.format(topic=topic) if template else f"{action_type} in {topic}"

                    events.append(
                        MCSTimelineEvent(
                            timestamp=timestamp,
                            position=position,
                            event_type=event_type,
                            topic_name=topic,
                            summary=summary,
                        )
                    )

            elif value_type == "UniversalSearchToolTraceData":
                sources = value.get("knowledgeSources", [])
                source_names = [s.split(".")[-1] if "." in s else s for s in sources]
                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.KNOWLEDGE_SEARCH,
                        summary=f"Knowledge search: [{', '.join(source_names[:3])}]"
                        + (f" (+{len(source_names) - 3})" if len(source_names) > 3 else ""),
                    )
                )

            elif value_type == "ErrorCode":
                error_code = value.get("ErrorCode", "Unknown")
                errors.append(f"ErrorCode: {error_code}")
                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.ERROR,
                        summary=f"Error: {error_code}",
                        error=error_code,
                    )
                )

        # Trace type
        if act_type == "trace":
            value = activity.get("value", {}) or {}

            if value_type == "VariableAssignment":
                var_id = value.get("id", "")
                new_value = str(value.get("newValue", ""))[:80]
                scope = value.get("type", "")
                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.VARIABLE_ASSIGNMENT,
                        summary=f"{scope.title()} {var_id} = {new_value}",
                    )
                )

            elif value_type == "DialogRedirect":
                target_id = value.get("targetDialogId", "")
                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.DIALOG_REDIRECT,
                        summary=f"Redirect → {target_id[:40]}",
                    )
                )

            elif value.get("ErrorCode"):
                error_code = value["ErrorCode"]
                errors.append(f"ErrorCode: {error_code}")
                events.append(
                    MCSTimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=MCSEventType.ERROR,
                        summary=f"Error: {error_code}",
                        error=error_code,
                    )
                )

    total_elapsed = _ms_between(first_timestamp, last_timestamp)

    return MCSConversationTimeline(
        bot_name=bot_name,
        conversation_id=conversation_id,
        user_query=user_query,
        events=events,
        phases=phases,
        errors=errors,
        total_elapsed_ms=total_elapsed,
    )
