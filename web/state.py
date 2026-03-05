"""Reflex state for the Power Platform Agent Renamer web UI."""

from __future__ import annotations

import base64
import os
import tempfile
import traceback
import zipfile
from pathlib import Path

import reflex as rx

from renamer import derive_schema_name, derive_solution_unique_name, inspect_zip, rename_solution_from_bytes
from validator import validate_zip_bytes
from visualizer import visualize_zip_bytes


class State(rx.State):
    """Application state."""

    # ── Upload & detection ────────────────────────────────────────────────
    upload_filename: str = ""
    zip_bytes_b64: str = ""          # base64-encoded uploaded ZIP bytes
    is_inspecting: bool = False
    inspect_error: str = ""
    no_agent_warning: str = ""       # set when the uploaded ZIP has no Copilot Studio agent

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
    def can_process(self) -> bool:
        return (
            self.has_detection
            and bool(self.new_agent_name.strip())
            and bool(self.new_solution_display_name.strip())
            and bool(self.derived_solution_unique)
        )

    # ── Event handlers ────────────────────────────────────────────────────

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        """Receive and inspect the uploaded ZIP."""
        if not files:
            return

        file = files[0]
        file_bytes = await file.read()

        if not file.filename.lower().endswith(".zip"):
            self.inspect_error = "Please upload a .zip file exported from Power Platform."
            return

        self.is_inspecting = True
        self.inspect_error = ""
        self.no_agent_warning = ""
        self.process_success = False
        self.process_error = ""
        self.result_filename = ""
        self._output_zip_b64 = ""
        yield  # flush state to UI

        # Write to temp so inspect_zip can use it
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            tf.write(file_bytes)
            tmp_path = Path(tf.name)

        # Pre-check: ensure the ZIP is valid and contains a Copilot Studio agent
        try:
            with zipfile.ZipFile(tmp_path) as _zf:
                _has_agent = any(
                    n == "bots" or n.startswith("bots/")
                    for n in _zf.namelist()
                )
        except zipfile.BadZipFile:
            self.inspect_error = "The uploaded file is not a valid ZIP archive."
            os.unlink(tmp_path)
            self.is_inspecting = False
            return

        if not _has_agent:
            self.no_agent_warning = (
                "This solution does not contain a Copilot Studio agent (bot) definition. "
                "Rename, Visualise and Validate operations require an agent to be included in the solution export."
            )
            os.unlink(tmp_path)
            self.is_inspecting = False
            return

        try:
            info = inspect_zip(tmp_path)
            self.zip_bytes_b64 = base64.b64encode(file_bytes).decode()
            self.upload_filename = file.filename
            self.detected_bot_schema = info.bot_schema_name
            self.detected_bot_name = info.bot_display_name
            self.detected_solution_name = info.solution_unique_name
            self.detected_solution_display = info.solution_display_name
            self.detected_component_count = len(info.botcomponent_folders)

            # Pre-fill suggestion fields if empty
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

        # ── Visualization (runs only when inspection succeeded) ───────────
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

        # ── Validation (runs only when inspection succeeded) ─────────────
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
        # Delete output ZIP if it was written to the upload directory
        if self.result_filename:
            output_file = Path(rx.get_upload_dir()) / self.result_filename
            output_file.unlink(missing_ok=True)
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

    @rx.event
    def set_active_tab(self, tab: str):
        self.active_tab = tab

    @rx.event
    def toggle_best_practices(self):
        self.show_best_practices = not self.show_best_practices

    # ── Private helpers ───────────────────────────────────────────────────

    def _update_derived_schema(self):
        if self.detected_bot_schema and self.new_agent_name.strip():
            self.derived_schema = derive_schema_name(
                self.detected_bot_schema, self.new_agent_name.strip()
            )
        else:
            self.derived_schema = ""

    def _update_derived_solution_unique(self):
        if self.new_solution_display_name.strip():
            self.derived_solution_unique = derive_solution_unique_name(
                self.new_solution_display_name.strip()
            )
        else:
            self.derived_solution_unique = ""
