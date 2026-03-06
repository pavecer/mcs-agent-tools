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

from mcs_models import MCSConversationTimeline as _MCSTl
from mcs_parser import parse_dialog_json as mcs_parse_dialog_json
from mcs_parser import parse_yaml as mcs_parse_yaml
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
from validator import validate_instructions, validate_zip_bytes
from visualizer import visualize_zip_bytes

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

    # ── Active tab ("rename" | "visualize" | "validate") ─────────────────────
    active_tab: str = "rename"

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

    # ── Computed / derived ────────────────────────────────────────────────

    @rx.var
    def has_upload(self) -> bool:
        return bool(self.zip_bytes_b64)

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
    def is_snapshot_zip(self) -> bool:
        return self.zip_type == "snapshot"

    @rx.var
    def has_mcs_report(self) -> bool:
        return bool(self.mcs_source)

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
        }
        md = section_map.get(self.mcs_analyse_tab, "")
        return _md_to_segments(md)

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

        if not _has_solution and not _has_snapshot:
            self.inspect_error = (
                "Unrecognised ZIP format — expected a Power Platform solution export "
                "(containing bots/) or a Copilot Studio snapshot ZIP (containing botContent.yml)."
            )
            return

        # ── Reset all upload-derived state ────────────────────────────────
        self.zip_type = "solution" if _has_solution else "snapshot"
        self.active_tab = "rename" if _has_solution else "analyse"
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
        self.mcs_section_profile = ""
        self.mcs_section_topics = ""
        self.mcs_section_graph = ""
        self.mcs_section_conversation = ""
        self.mcs_report_markdown = ""
        self.mcs_report_title = ""
        self.mcs_upload_error = ""
        self.mcs_source = ""
        self.detected_bot_schema = ""
        self.detected_bot_name = ""
        self.detected_solution_name = ""
        self.detected_solution_display = ""
        self.detected_component_count = 0
        yield

        if _has_solution:
            # ── Solution ZIP: inspect → visualize → validate ──────────────
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
                    self.mcs_source = "snapshot"
                    self.mcs_report_markdown = "\n\n".join(v for v in sections.values() if v.strip())
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
        self.no_agent_warning = ""
        self.active_tab = "rename"
        self.zip_type = ""
        self.mcs_source = ""
        self.mcs_section_profile = ""
        self.mcs_section_topics = ""
        self.mcs_section_graph = ""
        self.mcs_section_conversation = ""
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

                if self.mcs_source == "snapshot":
                    # Append transcript to the existing snapshot conversation section
                    existing = self.mcs_section_conversation.rstrip()
                    self.mcs_section_conversation = (
                        existing + "\n\n---\n\n## Uploaded Transcript\n\n" + transcript_report
                    )
                    self.mcs_report_markdown = "\n\n".join(
                        s
                        for s in [
                            self.mcs_section_profile,
                            self.mcs_section_topics,
                            self.mcs_section_graph,
                            self.mcs_section_conversation,
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
                    self.mcs_report_title = title
                    self.mcs_source = "transcript"
                    self.mcs_report_markdown = transcript_report
                    self.mcs_analyse_tab = "conversation"

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
