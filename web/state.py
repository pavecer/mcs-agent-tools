"""Reflex state for the Power Platform Agent Renamer web UI."""

from __future__ import annotations

import base64
import traceback
from pathlib import Path

import reflex as rx

from renamer import derive_schema_name, inspect_zip, rename_solution_from_bytes


class State(rx.State):
    """Application state."""

    # ── Upload & detection ────────────────────────────────────────────────
    upload_filename: str = ""
    zip_bytes_b64: str = ""          # base64-encoded uploaded ZIP bytes
    is_inspecting: bool = False
    inspect_error: str = ""

    detected_bot_schema: str = ""
    detected_bot_name: str = ""
    detected_solution_name: str = ""
    detected_solution_display: str = ""
    detected_component_count: int = 0

    # ── User inputs ───────────────────────────────────────────────────────
    new_agent_name: str = ""
    new_solution_name: str = ""
    # derived schema preview (read-only, updated as user types)
    derived_schema: str = ""

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
    result_zip_b64: str = ""  # base64-encoded output ZIP

    # ── Computed / derived ────────────────────────────────────────────────

    @rx.var
    def has_upload(self) -> bool:
        return bool(self.zip_bytes_b64)

    @rx.var
    def has_detection(self) -> bool:
        return bool(self.detected_bot_schema)

    @rx.var
    def can_process(self) -> bool:
        return (
            self.has_detection
            and bool(self.new_agent_name.strip())
            and bool(self.new_solution_name.strip())
        )

    @rx.var
    def solution_name_valid(self) -> bool:
        import re
        return bool(re.match(r'^[A-Za-z][A-Za-z0-9_]{0,99}$', self.new_solution_name))

    @rx.var
    def solution_name_error(self) -> str:
        if not self.new_solution_name:
            return ""
        if not self.solution_name_valid:
            return "Must start with a letter; only letters, digits, underscores allowed."
        return ""

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
        self.process_success = False
        self.process_error = ""
        self.result_zip_b64 = ""
        yield  # flush state to UI

        try:
            with rx.get_upload_dir() as udir:
                tmp_zip = Path(str(udir)) / "uploaded.zip"
        except Exception:
            # Fallback: keep in memory only
            tmp_zip = None

            # Write to temp so inspect_zip can use it
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            tf.write(file_bytes)
            tmp_path = Path(tf.name)

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
            if not self.new_solution_name:
                self.new_solution_name = info.solution_unique_name + "Copy"

            self._update_derived_schema()
        except Exception as exc:
            self.inspect_error = f"Could not inspect ZIP: {exc}"
        finally:
            os.unlink(tmp_path)
            self.is_inspecting = False

    @rx.event
    def set_new_agent_name(self, value: str):
        self.new_agent_name = value
        self._update_derived_schema()

    @rx.event
    def set_new_solution_name(self, value: str):
        self.new_solution_name = value

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
                new_solution_name=self.new_solution_name.strip(),
            )
            self.result_old_schema = result.old_bot_schema
            self.result_new_schema = result.new_bot_schema
            self.result_old_solution = result.old_solution_name
            self.result_new_solution = result.new_solution_name
            self.result_files_modified = result.files_modified
            self.result_folders_renamed = result.folders_renamed
            self.result_warnings = result.warnings
            self.result_filename = f"{self.new_solution_name}.zip"
            self.result_zip_b64 = base64.b64encode(output_bytes).decode()
            self.process_success = True
        except Exception as exc:
            self.process_error = f"Rename failed: {exc}\n{traceback.format_exc()}"
        finally:
            self.is_processing = False

    @rx.event
    def download_result(self):
        """Trigger download of the renamed ZIP."""
        if not self.result_zip_b64:
            return
        return rx.download(
            data=base64.b64decode(self.result_zip_b64),
            filename=self.result_filename,
        )

    @rx.event
    def reset(self):
        """Clear all state to start over."""
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
        self.new_solution_name = ""
        self.derived_schema = ""
        self.is_processing = False
        self.process_error = ""
        self.process_success = False
        self.result_zip_b64 = ""

    # ── Private helpers ───────────────────────────────────────────────────

    def _update_derived_schema(self):
        if self.detected_bot_schema and self.new_agent_name.strip():
            self.derived_schema = derive_schema_name(
                self.detected_bot_schema, self.new_agent_name.strip()
            )
        else:
            self.derived_schema = ""
