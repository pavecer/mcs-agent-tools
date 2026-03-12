"""Reflex state for the Power Platform Agent Renamer web UI."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import tempfile
import traceback
import zipfile
from pathlib import Path

import reflex as rx
from dotenv import load_dotenv

from mcs_credits import estimate_credits_from_activities
from mcs_models import MCSConversationTimeline as _MCSTl
from mcs_parser import parse_dialog_json as mcs_parse_dialog_json
from mcs_parser import parse_yaml as mcs_parse_yaml
from mcs_renderer import render_credit_estimate as mcs_render_credit_estimate
from mcs_renderer import build_conversation_flow_items as mcs_build_conversation_flow_items
from mcs_renderer import build_conversation_visual_summary as mcs_build_conversation_visual_summary
from mcs_renderer import render_report_sections as mcs_render_report_sections
from mcs_renderer import render_transcript_report as mcs_render_transcript_report
from mcs_renderer import to_viz_segments as mcs_to_viz_segments
from mcs_timeline import build_timeline as mcs_build_timeline
from mcs_transcript import parse_transcript_json as mcs_parse_transcript
from renamer import (
    derive_schema_name,
    derive_solution_unique_name,
    inspect_zip,
    rename_solution_from_bytes,
    safe_extractall,
)
from deps_analyzer import analyze_deps_zip_bytes
from solution_checker import check_solution_zip
from validator import validate_instructions, validate_zip_bytes
from visualizer import visualize_zip_bytes, get_evals_data

load_dotenv()

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB — maximum accepted upload size


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
    viz_segments: list[dict] = []

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

    # ── Dependencies ──────────────────────────────────────────────────────
    deps_is_analyzing: bool = False
    deps_error: str = ""
    deps_ran: bool = False
    deps_segments: list[dict] = []

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

    # ── Authentication ────────────────────────────────────────────────────
    username: str = ""
    password: str = ""
    is_authenticated: bool = False
    auth_error: str = ""

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
    mcs_section_topics: str = ""
    mcs_section_graph: str = ""
    mcs_section_conversation: str = ""
    mcs_section_credits: str = ""
    mcs_credit_rows: list[dict] = []
    mcs_credit_total: float = 0.0
    mcs_credit_assumptions: list[str] = []
    mcs_conversation_flow: list[dict] = []
    mcs_conversation_flow_source: str = ""  # "snapshot" | "transcript" | ""
    mcs_conv_kpis: list[dict] = []
    mcs_conv_event_mix: list[dict] = []
    mcs_conv_latency_bands: list[dict] = []
    mcs_conv_highlights: list[dict] = []

    # ── Computed / derived ────────────────────────────────────────────────

    @rx.var
    def has_upload(self) -> bool:
        return bool(self.zip_bytes_b64) or self.mcs_source == "transcript"

    @rx.var
    def has_detection(self) -> bool:
        return bool(self.detected_bot_schema)

    @rx.var
    def has_visualization(self) -> bool:
        return len(self.viz_segments) > 0

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
    def mcs_report_segments(self) -> list[dict]:
        """Full report segments (used for backward-compat / transcript flat view)."""
        return _md_to_segments(self.mcs_report_markdown)

    @rx.var
    def mcs_current_section_segments(self) -> list[dict]:
        """Segments for the currently active MCS analyse sub-tab."""
        section_map = {
            "profile": self.mcs_section_profile,
            "topics": self.mcs_section_topics,
            "graph": self.mcs_section_graph,
            "conversation": self.mcs_section_conversation,
            "credits": self.mcs_section_credits,
        }
        md = section_map.get(self.mcs_analyse_tab, "")
        return _md_to_segments(md)

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
        self.deps_is_analyzing = False
        self.deps_error = ""
        self.deps_ran = False
        self.deps_segments = []
        self.mcs_section_profile = ""
        self.mcs_section_topics = ""
        self.mcs_section_graph = ""
        self.mcs_section_conversation = ""
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
                        self.viz_segments = visualize_zip_bytes(file_bytes)
                        self.viz_error = ""
                    except Exception as viz_exc:
                        self.viz_error = str(viz_exc)
                        self.viz_segments = []
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
            else:
                # Generic solution ZIP (no Copilot agent assets): run dependencies only.
                self.is_inspecting = False
                self.detected_solution_display = file.filename

            self.deps_is_analyzing = True
            yield
            try:
                self.deps_segments = analyze_deps_zip_bytes(file_bytes)
                self.deps_ran = True
                self.deps_error = ""
            except Exception as dep_exc:
                self.deps_error = str(dep_exc)
                self.deps_segments = []
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
                    self.mcs_section_topics = sections["topics"]
                    self.mcs_section_graph = sections["graph"]
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
                    self.mcs_report_markdown = "\n\n".join(
                        v
                        for v in [
                            self.mcs_section_profile,
                            self.mcs_section_topics,
                            self.mcs_section_graph,
                            self.mcs_section_conversation,
                            self.mcs_section_credits,
                        ]
                        if v.strip()
                    )
                    self.mcs_upload_error = ""
                except Exception as e:
                    self.mcs_upload_error = f"Snapshot analysis failed: {e}"
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
        self.no_agent_warning = ""
        self.active_tab = "visualize"
        self.zip_type = ""
        self.solution_has_agent_assets = False
        self.deps_is_analyzing = False
        self.deps_error = ""
        self.deps_ran = False
        self.deps_segments = []
        self.mcs_source = ""
        self.mcs_section_profile = ""
        self.mcs_section_topics = ""
        self.mcs_section_graph = ""
        self.mcs_section_conversation = ""
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

    # ── Authentication handlers ───────────────────────────────────────────

    @rx.event
    def set_username(self, value: str):
        self.username = value

    @rx.event
    def set_password(self, value: str):
        self.password = value

    @rx.event
    def login(self):
        """Validate credentials against USERS env var and set authenticated."""
        users = _load_users()
        if not users:
            self.auth_error = "No users configured. Set the USERS environment variable."
            return
        pw_hash = hashlib.pbkdf2_hmac("sha256", self.password.encode(), self.username.encode(), 100_000).hex()
        if users.get(self.username) == pw_hash:
            self.is_authenticated = True
            self.auth_error = ""
            self.password = ""  # clear password from state
            return rx.redirect("/")
        self.auth_error = "Invalid username or password."

    @rx.event
    def logout(self):
        self.is_authenticated = False
        self.username = ""
        self.password = ""
        return rx.redirect("/login")

    @rx.event
    def check_auth(self):
        """Redirect to /login if USERS is configured and user is not authenticated."""
        if os.getenv("USERS", "").strip() and not self.is_authenticated:
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
        yield

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                json_path = tmp_path / "transcript.json"
                json_path.write_bytes(file_bytes)
                activities, metadata = mcs_parse_transcript(json_path)
                timeline = mcs_build_timeline(activities, {})
                title = f"Transcript Analysis — {filename}"
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
                    # Append transcript to the existing snapshot conversation section
                    existing = self.mcs_section_conversation.rstrip()
                    self.mcs_section_conversation = (
                        existing + "\n\n---\n\n## Uploaded Transcript\n\n" + transcript_report
                    )
                    existing_credits = self.mcs_section_credits.rstrip()
                    self.mcs_section_credits = (
                        existing_credits + "\n\n---\n\n## Uploaded Transcript Credits\n\n" + credit_report
                    )
                    self.mcs_report_markdown = "\n\n".join(
                        s
                        for s in [
                            self.mcs_section_profile,
                            self.mcs_section_topics,
                            self.mcs_section_graph,
                            self.mcs_section_conversation,
                            self.mcs_section_credits,
                        ]
                        if s.strip()
                    )
                    self.mcs_analyse_tab = "conversation"
                else:
                    # No snapshot: populate sections with placeholders + transcript conv
                    self.mcs_section_profile = (
                        "## Bot Profile\n\n"
                        "_No snapshot loaded — drop a Copilot Studio snapshot ZIP for full agent analysis._\n"
                    )
                    self.mcs_section_topics = "## Topics & Components\n\n_No snapshot loaded._\n"
                    self.mcs_section_graph = "## Topic Redirect Graph\n\n_No snapshot loaded._\n"
                    self.mcs_section_conversation = transcript_report
                    self.mcs_section_credits = credit_report
                    self.mcs_report_title = title
                    self.mcs_source = "transcript"
                    self.mcs_report_markdown = "\n\n".join(
                        s
                        for s in [
                            self.mcs_section_profile,
                            self.mcs_section_topics,
                            self.mcs_section_graph,
                            self.mcs_section_credits,
                            self.mcs_section_conversation,
                        ]
                        if s.strip()
                    )
                    self.mcs_analyse_tab = "conversation"
                    self.upload_filename = filename
                    self.active_tab = "analyse"

        except Exception as exc:
            self.mcs_upload_error = f"Analysis failed: {exc}\n{traceback.format_exc()}"
        finally:
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
        self.mcs_source = ""
        self.mcs_section_profile = ""
        self.mcs_section_topics = ""
        self.mcs_section_graph = ""
        self.mcs_section_conversation = ""
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

    def _update_derived_schema(self):
        if self.detected_bot_schema and self.new_agent_name.strip():
            self.derived_schema = derive_schema_name(self.detected_bot_schema, self.new_agent_name.strip())
        else:
            self.derived_schema = ""

    def _update_derived_solution_unique(self):
        if self.new_solution_display_name.strip():
            self.derived_solution_unique = derive_solution_unique_name(self.new_solution_display_name.strip())
        else:
            self.derived_solution_unique = ""
