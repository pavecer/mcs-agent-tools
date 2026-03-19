"""Reflex state for the Power Platform Agent Renamer web UI."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import tempfile
import traceback
import zipfile
from pathlib import Path
from typing import Any

import reflex as rx
from dotenv import load_dotenv

# Load environment variables from .env file before any imports that use them
load_dotenv()

from toolkit.pp.evals_manager import analyze_evals_zip_bytes, export_solution_with_evals, preview_generated_evals
from auth_services import (
    approve_account_request,
    authenticate_env_admin,
    authenticate_db_user,
    create_account_request,
    ensure_auth_schema,
    is_admin_login_enabled,
    is_db_auth_enabled,
    is_signup_enabled,
    verify_turnstile,
)
from toolkit.mcs.credits import estimate_credits_from_activities
from toolkit.mcs.models import MCSConversationTimeline as _MCSTl
from toolkit.mcs.parser import parse_dialog_json as mcs_parse_dialog_json
from toolkit.mcs.parser import parse_yaml as mcs_parse_yaml
from toolkit.mcs.renderer import render_credit_estimate as mcs_render_credit_estimate
from toolkit.mcs.renderer import build_conversation_flow_items as mcs_build_conversation_flow_items
from toolkit.mcs.renderer import build_conversation_visual_summary as mcs_build_conversation_visual_summary
from toolkit.mcs.renderer import render_report_sections as mcs_render_report_sections
from toolkit.mcs.renderer import render_transcript_report as mcs_render_transcript_report
from toolkit.mcs.renderer import to_viz_segments as mcs_to_viz_segments
from toolkit.mcs.timeline import build_timeline as mcs_build_timeline
from toolkit.mcs.transcript import parse_transcript_json as mcs_parse_transcript
from renamer import (
    derive_schema_name,
    derive_solution_unique_name,
    inspect_zip,
    rename_solution_from_bytes,
    safe_extractall,
)
from toolkit.pp.deps_analyzer import analyze_deps_zip_bytes_report
from remote_fetch import (
    authenticate_dataverse,
    begin_device_code_auth,
    check_dataverse_connection,
    complete_device_code_auth,
    DataverseAuthConfig,
    has_dataverse_env_credentials,
    RemoteFetchError,
    fetch_transcript_by_id,
)
from toolkit.pp.solution_checker import check_solution_zip
from toolkit.pp.validator import validate_instructions, validate_zip_bytes
from toolkit.pp.visualizer import visualize_zip_bytes, get_evals_data

load_dotenv()

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB — maximum accepted upload size
TUTORIAL_TOTAL_STEPS = 8  # number of tutorial steps; must match _TUTORIAL_TOTAL in components.py


def _fit_score_color(score: int) -> str:
    if score >= 75:
        return "#107c10"
    if score >= 50:
        return "#c7921e"
    return "#a4262c"


def _decorate_fit_dimensions(dimensions: list[dict]) -> list[dict]:
    decorated: list[dict] = []
    for item in dimensions:
        score = int(item.get("score", 0) or 0)
        decorated.append(
            {
                **item,
                "accent_color": _fit_score_color(score),
            }
        )
    return decorated


def _load_users() -> dict[str, str]:
    """Return {username: hashed_password} from the USERS env variable.

    Format: ``USERS=admin:pass1,analyst:pass2``
    Returns an empty dict if the env var is absent or empty, which disables auth.
    """
    raw = os.getenv("USERS", "").strip()
    if not raw:
        return {}
    users: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        username, _, password = entry.partition(":")
        username = username.strip()
        password = password.strip()
        if username and password:
            # Hash with PBKDF2-HMAC-SHA256 using the username as a deterministic salt
            users[username] = hashlib.pbkdf2_hmac("sha256", password.encode(), username.encode(), 100_000).hex()
    return users


def _md_to_segments(md: str) -> list[dict]:
    """Split a Markdown string into text / mermaid fence segments."""
    if not md:
        return []
    segments: list[dict] = []
    remaining = md
    fence_open = "```mermaid"
    fence_close = "```"
    while remaining:
        start = remaining.find(fence_open)
        if start == -1:
            segments.append({"type": "text", "content": remaining})
            break
        if start > 0:
            segments.append({"type": "text", "content": remaining[:start]})
        rest = remaining[start + len(fence_open) :]
        end = rest.find(fence_close)
        if end == -1:
            segments.append({"type": "text", "content": fence_open + rest})
            break
        mermaid_src = rest[:end].strip()
        segments.append({"type": "mermaid", "content": mermaid_src})
        remaining = rest[end + len(fence_close) :]
    return segments


class State(rx.State):
    """Application state."""

    # ── Upload & detection ────────────────────────────────────────────────
    upload_filename: str = ""
    zip_bytes_b64: str = ""  # base64-encoded uploaded ZIP bytes
    is_inspecting: bool = False
    inspect_error: str = ""
    no_agent_warning: str = ""  # set when the uploaded ZIP has no Copilot Studio agent

    detected_bot_schema: str = ""
    detected_bot_name: str = ""
    detected_solution_name: str = ""
    detected_solution_display: str = ""
    detected_component_count: int = 0

    # ── User inputs ───────────────────────────────────────────────────────
    new_agent_name: str = ""
    new_solution_display_name: str = ""
    # auto-derived technical names (read-only previews)
    derived_schema: str = ""
    derived_solution_unique: str = ""

    # ── Visualization ─────────────────────────────────────────────────────
    is_visualizing: bool = False
    viz_error: str = ""
    # Snapshot ZIP path uses raw markdown segments; solution ZIP uses structured vars below
    viz_segments: list[dict] = []
    # Structured vars populated only for solution ZIPs
    viz_display_name: str = ""
    viz_schema_name: str = ""
    viz_channels: list[str] = []
    viz_recognizer: str = ""
    viz_model: str = ""
    viz_web_browsing: bool = False
    viz_use_model_knowledge: bool = False
    viz_instructions_length: int = 0
    viz_instructions_preview: str = ""
    viz_total: int = 0
    viz_active_count: int = 0
    viz_inactive_count: int = 0
    viz_category_stats: list[dict] = []
    viz_component_rows: list[dict] = []
    viz_mermaid: str = ""

    # ── Validation ───────────────────────────────────────────────────────────
    is_validating: bool = False
    validation_error: str = ""
    validation_ran: bool = False
    validation_model_key: str = ""
    validation_model_display: str = ""
    validation_results: list[dict] = []
    validation_best_practices: str = ""
    validation_instructions_length: int = 0
    show_best_practices: bool = False

    # ── Solution Check ────────────────────────────────────────────────────
    is_checking: bool = False
    check_error: str = ""
    check_ran: bool = False
    check_agent_name: str = ""
    check_solution_name: str = ""
    check_results: list[dict] = []
    check_pass_count: int = 0
    check_warn_count: int = 0
    check_fail_count: int = 0
    check_info_count: int = 0
    check_active_category: str = ""  # empty = show all

    # ── Evaluations ───────────────────────────────────────────────────
    # Summary items (no nested test_cases/rows to avoid large state)
    evals_test_sets: list[dict] = []  # [{schema_name, display_name, test_count}]
    evals_eval_sets: list[dict] = []  # [{schema_name, display_name, graders, row_count}]
    # Flat lists for foreach rendering
    evals_all_test_cases: list[
        dict
    ] = []  # [{set_schema, set_name, input, expected_response, score_threshold, origin_type}]
    evals_all_eval_rows: list[dict] = []  # [{set_schema, set_name, input, expected_output, keywords, source}]
    evals_sub_tab: str = "tests"  # "tests" | "evals"
    evals_active_test_set: str = ""  # schema_name filter, empty = all
    evals_active_eval_set: str = ""  # schema_name filter, empty = all
    evals_is_analyzing: bool = False
    evals_fit_error: str = ""
    evals_fit_ran: bool = False
    evals_fit_score: int = 0
    evals_fit_dimensions: list[dict] = []
    evals_fit_gaps: list[dict] = []
    evals_fit_recommendations: list[str] = []
    evals_should_offer_improve: bool = False
    evals_is_generating: bool = False
    evals_preview_error: str = ""
    evals_preview_mode: str = ""
    evals_preview_test_sets: list[dict] = []
    evals_preview_eval_sets: list[dict] = []
    evals_preview_test_cases: list[dict] = []
    evals_preview_eval_rows: list[dict] = []
    evals_preview_category_counts: list[dict] = []
    evals_is_exporting: bool = False
    evals_export_error: str = ""
    evals_export_success: bool = False
    evals_export_filename: str = ""
    _evals_output_zip_b64: str = ""

    # ── Dependencies ──────────────────────────────────────────────────────
    deps_is_analyzing: bool = False
    deps_error: str = ""
    deps_ran: bool = False
    deps_segments: list[dict] = []
    deps_relation_rows: list[dict] = []
    deps_component_rows: list[dict] = []
    deps_diagram_mode: str = "aggregated"  # "aggregated" | "detailed"
    deps_diagram_zoom_pct: int = 100
    deps_relation_query: str = ""
    deps_relation_sort_key: str = "dependent"  # dependent | dependent_type | required | required_type | source
    deps_relation_sort_dir: str = "asc"  # asc | desc
    deps_component_query: str = ""
    deps_component_sort_key: str = "name"  # name | schema | type | type_code | group | kind | source
    deps_component_sort_dir: str = "asc"  # asc | desc

    # ── Active tab ("rename" | "visualize" | "validate" | "check" | "evals" | "deps") ─────────
    active_tab: str = "visualize"

    # ── Processing ────────────────────────────────────────────────────────
    is_processing: bool = False
    process_error: str = ""
    process_success: bool = False

    # ── Result ────────────────────────────────────────────────────────────
    result_old_schema: str = ""
    result_new_schema: str = ""
    result_old_solution: str = ""
    result_new_solution: str = ""
    result_files_modified: int = 0
    result_folders_renamed: int = 0
    result_warnings: list[str] = []
    result_filename: str = ""
    # base64-encoded output ZIP bytes – used by the download event
    _output_zip_b64: str = ""
    # Private: MCS ZIP bytes persisted as base64 text for reactive state safety.
    _mcs_zip_b64: str = ""

    # ── Authentication ────────────────────────────────────────────────────
    username: str = ""
    password: str = ""
    is_authenticated: bool = False
    is_admin: bool = False
    auth_error: str = ""
    auth_info: str = ""
    requires_password_reset: bool = False

    request_email: str = ""
    request_captcha_token: str = ""
    request_error: str = ""
    request_info: str = ""
    request_success: bool = False

    approve_request_id: str = ""
    approval_error: str = ""
    approval_info: str = ""

    # ── Tutorial ──────────────────────────────────────────────────────────────
    tutorial_open: bool = False
    tutorial_step: int = 0  # 0-based; total steps defined in components.py

    def open_tutorial(self) -> None:
        """Open the guided tutorial and reset to the first step."""
        self.tutorial_step = 0
        self.tutorial_open = True

    def close_tutorial(self) -> None:
        """Close the tutorial dialog."""
        self.tutorial_open = False

    def next_tutorial_step(self) -> None:
        """Advance to the next step; close the dialog after the last step."""
        if self.tutorial_step < TUTORIAL_TOTAL_STEPS - 1:
            self.tutorial_step += 1
        else:
            self.tutorial_open = False

    def prev_tutorial_step(self) -> None:
        """Go back to the previous tutorial step."""
        if self.tutorial_step > 0:
            self.tutorial_step -= 1

    def set_tutorial_step(self, step: int) -> None:
        """Jump directly to a tutorial step (used by step-label clicks)."""
        self.tutorial_step = step

    def set_tutorial_open(self, open: bool) -> None:
        """Set tutorial dialog open state (used by dialog on_open_change)."""
        self.tutorial_open = open

    # ── ZIP type detection ────────────────────────────────────────────────────
    zip_type: str = ""  # "solution" | "snapshot"
    solution_has_agent_assets: bool = False

    # ── MCS Analyse ───────────────────────────────────────────────────────────
    mcs_upload_type: str = "mcs_zip"  # kept for backward compat
    mcs_is_processing: bool = False
    mcs_upload_error: str = ""
    mcs_report_markdown: str = ""
    mcs_report_title: str = ""
    mcs_source: str = ""  # "snapshot" | "transcript" | ""
    mcs_analyse_tab: str = "profile"  # active section sub-tab
    mcs_section_profile: str = ""
    mcs_section_knowledge_tools: str = ""
    mcs_section_topics: str = ""
    mcs_section_graph: str = ""
    mcs_section_model_comparison: str = ""
    mcs_section_model_comparison_live: str = ""
    mcs_section_conversation: str = ""
    mcs_section_credits: str = ""
    mcs_api_comparison_running: bool = False  # true while fetching live API comparison
    mcs_api_comparison_available: bool = False  # true if a report exists to run comparison on
    mcs_credit_rows: list[dict] = []
    mcs_credit_total: float = 0.0
    mcs_credit_assumptions: list[str] = []
    mcs_conversation_flow: list[dict] = []
    mcs_conversation_flow_source: str = ""  # "snapshot" | "transcript" | ""
    mcs_conv_kpis: list[dict] = []
    mcs_conv_event_mix: list[dict] = []
    mcs_conv_latency_bands: list[dict] = []
    mcs_conv_highlights: list[dict] = []
    mcs_dv_environment: str = ""
    mcs_dv_dataverse_url: str = ""
    mcs_dv_transcript_id: str = ""
    mcs_dv_use_env_auth: bool = True
    mcs_dv_token: str = ""
    mcs_dv_tenant_id: str = ""
    mcs_dv_client_id: str = ""
    mcs_dv_client_secret: str = ""
    mcs_dv_connection_ok: bool = False
    mcs_dv_connection_message: str = ""
    mcs_dv_last_source: str = ""
    mcs_dv_last_table: str = ""
    mcs_dv_last_transcript_id: str = ""
    mcs_dv_last_created_at: str = ""
    mcs_dv_last_conversation_id: str = ""
    mcs_landing_transcript_mode: str = "upload"  # upload | dataverse
    mcs_dv_auth_ok: bool = False
    mcs_dv_auth_message: str = ""
    _mcs_dv_session_token: str = ""
    mcs_dv_oauth_tenant_id: str = ""
    mcs_dv_oauth_client_id: str = ""
    mcs_dv_oauth_device_code: str = ""
    mcs_dv_oauth_user_code: str = ""
    mcs_dv_oauth_verify_uri: str = ""
    mcs_dv_oauth_message: str = ""

    _DEFAULT_DEVICE_CLIENT_ID: str = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

    # ── Computed / derived ────────────────────────────────────────────────

    @rx.var
    def has_upload(self) -> bool:
        return bool(self.zip_bytes_b64) or self.mcs_source == "transcript"

    @rx.var
    def signup_enabled(self) -> bool:
        return is_signup_enabled() and is_db_auth_enabled()

    @rx.var
    def admin_login_enabled(self) -> bool:
        return is_admin_login_enabled()

    @rx.var
    def turnstile_site_key(self) -> str:
        return os.getenv("TURNSTILE_SITE_KEY", "").strip()

    @rx.var
    def has_detection(self) -> bool:
        return bool(self.detected_bot_schema)

    @rx.var
    def has_visualization(self) -> bool:
        return len(self.viz_segments) > 0 or self.viz_display_name != ""

    @rx.var
    def viz_instructions_length_str(self) -> str:
        return f"{self.viz_instructions_length:,}"

    @rx.var
    def has_validation(self) -> bool:
        return self.validation_ran

    @rx.var
    def validation_pass_count(self) -> int:
        return sum(1 for r in self.validation_results if r.get("severity") == "pass")

    @rx.var
    def validation_warn_count(self) -> int:
        return sum(1 for r in self.validation_results if r.get("severity") == "warning")

    @rx.var
    def validation_fail_count(self) -> int:
        return sum(1 for r in self.validation_results if r.get("severity") == "fail")

    @rx.var
    def has_result_warnings(self) -> bool:
        return len(self.result_warnings) > 0

    @rx.var
    def has_check(self) -> bool:
        return self.check_ran

    @rx.var
    def check_filtered_results(self) -> list[dict]:
        if not self.check_active_category:
            return self.check_results
        return [r for r in self.check_results if r.get("category") == self.check_active_category]

    @rx.var
    def has_deps(self) -> bool:
        return bool(self.deps_segments)

    @rx.var
    def deps_visible_segments(self) -> list[dict]:
        """Visible dependency segments for current diagram mode.

        In detailed mode, keep only the diagram to reduce noise.
        """
        if self.deps_diagram_mode != "detailed":
            return self.deps_segments
        return [seg for seg in self.deps_segments if seg.get("type") == "mermaid"]

    @rx.var
    def deps_diagram_zoom_style(self) -> str:
        return f"{self.deps_diagram_zoom_pct}%"

    @rx.var
    def has_deps_relations(self) -> bool:
        return bool(self.deps_relation_rows)

    @rx.var
    def has_deps_components(self) -> bool:
        return bool(self.deps_component_rows)

    @rx.var
    def deps_filtered_component_rows(self) -> list[dict]:
        rows = list(self.deps_component_rows)

        query = (self.deps_component_query or "").strip().lower()
        if query:
            rows = [
                row
                for row in rows
                if query in (row.get("name", "").lower())
                or query in (row.get("schema", "").lower())
                or query in (row.get("type", "").lower())
                or query in (row.get("type_code", "").lower())
                or query in (row.get("group", "").lower())
                or query in (row.get("kind", "").lower())
                or query in (row.get("source", "").lower())
            ]

        if rows and self.deps_component_sort_key in rows[0]:
            sort_key = self.deps_component_sort_key
        else:
            sort_key = "name"
        reverse = self.deps_component_sort_dir == "desc"
        rows.sort(key=lambda r: (r.get(sort_key) or "").lower(), reverse=reverse)
        return rows

    @rx.var
    def deps_filtered_relation_rows(self) -> list[dict]:
        rows = list(self.deps_relation_rows)

        query = (self.deps_relation_query or "").strip().lower()
        if query:
            rows = [
                row
                for row in rows
                if query in (row.get("dependent", "").lower())
                or query in (row.get("dependent_type", "").lower())
                or query in (row.get("required", "").lower())
                or query in (row.get("required_type", "").lower())
                or query in (row.get("source", "").lower())
            ]

        if rows and self.deps_relation_sort_key in rows[0]:
            sort_key = self.deps_relation_sort_key
        else:
            sort_key = "dependent"
        reverse = self.deps_relation_sort_dir == "desc"
        rows.sort(key=lambda r: (r.get(sort_key) or "").lower(), reverse=reverse)
        return rows

    @rx.var
    def has_evals(self) -> bool:
        return bool(self.evals_test_sets) or bool(self.evals_eval_sets)

    @rx.var
    def evals_test_total(self) -> int:
        return len(self.evals_all_test_cases)

    @rx.var
    def evals_eval_total(self) -> int:
        return len(self.evals_all_eval_rows)

    @rx.var
    def evals_filtered_test_cases(self) -> list[dict]:
        if not self.evals_active_test_set:
            return self.evals_all_test_cases
        return [tc for tc in self.evals_all_test_cases if tc.get("set_schema") == self.evals_active_test_set]

    @rx.var
    def evals_filtered_eval_rows(self) -> list[dict]:
        if not self.evals_active_eval_set:
            return self.evals_all_eval_rows
        return [row for row in self.evals_all_eval_rows if row.get("set_schema") == self.evals_active_eval_set]

    @rx.var
    def has_eval_fit_report(self) -> bool:
        return self.evals_fit_ran

    @rx.var
    def has_eval_preview(self) -> bool:
        return bool(self.evals_preview_test_cases) or bool(self.evals_preview_eval_rows)

    @rx.var
    def can_improve_current_evals(self) -> bool:
        return self.has_evals and self.evals_should_offer_improve

    @rx.var
    def validation_instructions_length_str(self) -> str:
        return str(self.validation_instructions_length)

    @rx.var
    def can_process(self) -> bool:
        return (
            self.has_detection
            and bool(self.new_agent_name.strip())
            and bool(self.new_solution_display_name.strip())
            and bool(self.derived_solution_unique)
        )

    @rx.var
    def is_solution_zip(self) -> bool:
        return self.zip_type == "solution"

    @rx.var
    def is_agent_solution_zip(self) -> bool:
        return self.zip_type == "solution" and self.solution_has_agent_assets

    @rx.var
    def is_snapshot_zip(self) -> bool:
        return self.zip_type == "snapshot"

    @rx.var
    def has_mcs_report(self) -> bool:
        return bool(self.mcs_source)

    @rx.var
    def has_mcs_conversation_flow(self) -> bool:
        return bool(self.mcs_conversation_flow)

    @rx.var
    def has_mcs_conv_visual_summary(self) -> bool:
        return bool(self.mcs_conv_kpis)

    @rx.var
    def mcs_dv_manual_mode(self) -> bool:
        return not self.mcs_dv_use_env_auth

    @rx.var
    def mcs_dv_actions_locked(self) -> bool:
        return self.mcs_dv_manual_mode and (not self.mcs_dv_auth_ok)

    @rx.var
    def mcs_report_segments(self) -> list[dict]:
        """Full report segments (used for backward-compat / transcript flat view)."""
        return _md_to_segments(self.mcs_report_markdown)

    @rx.var
    def mcs_current_section_segments(self) -> list[dict]:
        """Segments for the currently active MCS analyse sub-tab."""
        model_section = self.mcs_section_model_comparison
        live_section = self.mcs_section_model_comparison_live
        if live_section.strip():
            if model_section.strip():
                model_section = f"{model_section}\n\n---\n\n{live_section}"
            else:
                model_section = live_section

        section_map = {
            "profile": self.mcs_section_profile,
            "knowledge_tools": self.mcs_section_knowledge_tools,
            "topics": self.mcs_section_topics,
            "graph": self.mcs_section_graph,
            "model_comparison": model_section,
            "conversation": self.mcs_section_conversation,
            "credits": self.mcs_section_credits,
        }
        md = section_map.get(self.mcs_analyse_tab, "")
        return _md_to_segments(md)

    @rx.var
    def mcs_env_api_key_present(self) -> bool:
        """Whether OPENAI_API_KEY is available in the current process environment."""
        return bool(os.getenv("OPENAI_API_KEY", "").strip())

    @rx.var
    def can_run_mcs_api_comparison(self) -> bool:
        """Whether live API comparison can be executed for the current report state."""
        has_snapshot_context = bool(self._mcs_zip_b64) or (
            self.zip_type == "snapshot" and bool(self.zip_bytes_b64)
        )
        return self.mcs_api_comparison_available and has_snapshot_context

    # ── Setters for evals filter state (required — auto-setters deprecated) ──

    @rx.event
    def set_evals_sub_tab(self, value: str):
        self.evals_sub_tab = value

    @rx.event
    def set_evals_active_test_set(self, value: str):
        self.evals_active_test_set = value

    @rx.event
    def set_evals_active_eval_set(self, value: str):
        self.evals_active_eval_set = value

    # ── Event handlers ────────────────────────────────────────────────────

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        """Receive and inspect the uploaded ZIP (solution or snapshot)."""
        if not files:
            return

        file = files[0]
        file_bytes = await file.read()

        if len(file_bytes) > _MAX_UPLOAD_BYTES:
            self.inspect_error = f"File too large (max {_MAX_UPLOAD_BYTES // 1024 // 1024} MB)."
            return

        if not file.filename.lower().endswith(".zip"):
            self.inspect_error = "Please upload a .zip file exported from Power Platform."
            return

        # ── Detect ZIP type synchronously before any state updates ────────
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as _zf:
                _names = _zf.namelist()
        except zipfile.BadZipFile:
            self.inspect_error = "The uploaded file is not a valid ZIP archive."
            return

        _has_solution = any(n == "bots" or n.startswith("bots/") for n in _names)
        _has_snapshot = any("botContent.yml" in n for n in _names)
        _has_solution_manifest = any(Path(n).name.lower() == "solution.xml" for n in _names)

        if not _has_solution and not _has_snapshot and not _has_solution_manifest:
            self.inspect_error = (
                "Unrecognised ZIP format — expected a Power Platform solution export "
                "(containing solution.xml / bots/) or a Copilot Studio snapshot ZIP "
                "(containing botContent.yml)."
            )
            return

        # ── Reset all upload-derived state ────────────────────────────────
        self.zip_type = "snapshot" if _has_snapshot else "solution"
        self.solution_has_agent_assets = _has_solution
        self.active_tab = "analyse" if _has_snapshot else ("visualize" if _has_solution else "deps")
        self.mcs_analyse_tab = "profile"
        self.zip_bytes_b64 = base64.b64encode(file_bytes).decode()
        self.upload_filename = file.filename
        self.is_inspecting = True
        self.inspect_error = ""
        self.no_agent_warning = ""
        self.process_success = False
        self.process_error = ""
        self.result_filename = ""
        self._output_zip_b64 = ""
        self.viz_segments = []
        self.viz_error = ""
        self.viz_display_name = ""
        self.viz_schema_name = ""
        self.viz_channels = []
        self.viz_recognizer = ""
        self.viz_model = ""
        self.viz_web_browsing = False
        self.viz_use_model_knowledge = False
        self.viz_instructions_length = 0
        self.viz_instructions_preview = ""
        self.viz_total = 0
        self.viz_active_count = 0
        self.viz_inactive_count = 0
        self.viz_category_stats = []
        self.viz_component_rows = []
        self.viz_mermaid = ""
        self.validation_ran = False
        self.validation_error = ""
        self.validation_results = []
        self.validation_model_key = ""
        self.validation_model_display = ""
        self.validation_best_practices = ""
        self.validation_instructions_length = 0
        self.show_best_practices = False
        self.check_ran = False
        self.check_error = ""
        self.check_results = []
        self.check_pass_count = 0
        self.check_warn_count = 0
        self.check_fail_count = 0
        self.check_info_count = 0
        self.check_agent_name = ""
        self.check_solution_name = ""
        self.check_active_category = ""
        self.evals_test_sets = []
        self.evals_eval_sets = []
        self.evals_all_test_cases = []
        self.evals_all_eval_rows = []
        self.evals_sub_tab = "tests"
        self.evals_active_test_set = ""
        self.evals_active_eval_set = ""
        self.evals_is_analyzing = False
        self.evals_fit_error = ""
        self.evals_fit_ran = False
        self.evals_fit_score = 0
        self.evals_fit_dimensions = []
        self.evals_fit_gaps = []
        self.evals_fit_recommendations = []
        self.evals_should_offer_improve = False
        self.evals_is_generating = False
        self.evals_preview_error = ""
        self.evals_preview_mode = ""
        self.evals_preview_test_sets = []
        self.evals_preview_eval_sets = []
        self.evals_preview_test_cases = []
        self.evals_preview_eval_rows = []
        self.evals_preview_category_counts = []
        self.evals_is_exporting = False
        self.evals_export_error = ""
        self.evals_export_success = False
        self.evals_export_filename = ""
        self._evals_output_zip_b64 = ""
        self.deps_is_analyzing = False
        self.deps_error = ""
        self.deps_ran = False
        self.deps_segments = []
        self.deps_relation_rows = []
        self.deps_component_rows = []
        self.deps_diagram_mode = "aggregated"
        self.deps_diagram_zoom_pct = 100
        self.deps_relation_query = ""
        self.deps_relation_sort_key = "dependent"
        self.deps_relation_sort_dir = "asc"
        self.deps_component_query = ""
        self.deps_component_sort_key = "name"
        self.deps_component_sort_dir = "asc"
        self.mcs_section_profile = ""
        self.mcs_section_knowledge_tools = ""
        self.mcs_section_topics = ""
        self.mcs_section_graph = ""
        self.mcs_section_model_comparison = ""
        self.mcs_section_model_comparison_live = ""
        self.mcs_section_conversation = ""
        self.mcs_section_credits = ""
        self.mcs_api_comparison_running = False
        self.mcs_api_comparison_available = False
        self._mcs_zip_b64 = ""
        self.mcs_credit_rows = []
        self.mcs_credit_total = 0.0
        self.mcs_credit_assumptions = []
        self.mcs_conversation_flow = []
        self.mcs_conversation_flow_source = ""
        self.mcs_conv_kpis = []
        self.mcs_conv_event_mix = []
        self.mcs_conv_latency_bands = []
        self.mcs_conv_highlights = []
        self.mcs_report_markdown = ""
        self.mcs_report_title = ""
        self.mcs_upload_error = ""
        self.mcs_source = ""
        self.detected_bot_schema = ""
        self.detected_bot_name = ""
        self.detected_solution_name = ""
        self.detected_solution_display = ""
        self.detected_component_count = 0
        if self.zip_type == "solution" and not _has_solution:
            self.no_agent_warning = (
                "This solution ZIP has no Copilot Studio agent assets (bots/). "
                "Dependencies analysis is available; rename/validate/check/evals require an agent solution ZIP."
            )
        yield

        if self.zip_type == "solution":
            if _has_solution:
                # ── Agent solution ZIP: inspect → visualize → validate ───────
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
                    tf.write(file_bytes)
                    tmp_path = Path(tf.name)
                try:
                    info = inspect_zip(tmp_path)
                    self.detected_bot_schema = info.bot_schema_name
                    self.detected_bot_name = info.bot_display_name
                    self.detected_solution_name = info.solution_unique_name
                    self.detected_solution_display = info.solution_display_name
                    self.detected_component_count = len(info.botcomponent_folders)
                    if not self.new_agent_name:
                        self.new_agent_name = info.bot_display_name + " Copy"
                    if not self.new_solution_display_name:
                        self.new_solution_display_name = info.solution_display_name + " Copy"
                    self._update_derived_schema()
                    self._update_derived_solution_unique()
                except Exception as exc:
                    self.inspect_error = f"Could not inspect ZIP: {exc}"
                finally:
                    os.unlink(tmp_path)
                    self.is_inspecting = False

                if not self.inspect_error:
                    self.is_visualizing = True
                    yield
                    try:
                        result = visualize_zip_bytes(file_bytes)
                        self.viz_display_name = result["display_name"]
                        self.viz_schema_name = result["schema_name"]
                        self.viz_channels = result["channels"]
                        self.viz_recognizer = result["recognizer"]
                        self.viz_model = result["model"]
                        self.viz_web_browsing = result["web_browsing"]
                        self.viz_use_model_knowledge = result["use_model_knowledge"]
                        self.viz_instructions_length = result["instructions_length"]
                        self.viz_instructions_preview = result["instructions_preview"]
                        self.viz_total = result["total"]
                        self.viz_active_count = result["active"]
                        self.viz_inactive_count = result["inactive"]
                        self.viz_category_stats = result["category_stats"]
                        self.viz_component_rows = result["component_rows"]
                        self.viz_mermaid = result["mermaid"]
                        self.viz_error = ""
                    except Exception as viz_exc:
                        self.viz_error = str(viz_exc)
                        self.viz_display_name = ""
                        self.viz_component_rows = []
                        self.viz_mermaid = ""
                    finally:
                        self.is_visualizing = False

                if not self.inspect_error:
                    self.is_validating = True
                    yield
                    try:
                        report = validate_zip_bytes(file_bytes)
                        self.validation_model_key = report["model_key"]
                        self.validation_model_display = report["model_display"]
                        self.validation_results = report["results"]
                        self.validation_best_practices = report.get("best_practices_md", "")
                        self.validation_instructions_length = report.get("instructions_length", 0)
                        self.validation_ran = True
                        self.validation_error = ""
                    except Exception as val_exc:
                        self.validation_error = str(val_exc)
                        self.validation_results = []
                        self.validation_ran = False
                    finally:
                        self.is_validating = False

                if not self.inspect_error:
                    self.is_checking = True
                    yield
                    try:
                        check_report = check_solution_zip(file_bytes)
                        if check_report["error"]:
                            self.check_error = check_report["error"]
                            self.check_ran = False
                        else:
                            self.check_results = check_report["results"]
                            self.check_pass_count = check_report["pass_count"]
                            self.check_warn_count = check_report["warn_count"]
                            self.check_fail_count = check_report["fail_count"]
                            self.check_info_count = check_report["info_count"]
                            self.check_agent_name = check_report["agent_name"]
                            self.check_solution_name = check_report["solution_name"]
                            self.check_ran = True
                            self.check_error = ""
                    except Exception as chk_exc:
                        self.check_error = str(chk_exc)
                        self.check_ran = False
                    finally:
                        self.is_checking = False

                if not self.inspect_error:
                    self.evals_is_analyzing = True
                    yield
                    try:
                        evals = get_evals_data(file_bytes)
                        test_sets_summary = []
                        all_test_cases = []
                        for ts in evals.get("test_sets", []):
                            test_sets_summary.append(
                                {
                                    "schema_name": ts["schema_name"],
                                    "display_name": ts["display_name"],
                                    "test_count": len(ts.get("test_cases", [])),
                                }
                            )
                            for tc in ts.get("test_cases", []):
                                all_test_cases.append(
                                    {
                                        "set_schema": ts["schema_name"],
                                        "set_name": ts["display_name"],
                                        "input": tc["input"],
                                        "expected_response": tc["expected_response"],
                                        "score_threshold": tc["score_threshold"],
                                        "origin_type": tc["origin_type"],
                                    }
                                )
                        eval_sets_summary = []
                        all_eval_rows = []
                        for es in evals.get("eval_sets", []):
                            eval_sets_summary.append(
                                {
                                    "schema_name": es["schema_name"],
                                    "display_name": es["display_name"],
                                    "graders": ", ".join(es.get("graders", [])) or "None",
                                    "row_count": len(es.get("rows", [])),
                                }
                            )
                            for row in es.get("rows", []):
                                all_eval_rows.append(
                                    {
                                        "set_schema": es["schema_name"],
                                        "set_name": es["display_name"],
                                        "input": row["input"],
                                        "expected_output": row["expected_output"],
                                        "keywords": " · ".join(row.get("keywords", [])),
                                        "source": row["source"],
                                    }
                                )
                        self.evals_test_sets = test_sets_summary
                        self.evals_all_test_cases = all_test_cases
                        self.evals_eval_sets = eval_sets_summary
                        self.evals_all_eval_rows = all_eval_rows
                    except Exception:
                        pass  # evals are non-critical; silently skip on error

                    try:
                        fit_report = analyze_evals_zip_bytes(file_bytes)
                        self.evals_fit_score = fit_report.get("score", 0)
                        self.evals_fit_dimensions = _decorate_fit_dimensions(fit_report.get("fit_dimensions", []))
                        self.evals_fit_gaps = fit_report.get("gaps", [])
                        self.evals_fit_recommendations = fit_report.get("recommendations", [])
                        self.evals_should_offer_improve = bool(fit_report.get("should_offer_improve", False))
                        self.evals_fit_error = ""
                        self.evals_fit_ran = True
                    except Exception as eval_exc:
                        self.evals_fit_error = str(eval_exc)
                        self.evals_fit_ran = False
                    finally:
                        self.evals_is_analyzing = False
            else:
                # Generic solution ZIP (no Copilot agent assets): run dependencies only.
                self.is_inspecting = False
                self.detected_solution_display = file.filename

            self.deps_is_analyzing = True
            yield
            try:
                report = analyze_deps_zip_bytes_report(
                    file_bytes,
                    detailed_diagram=self.deps_diagram_mode == "detailed",
                )
                self.deps_segments = [
                    {"type": "text", "content": report["summary_markdown"]},
                    {"type": "mermaid", "content": report["mermaid"]},
                ]
                self.deps_relation_rows = report.get("relation_rows", [])
                self.deps_component_rows = report.get("component_rows", [])
                self.deps_ran = True
                self.deps_error = ""
            except Exception as dep_exc:
                self.deps_error = str(dep_exc)
                self.deps_segments = []
                self.deps_relation_rows = []
                self.deps_component_rows = []
                self.deps_ran = False
            finally:
                self.deps_is_analyzing = False

        else:
            # ── Snapshot ZIP: parse → visualize (topic graph) → validate (instructions) → analyse ──
            self.is_inspecting = False
            with tempfile.TemporaryDirectory() as tmp_dir:
                snap_dir = Path(tmp_dir)
                zip_path = snap_dir / "snapshot.zip"
                zip_path.write_bytes(file_bytes)
                extracted = snap_dir / "extracted"
                with zipfile.ZipFile(zip_path) as zf:
                    safe_extractall(zf, extracted)

                bot_content = next((p for p in extracted.rglob("botContent.yml") if p.is_file()), None)
                if bot_content is None:
                    self.inspect_error = "Could not find botContent.yml inside the snapshot ZIP."
                    return

                try:
                    profile, schema_lookup = mcs_parse_yaml(bot_content)
                except Exception as exc:
                    self.inspect_error = f"Failed to parse snapshot: {exc}"
                    return

                self.detected_bot_schema = profile.schema_name
                self.detected_bot_name = profile.display_name
                self.detected_solution_display = profile.display_name
                self.detected_component_count = len(profile.components)
                self.mcs_report_title = profile.display_name or file.filename
                yield

                # Visualization
                self.is_visualizing = True
                yield
                try:
                    self.viz_segments = mcs_to_viz_segments(profile)
                    self.viz_error = ""
                except Exception as e:
                    self.viz_error = str(e)
                    self.viz_segments = []
                finally:
                    self.is_visualizing = False

                # Validation
                self.is_validating = True
                yield
                try:
                    gpt = profile.gpt_info
                    instructions = (gpt.instructions or "") if gpt else ""
                    hint = gpt.model_hint if gpt else None
                    report = validate_instructions(instructions, hint)
                    self.validation_model_key = report["model_key"]
                    self.validation_model_display = report["model_display"]
                    self.validation_results = report["results"]
                    self.validation_best_practices = report.get("best_practices_md", "")
                    self.validation_instructions_length = report.get("instructions_length", 0)
                    self.validation_ran = True
                    self.validation_error = ""
                except Exception as e:
                    self.validation_error = str(e)
                    self.validation_ran = False
                finally:
                    self.is_validating = False

                # MCS section analysis
                self.mcs_is_processing = True
                yield
                try:
                    dialog_json = next((p for p in extracted.rglob("dialog.json") if p.is_file()), None)
                    activities: list[dict] = []
                    if dialog_json:
                        activities = mcs_parse_dialog_json(dialog_json)
                        timeline = mcs_build_timeline(activities, schema_lookup)
                    else:
                        timeline = _MCSTl()

                    sections = mcs_render_report_sections(profile, timeline)
                    self.mcs_section_profile = sections["profile"]
                    self.mcs_section_knowledge_tools = sections.get("knowledge_tools", "")
                    self.mcs_section_topics = sections["topics"]
                    self.mcs_section_graph = sections["graph"]
                    self.mcs_section_model_comparison = sections.get("model_comparison", "")
                    self.mcs_section_model_comparison_live = ""
                    self.mcs_section_conversation = sections["conversation"]
                    estimate = estimate_credits_from_activities(
                        activities, profile.gpt_info.model_hint if profile.gpt_info else None
                    )
                    self.mcs_section_credits = mcs_render_credit_estimate("Credit Prediction", estimate)
                    self.mcs_credit_rows = [
                        {
                            "meter": "Classic answer",
                            "count": estimate.classic_answers,
                            "rate": "1",
                            "credits": estimate.classic_credits,
                        },
                        {
                            "meter": "Generative answer",
                            "count": estimate.generative_answers,
                            "rate": "2",
                            "credits": estimate.generative_credits,
                        },
                        {
                            "meter": "Agent action",
                            "count": estimate.agent_actions,
                            "rate": "5",
                            "credits": estimate.agent_action_credits,
                        },
                        {
                            "meter": "Tenant graph grounding (messages)",
                            "count": estimate.tenant_graph_grounding_messages,
                            "rate": "10",
                            "credits": estimate.tenant_graph_credits,
                        },
                        {
                            "meter": "Agent flow actions",
                            "count": estimate.agent_flow_actions,
                            "rate": "13 / 100",
                            "credits": estimate.agent_flow_credits,
                        },
                        {
                            "meter": "Text/gen AI tools (premium) responses",
                            "count": estimate.premium_tool_responses,
                            "rate": "100 / 10",
                            "credits": estimate.premium_tool_credits,
                        },
                    ]
                    self.mcs_credit_total = estimate.total_credits
                    self.mcs_credit_assumptions = estimate.assumptions
                    self.mcs_conversation_flow = mcs_build_conversation_flow_items(timeline)
                    self.mcs_conversation_flow_source = "snapshot"
                    conv_summary = mcs_build_conversation_visual_summary(timeline)
                    self.mcs_conv_kpis = conv_summary.get("kpis", [])
                    self.mcs_conv_event_mix = conv_summary.get("event_mix", [])
                    self.mcs_conv_latency_bands = conv_summary.get("latency_bands", [])
                    self.mcs_conv_highlights = conv_summary.get("highlights", [])
                    self.mcs_source = "snapshot"
                    self.mcs_report_markdown = self._compose_mcs_report_markdown()
                    self.mcs_api_comparison_available = True  # enable on-demand API comparison
                    self._mcs_zip_b64 = base64.b64encode(file_bytes).decode("ascii")
                    self.mcs_upload_error = ""
                except Exception as e:
                    self.mcs_upload_error = f"Snapshot analysis failed: {e}"
                    self.mcs_api_comparison_available = False
                    self._mcs_zip_b64 = ""
                finally:
                    self.mcs_is_processing = False

    @rx.event
    def set_new_agent_name(self, value: str):
        self.new_agent_name = value
        self._update_derived_schema()

    @rx.event
    def set_new_solution_display_name(self, value: str):
        self.new_solution_display_name = value
        self._update_derived_solution_unique()

    @rx.event
    async def process(self):
        """Run the rename operation and prepare the output ZIP for download."""
        if not self.can_process:
            return

        self.is_processing = True
        self.process_error = ""
        self.process_success = False
        yield

        try:
            zip_bytes = base64.b64decode(self.zip_bytes_b64)
            output_bytes, result = rename_solution_from_bytes(
                zip_bytes=zip_bytes,
                new_agent_name=self.new_agent_name.strip(),
                new_solution_name=self.derived_solution_unique,
                new_solution_display_name=self.new_solution_display_name.strip(),
            )
            self.result_old_schema = result.old_bot_schema
            self.result_new_schema = result.new_bot_schema
            self.result_old_solution = result.old_solution_name
            self.result_new_solution = result.new_solution_name
            self.result_files_modified = result.files_modified
            self.result_folders_renamed = result.folders_renamed
            self.result_warnings = result.warnings
            self.result_filename = f"{self.derived_solution_unique}.zip"
            self._output_zip_b64 = base64.b64encode(output_bytes).decode("ascii")
            self.process_success = True
        except Exception as exc:
            self.process_error = f"Rename failed: {exc}\n{traceback.format_exc()}"
        finally:
            self.is_processing = False

    @rx.event
    async def generate_eval_samples(self):
        if not self.zip_bytes_b64:
            return

        self.evals_is_generating = True
        self.evals_preview_error = ""
        self.evals_export_error = ""
        self.evals_export_success = False
        yield

        try:
            preview = preview_generated_evals(base64.b64decode(self.zip_bytes_b64), mode="generate", target_count=24)
            self.evals_preview_mode = preview.get("mode", "generate")
            self.evals_preview_test_sets = preview.get("test_sets", [])
            self.evals_preview_eval_sets = preview.get("eval_sets", [])
            self.evals_preview_test_cases = preview.get("test_cases", [])
            self.evals_preview_eval_rows = preview.get("eval_rows", [])
            self.evals_preview_category_counts = preview.get("category_counts", [])
        except Exception as exc:
            self.evals_preview_error = f"Eval generation failed: {exc}"
        finally:
            self.evals_is_generating = False

    @rx.event
    async def improve_current_evals(self):
        if not self.zip_bytes_b64:
            return

        self.evals_is_generating = True
        self.evals_preview_error = ""
        self.evals_export_error = ""
        self.evals_export_success = False
        yield

        try:
            preview = preview_generated_evals(base64.b64decode(self.zip_bytes_b64), mode="improve", target_count=24)
            self.evals_preview_mode = preview.get("mode", "improve")
            self.evals_preview_test_sets = preview.get("test_sets", [])
            self.evals_preview_eval_sets = preview.get("eval_sets", [])
            self.evals_preview_test_cases = preview.get("test_cases", [])
            self.evals_preview_eval_rows = preview.get("eval_rows", [])
            self.evals_preview_category_counts = preview.get("category_counts", [])
        except Exception as exc:
            self.evals_preview_error = f"Eval improvement failed: {exc}"
        finally:
            self.evals_is_generating = False

    @rx.event
    async def export_eval_solution(self):
        if not self.zip_bytes_b64 or not self.evals_preview_mode:
            return

        self.evals_is_exporting = True
        self.evals_export_error = ""
        self.evals_export_success = False
        yield

        try:
            output_bytes, preview = export_solution_with_evals(
                base64.b64decode(self.zip_bytes_b64),
                mode=self.evals_preview_mode,
                target_count=max(20, len(self.evals_preview_test_cases) or 24),
            )
            self._evals_output_zip_b64 = base64.b64encode(output_bytes).decode("ascii")
            suffix = "improved" if preview.get("mode") == "improve" else "generated"
            base_name = Path(self.upload_filename or "solution.zip").stem
            self.evals_export_filename = f"{base_name}_{suffix}_evals.zip"
            self.evals_export_success = True
        except Exception as exc:
            self.evals_export_error = f"Eval export failed: {exc}"
        finally:
            self.evals_is_exporting = False

    @rx.event
    def download_eval_solution(self):
        if not self._evals_output_zip_b64 or not self.evals_export_filename:
            return
        return rx.download(
            data=base64.b64decode(self._evals_output_zip_b64),
            filename=self.evals_export_filename,
            mime_type="application/zip",
        )

    @rx.event
    def download_result(self):
        """Trigger a browser download of the renamed ZIP using a data URL.

        This bypasses cross-origin and browser-specific issues that can arise
        when linking directly to the backend upload URL from the Vite frontend.
        """
        if not self._output_zip_b64 or not self.result_filename:
            return
        zip_bytes = base64.b64decode(self._output_zip_b64)
        return rx.download(
            data=zip_bytes,
            filename=self.result_filename,
            mime_type="application/zip",
        )

    @rx.event
    def clear_all(self):
        self.upload_filename = ""
        self.zip_bytes_b64 = ""
        self.is_inspecting = False
        self.inspect_error = ""
        self.detected_bot_schema = ""
        self.detected_bot_name = ""
        self.detected_solution_name = ""
        self.detected_solution_display = ""
        self.detected_component_count = 0
        self.new_agent_name = ""
        self.new_solution_display_name = ""
        self.derived_schema = ""
        self.derived_solution_unique = ""
        self.is_processing = False
        self.process_error = ""
        self.process_success = False
        self.result_old_schema = ""
        self.result_new_schema = ""
        self.result_old_solution = ""
        self.result_new_solution = ""
        self.result_files_modified = 0
        self.result_folders_renamed = 0
        self.result_warnings = []
        self.result_filename = ""
        self._output_zip_b64 = ""
        self.viz_error = ""
        self.is_visualizing = False
        self.is_validating = False
        self.validation_error = ""
        self.validation_ran = False
        self.validation_model_key = ""
        self.validation_model_display = ""
        self.validation_results = []
        self.validation_best_practices = ""
        self.validation_instructions_length = 0
        self.show_best_practices = False
        self.is_checking = False
        self.check_error = ""
        self.check_ran = False
        self.check_results = []
        self.check_pass_count = 0
        self.check_warn_count = 0
        self.check_fail_count = 0
        self.check_info_count = 0
        self.check_agent_name = ""
        self.check_solution_name = ""
        self.check_active_category = ""
        self.evals_test_sets = []
        self.evals_eval_sets = []
        self.evals_all_test_cases = []
        self.evals_all_eval_rows = []
        self.evals_sub_tab = "tests"
        self.evals_active_test_set = ""
        self.evals_active_eval_set = ""
        self.evals_is_analyzing = False
        self.evals_fit_error = ""
        self.evals_fit_ran = False
        self.evals_fit_score = 0
        self.evals_fit_dimensions = []
        self.evals_fit_gaps = []
        self.evals_fit_recommendations = []
        self.evals_should_offer_improve = False
        self.evals_is_generating = False
        self.evals_preview_error = ""
        self.evals_preview_mode = ""
        self.evals_preview_test_sets = []
        self.evals_preview_eval_sets = []
        self.evals_preview_test_cases = []
        self.evals_preview_eval_rows = []
        self.evals_preview_category_counts = []
        self.evals_is_exporting = False
        self.evals_export_error = ""
        self.evals_export_success = False
        self.evals_export_filename = ""
        self._evals_output_zip_b64 = ""
        self.no_agent_warning = ""
        self.active_tab = "visualize"
        self.zip_type = ""
        self.solution_has_agent_assets = False
        self.deps_is_analyzing = False
        self.deps_error = ""
        self.deps_ran = False
        self.deps_segments = []
        self.deps_relation_rows = []
        self.deps_component_rows = []
        self.deps_diagram_mode = "aggregated"
        self.deps_relation_query = ""
        self.deps_relation_sort_key = "dependent"
        self.deps_relation_sort_dir = "asc"
        self.mcs_source = ""
        self.mcs_section_profile = ""
        self.mcs_section_knowledge_tools = ""
        self.mcs_section_topics = ""
        self.mcs_section_graph = ""
        self.mcs_section_conversation = ""
        self.mcs_section_model_comparison = ""
        self.mcs_section_model_comparison_live = ""
        self.mcs_section_credits = ""
        self.mcs_api_comparison_running = False
        self.mcs_api_comparison_available = False
        self._mcs_zip_b64 = ""
        self.mcs_credit_rows = []
        self.mcs_credit_total = 0.0
        self.mcs_credit_assumptions = []
        self.mcs_conversation_flow = []
        self.mcs_conversation_flow_source = ""
        self.mcs_conv_kpis = []
        self.mcs_conv_event_mix = []
        self.mcs_conv_latency_bands = []
        self.mcs_conv_highlights = []
        self.mcs_analyse_tab = "profile"
        self.mcs_dv_environment = ""
        self.mcs_dv_dataverse_url = ""
        self.mcs_dv_transcript_id = ""
        self.mcs_dv_use_env_auth = True
        self.mcs_dv_token = ""
        self.mcs_dv_tenant_id = ""
        self.mcs_dv_client_id = ""
        self.mcs_dv_client_secret = ""
        self.mcs_dv_connection_ok = False
        self.mcs_dv_connection_message = ""
        self.mcs_dv_last_source = ""
        self.mcs_dv_last_table = ""
        self.mcs_dv_last_transcript_id = ""
        self.mcs_dv_last_created_at = ""
        self.mcs_dv_last_conversation_id = ""
        self.mcs_landing_transcript_mode = "upload"
        self.mcs_dv_auth_ok = False
        self.mcs_dv_auth_message = ""
        self._mcs_dv_session_token = ""
        self.mcs_dv_oauth_tenant_id = ""
        self.mcs_dv_oauth_client_id = ""
        self.mcs_dv_oauth_device_code = ""
        self.mcs_dv_oauth_user_code = ""
        self.mcs_dv_oauth_verify_uri = ""
        self.mcs_dv_oauth_message = ""
        self.mcs_dv_auth_ok = False
        self.mcs_dv_auth_message = ""
        self._mcs_dv_session_token = ""
        self.mcs_dv_oauth_tenant_id = ""
        self.mcs_dv_oauth_client_id = ""
        self.mcs_dv_oauth_device_code = ""
        self.mcs_dv_oauth_user_code = ""
        self.mcs_dv_oauth_verify_uri = ""
        self.mcs_dv_oauth_message = ""
        self.mcs_landing_transcript_mode = "upload"
        self.mcs_report_markdown = ""
        self.mcs_report_title = ""
        self.mcs_upload_error = ""

    @rx.event
    def set_active_tab(self, tab: str):
        self.active_tab = tab

    @rx.event
    def toggle_best_practices(self):
        self.show_best_practices = not self.show_best_practices

    @rx.event
    def set_check_active_category(self, category: str):
        self.check_active_category = category

    @rx.event
    async def set_deps_diagram_mode(self, mode: str):
        if mode not in ("aggregated", "detailed"):
            return
        if self.deps_diagram_mode == mode:
            return
        self.deps_diagram_mode = mode

        # Re-render dependency report for the current ZIP without requiring re-upload.
        if self.zip_type != "solution" or not self.zip_bytes_b64:
            return

        self.deps_is_analyzing = True
        self.deps_error = ""
        yield
        try:
            file_bytes = base64.b64decode(self.zip_bytes_b64)
            report = analyze_deps_zip_bytes_report(file_bytes, detailed_diagram=mode == "detailed")
            self.deps_segments = [
                {"type": "text", "content": report["summary_markdown"]},
                {"type": "mermaid", "content": report["mermaid"]},
            ]
            self.deps_relation_rows = report.get("relation_rows", [])
            self.deps_component_rows = report.get("component_rows", [])
            self.deps_ran = True
        except Exception as dep_exc:
            self.deps_error = str(dep_exc)
            self.deps_segments = []
            self.deps_relation_rows = []
            self.deps_component_rows = []
            self.deps_ran = False
        finally:
            self.deps_is_analyzing = False

    @rx.event
    def set_deps_relation_query(self, value: str):
        self.deps_relation_query = value

    @rx.event
    def set_deps_relation_sort(self, key: str):
        if key not in ("dependent", "dependent_type", "required", "required_type", "source"):
            return
        if self.deps_relation_sort_key == key:
            self.deps_relation_sort_dir = "desc" if self.deps_relation_sort_dir == "asc" else "asc"
            return
        self.deps_relation_sort_key = key
        self.deps_relation_sort_dir = "asc"

    @rx.event
    def set_deps_component_query(self, value: str):
        self.deps_component_query = value

    @rx.event
    def set_deps_component_sort(self, key: str):
        if key not in ("name", "schema", "type", "type_code", "group", "kind", "source"):
            return
        if self.deps_component_sort_key == key:
            self.deps_component_sort_dir = "desc" if self.deps_component_sort_dir == "asc" else "asc"
            return
        self.deps_component_sort_key = key
        self.deps_component_sort_dir = "asc"

    @rx.event
    def deps_zoom_in(self):
        self.deps_diagram_zoom_pct = min(220, self.deps_diagram_zoom_pct + 10)

    @rx.event
    def deps_zoom_out(self):
        self.deps_diagram_zoom_pct = max(50, self.deps_diagram_zoom_pct - 10)

    @rx.event
    def deps_zoom_reset(self):
        self.deps_diagram_zoom_pct = 100

    # ── Authentication handlers ───────────────────────────────────────────

    @rx.event
    def set_username(self, value: str):
        self.username = value
        self.auth_error = ""
        self.auth_info = ""

    @rx.event
    def set_password(self, value: str):
        self.password = value
        self.auth_error = ""
        self.auth_info = ""

    @rx.event
    def set_request_email(self, value: str):
        self.request_email = value
        self.request_error = ""
        self.request_info = ""
        self.request_success = False

    @rx.event
    def set_request_captcha_token(self, value: str):
        self.request_captcha_token = value
        self.request_error = ""

    @rx.event
    def login(self):
        """Validate credentials against DB-backed users first, then USERS env var."""
        username = (self.username or "").strip().lower()

        admin_result = authenticate_env_admin(username, self.password)
        if admin_result.success:
            self.is_authenticated = True
            self.is_admin = True
            self.username = username
            self.auth_error = ""
            self.auth_info = ""
            self.requires_password_reset = False
            self.password = ""
            return rx.redirect("/request-approval")
        if admin_result.message:
            self.auth_error = admin_result.message
            self.auth_info = ""
            return

        if is_db_auth_enabled():
            try:
                ensure_auth_schema()
                db_result = authenticate_db_user(username, self.password)
            except Exception:
                self.auth_error = "Authentication is temporarily unavailable."
                self.auth_info = ""
                return

            if db_result.success:
                self.is_authenticated = True
                self.is_admin = False
                self.username = username
                self.auth_error = ""
                self.auth_info = ""
                self.requires_password_reset = db_result.requires_password_reset
                self.password = ""
                if self.requires_password_reset:
                    self.auth_info = "Your temporary password was accepted. Please contact admin to reset password support flow."
                return rx.redirect("/")

            if db_result.message:
                self.auth_error = db_result.message
                self.auth_info = ""
                return

        users = _load_users()
        if not users:
            self.auth_error = "No users configured. Set the USERS environment variable."
            self.auth_info = ""
            return
        pw_hash = hashlib.pbkdf2_hmac("sha256", self.password.encode(), username.encode(), 100_000).hex()
        if users.get(username) == pw_hash:
            self.is_authenticated = True
            self.is_admin = False
            self.username = username
            self.auth_error = ""
            self.auth_info = ""
            self.password = ""  # clear password from state
            return rx.redirect("/")
        self.auth_error = "Invalid username or password."
        self.auth_info = ""

    @rx.event
    def login_submit(self, _form_data: dict[str, Any]):
        """Handle login form submit so Enter key triggers authentication."""
        return self.login()

    @rx.event
    def submit_account_request(self, _form_data: dict[str, Any]):
        """Validate captcha and store account request as pending approval."""
        self.request_error = ""
        self.request_info = ""
        self.request_success = False

        if not (is_signup_enabled() and is_db_auth_enabled()):
            self.request_error = "Account requests are not enabled in this environment."
            return

        email = (_form_data.get("email") or self.request_email or "").strip().lower()
        if not email or not re.fullmatch(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", email):
            self.request_error = "Enter a valid email address."
            return

        # Prefer form_data value (current DOM value, bypasses React controlled-input
        # reset race) and fall back to state in case form_data is unavailable.
        captcha_token = (_form_data.get("captcha_token") or self.request_captcha_token or "").strip()
        try:
            captcha_ok, captcha_msg = verify_turnstile(captcha_token)
        except Exception:
            self.request_error = "Captcha verification is temporarily unavailable. Please try again."
            return
        if not captcha_ok:
            self.request_error = captcha_msg or "Captcha validation failed."
            return

        try:
            ok, message = create_account_request(email=email)
        except Exception:
            self.request_error = "Unable to submit request. Please try again later."
            return
        if not ok:
            self.request_error = message
            return

        self.request_success = True
        self.request_info = message
        self.request_email = ""
        self.request_captcha_token = ""

    @rx.event
    def set_approve_request_id(self, value: str):
        self.approve_request_id = value
        self.approval_error = ""
        self.approval_info = ""

    @rx.event
    def approve_pending_request(self):
        """Approve a pending account request and send credentials via ACS."""
        self.approval_error = ""
        self.approval_info = ""

        if not self.is_authenticated:
            self.approval_error = "Sign in as an admin before approving requests."
            return
        if not self.is_admin:
            self.approval_error = "Only the configured admin account can approve requests."
            return

        ok, message = approve_account_request(self.approve_request_id, self.username)
        if not ok:
            self.approval_error = message
            return
        self.approval_info = message
        self.approve_request_id = ""

    @rx.event
    def logout(self):
        self.is_authenticated = False
        self.is_admin = False
        self.username = ""
        self.password = ""
        self.auth_error = ""
        self.auth_info = ""
        self.requires_password_reset = False
        return rx.redirect("/login")

    @rx.event
    def check_auth(self):
        """Redirect to /login when any authentication mode is configured."""
        env_auth_enabled = bool(os.getenv("USERS", "").strip())
        if (env_auth_enabled or is_db_auth_enabled()) and not self.is_authenticated:
            return rx.redirect("/login")

    @rx.event
    def check_already_authed(self):
        """Redirect away from the login page if already authenticated."""
        if self.is_authenticated:
            return rx.redirect("/")

    # ── MCS Analyse handlers ──────────────────────────────────────────────

    @rx.event
    def set_mcs_upload_type(self, value: str):
        self.mcs_upload_type = value

    @rx.event
    def set_mcs_analyse_tab(self, tab: str):
        self.mcs_analyse_tab = tab

    @rx.event
    async def run_mcs_api_comparison(self):
        """Run on-demand live API comparison for the current profile."""
        self.mcs_analyse_tab = "model_comparison"
        self.mcs_section_model_comparison_live = (
            "### Live API Comparison\n\n"
            "> ⏳ **Running analysis...**\n\n"
            "Executing sample queries against configured models. "
            "This can take up to 30 seconds.\n"
        )
        self.mcs_api_comparison_running = True
        yield

        try:
            from model_comparison import run_live_api_comparison
            from toolkit.mcs.parser import parse_zip_bytes

            # Re-parse the profile from stored ZIP bytes
            if not self.mcs_api_comparison_available:
                self.mcs_section_model_comparison_live = (
                    "### Live API Comparison\n\n"
                    "> ⚠️ **Comparison unavailable**\n\n"
                    "Upload and analyse a snapshot ZIP first to run live API comparison.\n"
                )
                return

            source_b64 = self._mcs_zip_b64 or (self.zip_bytes_b64 if self.zip_type == "snapshot" else "")
            if not source_b64:
                self.mcs_section_model_comparison_live = (
                    "### Live API Comparison\n\n"
                    "> ⚠️ **Snapshot context missing**\n\n"
                    "The snapshot context was not found in session state. "
                    "Please re-upload the snapshot ZIP and try again.\n"
                )
                return

            zip_bytes = base64.b64decode(source_b64)
            profile = parse_zip_bytes(zip_bytes)
            if not profile:
                raise RuntimeError("Could not extract profile from snapshot")

            result = run_live_api_comparison(profile)
            self.mcs_section_model_comparison_live = result
        except Exception as e:
            self.mcs_section_model_comparison_live = f"> ⚠️ **API Comparison Failed**\n\n{str(e)}"
        finally:
            self.mcs_api_comparison_running = False

    @rx.event
    def set_mcs_landing_transcript_mode(self, value: str):
        mode = (value or "").strip().lower()
        self.mcs_landing_transcript_mode = "dataverse" if mode == "dataverse" else "upload"

    @rx.event
    def set_mcs_dv_environment(self, value: str):
        self.mcs_dv_environment = value
        self.mcs_dv_connection_message = ""

    @rx.event
    def set_mcs_dv_dataverse_url(self, value: str):
        self.mcs_dv_dataverse_url = value
        self.mcs_dv_connection_message = ""

    @rx.event
    def set_mcs_dv_transcript_id(self, value: str):
        self.mcs_dv_transcript_id = value

    @rx.event
    def set_mcs_dv_token(self, value: str):
        self.mcs_dv_token = value
        self.mcs_dv_auth_ok = False
        self.mcs_dv_auth_message = ""
        self._mcs_dv_session_token = ""

    @rx.event
    def set_mcs_dv_tenant_id(self, value: str):
        self.mcs_dv_tenant_id = value
        self.mcs_dv_auth_ok = False
        self.mcs_dv_auth_message = ""
        self._mcs_dv_session_token = ""

    @rx.event
    def set_mcs_dv_client_id(self, value: str):
        self.mcs_dv_client_id = value
        self.mcs_dv_auth_ok = False
        self.mcs_dv_auth_message = ""
        self._mcs_dv_session_token = ""

    @rx.event
    def set_mcs_dv_client_secret(self, value: str):
        self.mcs_dv_client_secret = value
        self.mcs_dv_auth_ok = False
        self.mcs_dv_auth_message = ""
        self._mcs_dv_session_token = ""

    @rx.event
    def set_mcs_dv_oauth_tenant_id(self, value: str):
        self.mcs_dv_oauth_tenant_id = value

    @rx.event
    def set_mcs_dv_oauth_client_id(self, value: str):
        self.mcs_dv_oauth_client_id = value

    @rx.event
    def use_mcs_dv_default_oauth_client_id(self):
        """Apply a known public-client ID as a convenience preset."""
        self.mcs_dv_oauth_client_id = self._DEFAULT_DEVICE_CLIENT_ID
        self.mcs_dv_oauth_message = (
            "Applied default public client ID preset. "
            "If your tenant blocks it, replace with your app registration client ID."
        )

    @rx.event
    def start_mcs_dataverse_device_login(self):
        """Start OAuth device-code sign-in flow for smoother UI auth."""
        environment = self.mcs_dv_environment.strip()
        dataverse_url = self.mcs_dv_dataverse_url.strip()
        if not environment and not dataverse_url:
            self.mcs_upload_error = "Provide either Environment ID/URL or Dataverse URL."
            return

        tenant_id = self.mcs_dv_oauth_tenant_id.strip() or self.mcs_dv_tenant_id.strip()
        client_id = self.mcs_dv_oauth_client_id.strip() or self.mcs_dv_client_id.strip()
        if not tenant_id or not client_id:
            self.mcs_upload_error = "OAuth Device Code requires Tenant ID and Client ID."
            return

        self.mcs_is_processing = True
        self.mcs_upload_error = ""
        self.mcs_dv_oauth_message = "Starting device-code sign in..."
        yield

        try:
            result = begin_device_code_auth(
                environment=environment or dataverse_url,
                dataverse_url=dataverse_url or None,
                tenant_id=tenant_id,
                client_id=client_id,
            )
            self.mcs_dv_oauth_device_code = str(result.get("device_code", ""))
            self.mcs_dv_oauth_user_code = str(result.get("user_code", ""))
            self.mcs_dv_oauth_verify_uri = str(result.get("verification_uri_complete", "")) or str(
                result.get("verification_uri", "")
            )
            resolved_url = str(result.get("dataverse_url", ""))
            if resolved_url and not self.mcs_dv_dataverse_url.strip():
                self.mcs_dv_dataverse_url = resolved_url
            default_message = "Open the verification URL, enter the user code, then click Complete Device Login."
            self.mcs_dv_oauth_message = str(result.get("message", "")).strip() or default_message
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = "Device login started. Complete sign-in then click Complete Device Login."
        except RemoteFetchError as exc:
            self.mcs_dv_oauth_message = f"Device login start failed: {exc}"
        except Exception as exc:
            self.mcs_dv_oauth_message = f"Device login start failed: {exc}"
        finally:
            self.mcs_is_processing = False

    @rx.event
    def complete_mcs_dataverse_device_login(self):
        """Complete OAuth device-code flow and store session token."""
        tenant_id = self.mcs_dv_oauth_tenant_id.strip() or self.mcs_dv_tenant_id.strip()
        client_id = self.mcs_dv_oauth_client_id.strip() or self.mcs_dv_client_id.strip()
        device_code = self.mcs_dv_oauth_device_code.strip()
        if not tenant_id or not client_id or not device_code:
            self.mcs_upload_error = "Start Device Login first (Tenant ID, Client ID and device code are required)."
            return

        self.mcs_is_processing = True
        self.mcs_upload_error = ""
        self.mcs_dv_oauth_message = "Completing device-code sign in..."
        yield

        try:
            result = complete_device_code_auth(
                tenant_id=tenant_id,
                client_id=client_id,
                device_code=device_code,
            )
            if str(result.get("status", "")).lower() == "pending":
                self.mcs_dv_oauth_message = str(
                    result.get("message", "Authorization pending. Complete sign-in and retry.")
                )
                self.mcs_dv_auth_ok = False
                self.mcs_dv_auth_message = (
                    "Device login pending. Complete sign-in and click Complete Device Login again."
                )
            else:
                self._mcs_dv_session_token = str(result.get("access_token", ""))
                self.mcs_dv_auth_ok = bool(self._mcs_dv_session_token)
                self.mcs_dv_auth_message = "Device login successful. Session token is ready for Test/Fetch."
                self.mcs_dv_oauth_message = "Device login completed."
        except RemoteFetchError as exc:
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = f"Device login failed: {exc}"
            self.mcs_dv_oauth_message = self.mcs_dv_auth_message
        except Exception as exc:
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = f"Device login failed: {exc}"
            self.mcs_dv_oauth_message = self.mcs_dv_auth_message
        finally:
            self.mcs_is_processing = False

    @rx.event
    def set_mcs_dv_use_env_auth(self, value: bool):
        self.mcs_dv_use_env_auth = bool(value)
        self.mcs_dv_auth_ok = False
        self.mcs_dv_auth_message = ""
        self._mcs_dv_session_token = ""
        if self.mcs_dv_use_env_auth:
            self.mcs_dv_token = ""
            self.mcs_dv_tenant_id = ""
            self.mcs_dv_client_id = ""
            self.mcs_dv_client_secret = ""

    @rx.event
    def authenticate_mcs_dataverse(self):
        """Acquire Dataverse token explicitly for container deployments without pac auth."""
        environment = self.mcs_dv_environment.strip()
        dataverse_url = self.mcs_dv_dataverse_url.strip()
        if not environment and not dataverse_url:
            self.mcs_upload_error = "Provide either Environment ID/URL or Dataverse URL."
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = "Authentication failed: missing Environment ID/URL or Dataverse URL."
            return

        self.mcs_is_processing = True
        self.mcs_upload_error = ""
        self.mcs_dv_auth_ok = False
        self.mcs_dv_auth_message = "Authenticating..."
        yield

        if self.mcs_dv_use_env_auth and not has_dataverse_env_credentials():
            self.mcs_dv_use_env_auth = False
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = (
                "Environment credentials were not found. Switched to Manual Auth automatically. "
                "Provide bearer token or tenant/client/secret and click Authenticate again."
            )
            self.mcs_is_processing = False
            return

        auth: DataverseAuthConfig | None = None
        if not self.mcs_dv_use_env_auth:
            auth = DataverseAuthConfig(
                token=self.mcs_dv_token.strip() or None,
                tenant_id=self.mcs_dv_tenant_id.strip() or None,
                client_id=self.mcs_dv_client_id.strip() or None,
                client_secret=self.mcs_dv_client_secret.strip() or None,
            )

        try:
            result = authenticate_dataverse(
                environment=environment or dataverse_url,
                dataverse_url=dataverse_url or None,
                auth=auth,
            )
            self._mcs_dv_session_token = str(result.get("access_token", ""))
            resolved_url = str(result.get("dataverse_url", ""))
            if resolved_url and not self.mcs_dv_dataverse_url.strip():
                self.mcs_dv_dataverse_url = resolved_url
            self.mcs_dv_auth_ok = True
            self.mcs_dv_auth_message = "Authentication successful. Token stored for this session."
        except RemoteFetchError as exc:
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = f"Authentication failed: {exc}"
        except Exception as exc:
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = f"Authentication failed: {exc}"
        finally:
            self.mcs_dv_client_secret = ""
            self.mcs_is_processing = False

    @rx.event
    def test_mcs_dataverse_connection(self):
        """Test Dataverse authentication and connectivity for transcript fetch."""
        environment = self.mcs_dv_environment.strip()
        dataverse_url = self.mcs_dv_dataverse_url.strip()
        if self.mcs_dv_actions_locked:
            self.mcs_upload_error = "Authenticate first in Manual Auth mode."
            self.mcs_dv_connection_ok = False
            self.mcs_dv_connection_message = "Connection blocked: authenticate first in Manual Auth mode."
            return
        if not environment and not dataverse_url:
            self.mcs_upload_error = "Provide either Environment ID/URL or Dataverse URL."
            self.mcs_dv_connection_ok = False
            self.mcs_dv_connection_message = "Connection failed: missing Environment ID/URL or Dataverse URL."
            return

        self.mcs_is_processing = True
        self.mcs_upload_error = ""
        self.mcs_dv_connection_ok = False
        self.mcs_dv_connection_message = ""
        yield

        auth: DataverseAuthConfig | None = None
        if self._mcs_dv_session_token:
            auth = DataverseAuthConfig(token=self._mcs_dv_session_token)
        elif not self.mcs_dv_use_env_auth:
            auth = DataverseAuthConfig(
                token=self.mcs_dv_token.strip() or None,
                tenant_id=self.mcs_dv_tenant_id.strip() or None,
                client_id=self.mcs_dv_client_id.strip() or None,
                client_secret=self.mcs_dv_client_secret.strip() or None,
            )

        try:
            info = check_dataverse_connection(
                environment=environment or dataverse_url,
                dataverse_url=dataverse_url or None,
                auth=auth,
            )
            self.mcs_dv_connection_ok = True
            self.mcs_dv_connection_message = (
                "Connected to Dataverse successfully. "
                f"Org: {info.get('organization_id', '-')}, User: {info.get('user_id', '-')}"
            )
        except RemoteFetchError as exc:
            self.mcs_dv_connection_ok = False
            self.mcs_dv_connection_message = f"Connection failed: {exc}"
        except Exception as exc:
            self.mcs_dv_connection_ok = False
            self.mcs_dv_connection_message = f"Connection test failed: {exc}"
        finally:
            self.mcs_dv_client_secret = ""
            self.mcs_is_processing = False

    @rx.event
    async def handle_mcs_upload(self, files: list[rx.UploadFile]):
        """Parse a transcript JSON and build a conversation analysis report."""
        if not files:
            return
        file = files[0]
        file_bytes = await file.read()
        filename = file.filename or ""

        if len(file_bytes) > _MAX_UPLOAD_BYTES:
            self.mcs_upload_error = f"File too large (max {_MAX_UPLOAD_BYTES // 1024 // 1024} MB)."
            return

        if not filename.lower().endswith(".json"):
            self.mcs_upload_error = "Please upload a .json transcript file."
            return

        self.mcs_is_processing = True
        self.mcs_upload_error = ""
        self.mcs_dv_connection_message = ""
        yield

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                json_path = tmp_path / "transcript.json"
                json_path.write_bytes(file_bytes)
                activities, metadata = mcs_parse_transcript(json_path)
                self._apply_transcript_analysis(
                    activities=activities,
                    metadata=metadata,
                    title=f"Transcript Analysis — {filename}",
                    conversation_label="Uploaded Transcript",
                    credits_label="Uploaded Transcript Credits",
                    upload_filename=filename,
                )

        except Exception as exc:
            self.mcs_upload_error = f"Analysis failed: {exc}\n{traceback.format_exc()}"
        finally:
            self.mcs_is_processing = False

    @rx.event
    def fetch_mcs_transcript_from_dataverse(self):
        """Fetch one transcript by Dataverse transcript ID and analyse it."""
        transcript_id = self.mcs_dv_transcript_id.strip()
        environment = self.mcs_dv_environment.strip()
        dataverse_url = self.mcs_dv_dataverse_url.strip()
        if self.mcs_dv_actions_locked:
            self.mcs_upload_error = "Authenticate first in Manual Auth mode."
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = "Fetch blocked: authenticate first in Manual Auth mode."
            return
        if not transcript_id:
            self.mcs_upload_error = "Please provide a transcript ID."
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = "Fetch failed: transcript ID is required."
            return
        if not environment and not dataverse_url:
            self.mcs_upload_error = "Provide either Environment ID/URL or Dataverse URL."
            self.mcs_dv_auth_ok = False
            self.mcs_dv_auth_message = "Fetch failed: missing Environment ID/URL or Dataverse URL."
            return

        self.mcs_is_processing = True
        self.mcs_upload_error = ""
        yield

        auth: DataverseAuthConfig | None = None
        if self._mcs_dv_session_token:
            auth = DataverseAuthConfig(token=self._mcs_dv_session_token)
        elif not self.mcs_dv_use_env_auth:
            auth = DataverseAuthConfig(
                token=self.mcs_dv_token.strip() or None,
                tenant_id=self.mcs_dv_tenant_id.strip() or None,
                client_id=self.mcs_dv_client_id.strip() or None,
                client_secret=self.mcs_dv_client_secret.strip() or None,
            )

        try:
            activities, metadata = fetch_transcript_by_id(
                environment=environment or dataverse_url,
                transcript_id=transcript_id,
                dataverse_url=dataverse_url or None,
                auth=auth,
            )
            self._apply_transcript_analysis(
                activities=activities,
                metadata=metadata,
                title=f"Dataverse Transcript Analysis — {transcript_id}",
                conversation_label=f"Dataverse Transcript {transcript_id}",
                credits_label=f"Dataverse Transcript {transcript_id} Credits",
                upload_filename=f"dataverse_{transcript_id}.json",
            )
            self.mcs_dv_last_source = str(metadata.get("transcript_source", "dataverse"))
            self.mcs_dv_last_table = str(metadata.get("transcript_table", ""))
            self.mcs_dv_last_transcript_id = str(metadata.get("transcript_id", transcript_id))
            self.mcs_dv_last_created_at = str(metadata.get("transcript_created_at", ""))
            self.mcs_dv_last_conversation_id = str(metadata.get("transcript_conversation_id", ""))
        except RemoteFetchError as exc:
            self.mcs_upload_error = (
                f"Dataverse transcript fetch failed: {exc}. You can still upload a transcript JSON file manually."
            )
        except Exception as exc:
            self.mcs_upload_error = f"Dataverse transcript analysis failed: {exc}\n{traceback.format_exc()}"
        finally:
            self.mcs_dv_client_secret = ""
            self.mcs_is_processing = False

    @rx.event
    def download_mcs_report(self):
        """Download the rendered Markdown report as a .md file."""
        if not self.mcs_report_markdown:
            return
        safe_title = (self.mcs_report_title or "report").replace(" ", "_").replace("/", "-")
        filename = f"{safe_title}.md"
        return rx.download(
            data=self.mcs_report_markdown.encode("utf-8"),
            filename=filename,
            mime_type="text/markdown",
        )

    @rx.event
    def clear_mcs_report(self):
        self.mcs_report_markdown = ""
        self.mcs_report_title = ""
        self.mcs_upload_error = ""
        self.mcs_is_processing = False
        self.mcs_api_comparison_running = False
        self.mcs_api_comparison_available = False
        self._mcs_zip_b64 = ""
        self.mcs_source = ""
        self.mcs_section_profile = ""
        self.mcs_section_knowledge_tools = ""
        self.mcs_section_topics = ""
        self.mcs_section_graph = ""
        self.mcs_section_conversation = ""
        self.mcs_section_model_comparison = ""
        self.mcs_section_model_comparison_live = ""
        self.mcs_section_credits = ""
        self.mcs_credit_rows = []
        self.mcs_credit_total = 0.0
        self.mcs_credit_assumptions = []
        self.mcs_conversation_flow = []
        self.mcs_conversation_flow_source = ""
        self.mcs_conv_kpis = []
        self.mcs_conv_event_mix = []
        self.mcs_conv_latency_bands = []
        self.mcs_conv_highlights = []
        self.mcs_analyse_tab = "profile"

    # ── Private helpers ───────────────────────────────────────────────────

    def _apply_transcript_analysis(
        self,
        *,
        activities: list[dict],
        metadata: dict,
        title: str,
        conversation_label: str,
        credits_label: str,
        upload_filename: str,
    ) -> None:
        timeline = mcs_build_timeline(activities, {})
        transcript_report = mcs_render_transcript_report(title, timeline, metadata)
        estimate = estimate_credits_from_activities(activities, None)
        credit_report = mcs_render_credit_estimate("Credit Prediction", estimate)
        self.mcs_credit_rows = [
            {
                "meter": "Classic answer",
                "count": estimate.classic_answers,
                "rate": "1",
                "credits": estimate.classic_credits,
            },
            {
                "meter": "Generative answer",
                "count": estimate.generative_answers,
                "rate": "2",
                "credits": estimate.generative_credits,
            },
            {
                "meter": "Agent action",
                "count": estimate.agent_actions,
                "rate": "5",
                "credits": estimate.agent_action_credits,
            },
            {
                "meter": "Tenant graph grounding (messages)",
                "count": estimate.tenant_graph_grounding_messages,
                "rate": "10",
                "credits": estimate.tenant_graph_credits,
            },
            {
                "meter": "Agent flow actions",
                "count": estimate.agent_flow_actions,
                "rate": "13 / 100",
                "credits": estimate.agent_flow_credits,
            },
            {
                "meter": "Text/gen AI tools (premium) responses",
                "count": estimate.premium_tool_responses,
                "rate": "100 / 10",
                "credits": estimate.premium_tool_credits,
            },
        ]
        self.mcs_credit_total = estimate.total_credits
        self.mcs_credit_assumptions = estimate.assumptions
        self.mcs_conversation_flow = mcs_build_conversation_flow_items(timeline)
        self.mcs_conversation_flow_source = "transcript"
        conv_summary = mcs_build_conversation_visual_summary(timeline)
        self.mcs_conv_kpis = conv_summary.get("kpis", [])
        self.mcs_conv_event_mix = conv_summary.get("event_mix", [])
        self.mcs_conv_latency_bands = conv_summary.get("latency_bands", [])
        self.mcs_conv_highlights = conv_summary.get("highlights", [])

        if self.mcs_source == "snapshot":
            existing = self.mcs_section_conversation.rstrip()
            self.mcs_section_conversation = existing + f"\n\n---\n\n## {conversation_label}\n\n" + transcript_report
            existing_credits = self.mcs_section_credits.rstrip()
            self.mcs_section_credits = existing_credits + f"\n\n---\n\n## {credits_label}\n\n" + credit_report
            self.mcs_report_markdown = self._compose_mcs_report_markdown()
            self.mcs_analyse_tab = "conversation"
            return

        self.mcs_section_profile = (
            "## Bot Profile\n\n_No snapshot loaded — drop a Copilot Studio snapshot ZIP for full agent analysis._\n"
        )
        self.mcs_section_knowledge_tools = (
            "## Knowledge Sources & External Tools\n\n"
            "_No snapshot loaded — drop a Copilot Studio snapshot ZIP for knowledge and connector inventory._\n"
        )
        self.mcs_section_topics = "## Topics & Components\n\n_No snapshot loaded._\n"
        self.mcs_section_graph = "## Topic Redirect Graph\n\n_No snapshot loaded._\n"
        self.mcs_section_model_comparison_live = ""
        self.mcs_section_conversation = transcript_report
        self.mcs_section_credits = credit_report
        self.mcs_report_title = title
        self.mcs_source = "transcript"
        self.mcs_report_markdown = self._compose_mcs_report_markdown()
        self.mcs_analyse_tab = "conversation"
        self.upload_filename = upload_filename
        self.active_tab = "analyse"

    def _update_derived_schema(self):
        if self.detected_bot_schema and self.new_agent_name.strip():
            self.derived_schema = derive_schema_name(self.detected_bot_schema, self.new_agent_name.strip())
        else:
            self.derived_schema = ""

    def _compose_mcs_report_markdown(self) -> str:
        """Build one consolidated report body from currently available MCS sections."""
        return "\n\n".join(
            section
            for section in [
                self.mcs_section_profile,
                self.mcs_section_knowledge_tools,
                self.mcs_section_topics,
                self.mcs_section_graph,
                self.mcs_section_model_comparison,
                self.mcs_section_model_comparison_live,
                self.mcs_section_conversation,
                self.mcs_section_credits,
            ]
            if section.strip()
        )

    def _update_derived_solution_unique(self):
        if self.new_solution_display_name.strip():
            self.derived_solution_unique = derive_solution_unique_name(self.new_solution_display_name.strip())
        else:
            self.derived_solution_unique = ""
