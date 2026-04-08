"""Pydantic models for the MCS Agent Analyser — Microsoft Copilot Studio snapshot analysis.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── Bot Profile models (from botContent.yml) ──────────────────────────────────


class MCSAISettings(BaseModel):
    use_model_knowledge: bool = False
    file_analysis: bool = False
    semantic_search: bool = False
    content_moderation: str = "Unknown"
    opt_in_latest_models: bool = False


class MCSComponentSummary(BaseModel):
    kind: str
    display_name: str
    schema_name: str
    state: str = "Active"
    trigger_kind: str | None = None
    trigger_queries: list[str] = Field(default_factory=list)
    dialog_kind: str | None = None
    action_kind: str | None = None
    description: str | None = None


class MCSGptInfo(BaseModel):
    display_name: str = ""
    description: str | None = None
    instructions: str | None = None
    model_hint: str | None = None
    knowledge_sources_kind: str | None = None
    web_browsing: bool = False
    code_interpreter: bool = False


class MCSKnowledgeSource(BaseModel):
    name: str = ""
    source_type: str = "Unknown"
    location: str | None = None
    site_id: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class MCSExternalTool(BaseModel):
    name: str = ""
    tool_type: str = "Unknown"
    connector_id: str | None = None
    auth_mode: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class MCSTopicConnection(BaseModel):
    source_schema: str
    source_display: str
    target_schema: str
    target_display: str
    condition: str | None = None


class MCSBotProfile(BaseModel):
    schema_name: str = ""
    bot_id: str = ""
    display_name: str = ""
    channels: list[str] = Field(default_factory=list)
    ai_settings: MCSAISettings = Field(default_factory=MCSAISettings)
    recognizer_kind: str = "Unknown"
    recognizer_id: str = ""
    components: list[MCSComponentSummary] = Field(default_factory=list)
    is_orchestrator: bool = False
    gpt_info: MCSGptInfo | None = None
    topic_connections: list[MCSTopicConnection] = Field(default_factory=list)
    knowledge_sources: list[MCSKnowledgeSource] = Field(default_factory=list)
    external_tools: list[MCSExternalTool] = Field(default_factory=list)


# ── Timeline models (from dialog.json / transcript.json) ──────────────────────


class MCSEventType(str, Enum):
    USER_MESSAGE = "UserMessage"
    BOT_MESSAGE = "BotMessage"
    PLAN_RECEIVED = "PlanReceived"
    PLAN_RECEIVED_DEBUG = "PlanReceivedDebug"
    STEP_TRIGGERED = "StepTriggered"
    STEP_FINISHED = "StepFinished"
    PLAN_FINISHED = "PlanFinished"
    DIALOG_TRACING = "DialogTracing"
    KNOWLEDGE_SEARCH = "KnowledgeSearch"
    VARIABLE_ASSIGNMENT = "VariableAssignment"
    DIALOG_REDIRECT = "DialogRedirect"
    ACTION_HTTP_REQUEST = "ActionHttpRequest"
    ACTION_QA = "ActionQA"
    ACTION_TRIGGER_EVAL = "ActionTriggerEval"
    ACTION_BEGIN_DIALOG = "ActionBeginDialog"
    ACTION_SEND_ACTIVITY = "ActionSendActivity"
    ERROR = "Error"
    OTHER = "Other"


class MCSKnowledgeSearchTrace(BaseModel):
    source_names: list[str] = Field(default_factory=list)
    output_source_names: list[str] = Field(default_factory=list)
    endpoints: list[str] = Field(default_factory=list)
    rewritten_question: str | None = None
    rewritten_keywords: str | None = None
    hypothetical_snippet: str | None = None
    completion_state: str | None = None
    gpt_answer_state: str | None = None
    result_count: int = 0
    verified_result_count: int = 0
    search_errors: list[str] = Field(default_factory=list)
    result_sources: list[str] = Field(default_factory=list)
    top_results: list[str] = Field(default_factory=list)
    verified_top_results: list[str] = Field(default_factory=list)
    rewrite_model_name: str | None = None
    rewrite_prompt_tokens: int = 0
    rewrite_completion_tokens: int = 0
    summary_model_name: str | None = None
    summary_prompt_tokens: int = 0
    summary_completion_tokens: int = 0
    summary_preview: str | None = None


class MCSTimelineEvent(BaseModel):
    timestamp: str | None = None
    position: int = 0
    event_type: MCSEventType = MCSEventType.OTHER
    topic_name: str | None = None
    summary: str = ""
    state: str | None = None
    error: str | None = None
    step_id: str | None = None
    plan_identifier: str | None = None
    tool_name: str | None = None
    search_query: str | None = None
    search_trace: MCSKnowledgeSearchTrace | None = None
    details: dict[str, str] = Field(default_factory=dict)


# ── Dynamic Planner Trace models ──────────────────────────────────────────────


class MCSSearchResultItem(BaseModel):
    """A single document returned by a knowledge source search."""

    name: str = ""
    url: str | None = None
    file_type: str | None = None
    source_id: str | None = None
    relevance_score: float = 0.0  # 0.0–1.0 term-overlap fraction (computed by planner_analysis)


class MCSPlannerStepTrace(BaseModel):
    """Full trace of one Dynamic Planner step (typically UniversalSearchTool).

    Fields are populated from five event valueTypes in order:
      DynamicPlanReceivedDebug    → user_ask
      DynamicPlanStepTriggered    → planner_thought, step_type, tool_id
      DynamicPlanStepBindUpdate   → search_query, search_keywords, enable_summarization
      UniversalSearchToolTraceData → knowledge_sources_candidate, knowledge_sources_output
      DynamicPlanStepFinished     → result_items, execution_time_ms, step_state
    Quality scores are computed by toolkit.mcs.planner_analysis._score_step.
    """

    step_id: str = ""
    plan_identifier: str = ""
    tool_id: str = ""

    # From DynamicPlanReceivedDebug (plan level)
    user_ask: str = ""

    # From DynamicPlanStepTriggered
    planner_thought: str = ""
    step_type: str = ""

    # From DynamicPlanStepBindUpdate
    search_query: str = ""
    search_keywords: str = ""
    enable_summarization: bool = False

    # From UniversalSearchToolTraceData
    knowledge_sources_candidate: list[str] = Field(default_factory=list)
    knowledge_sources_output: list[str] = Field(default_factory=list)

    # From DynamicPlanStepFinished
    result_items: list[MCSSearchResultItem] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    search_errors: list[str] = Field(default_factory=list)
    step_state: str = ""

    # Quality scores (computed by toolkit.mcs.planner_analysis._score_step)
    query_fidelity_pct: float = 0.0    # % of ask-terms found in generated query
    item_hit_rate_pct: float = 0.0     # % of returned docs that matched ask terms
    source_fidelity_pct: float = 0.0   # % of candidate sources that returned results
    overall_success_pct: float = 0.0   # weighted combination (45/35/20)
    matched_item_count: int = 0
    ask_term_count: int = 0            # total unique content terms extracted from user ask
    query_matched_term_count: int = 0  # ask-terms found in generated query
    score_flags: list[str] = Field(default_factory=list)


class MCSPlannerAnalysis(BaseModel):
    """Aggregated Dynamic Planner trace analysis for a full conversation session."""

    plan_count: int = 0
    step_count: int = 0
    steps: list[MCSPlannerStepTrace] = Field(default_factory=list)
    has_planner_events: bool = False


class MCSExecutionPhase(BaseModel):
    label: str
    phase_type: str = ""
    start: str | None = None
    end: str | None = None
    duration_ms: float = 0.0
    state: str = "completed"


class MCSConversationTimeline(BaseModel):
    bot_name: str = ""
    conversation_id: str = ""
    user_query: str = ""
    events: list[MCSTimelineEvent] = Field(default_factory=list)
    phases: list[MCSExecutionPhase] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    total_elapsed_ms: float = 0.0
    total_activities: int = 0
    message_count: int = 0
    event_count: int = 0
    trace_count: int = 0
    typing_count: int = 0
    planner_analysis: MCSPlannerAnalysis | None = None
