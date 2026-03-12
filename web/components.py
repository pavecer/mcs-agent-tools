"""Reusable UI components for the Agent Renamer web app."""

from __future__ import annotations

import reflex as rx

from app_meta import FEATURE_URL, ISSUE_URL, LICENSE_NAME, OPEN_ISSUE_URL, get_app_version
from web.mermaid import render_segment
from web.state import State


# ── Colour palette ────────────────────────────────────────────────────────────
PRIMARY = "#0a66ff"  # bright azure blue
PRIMARY_DARK = "#0049c7"
PRIMARY_SOFT = "#e8f0ff"
SUCCESS = "#107c10"  # Microsoft green
WARNING = "#797673"  # muted amber label
WARNING_AMBER = "#c7921e"  # amber for validation badges
ERROR_COLOR = "#a4262c"  # Microsoft red
BG = "#eef3fb"
CARD_BG = "#ffffff"
SURFACE_BORDER = "#d7e2f2"
CARD_SHADOW = "0 16px 40px rgba(12, 33, 70, 0.10)"


# ── Building blocks ───────────────────────────────────────────────────────────


def card(*children, **props) -> rx.Component:
    """Glass-like card surface used throughout the app."""
    card_props = {
        "background_color": CARD_BG,
        "border": f"1px solid {SURFACE_BORDER}",
        "border_radius": "16px",
        "box_shadow": CARD_SHADOW,
        "padding": "24px",
        "transition": "transform 180ms ease, box-shadow 180ms ease",
        "_hover": {
            "transform": "translateY(-1px)",
            "box_shadow": "0 20px 44px rgba(12, 33, 70, 0.14)",
        },
    }
    card_props.update(props)
    return rx.box(
        *children,
        **card_props,
    )


def section_heading(text: str) -> rx.Component:
    return rx.heading(text, size="4", margin_bottom="12px", color="#102548", letter_spacing="-0.01em")


def label(text: str) -> rx.Component:
    return rx.text(text, font_size="12px", font_weight="700", color="#334a6d", margin_bottom="6px")


def info_row(field: str, value: rx.Component | str) -> rx.Component:
    return rx.flex(
        rx.text(field, font_size="13px", color="#605e5c", width="220px", flex_shrink="0"),
        rx.text(value, font_size="13px", font_weight="600", color="#201f1e") if isinstance(value, str) else value,
        direction="row",
        align="center",
        gap="8px",
        padding_y="4px",
    )


def sub_heading(text: str) -> rx.Component:
    """Small uppercase section label used inside cards."""
    return rx.text(
        text,
        font_size="10px",
        font_weight="700",
        color=PRIMARY_DARK,
        letter_spacing="0.08em",
        margin_bottom="6px",
    )


# ── Upload area ───────────────────────────────────────────────────────────────


def upload_area() -> rx.Component:
    return rx.upload(
        rx.vstack(
            rx.icon("cloud-upload", color=PRIMARY, size=40),
            rx.text(
                "Drag & drop your solution ZIP here",
                font_size="15px",
                font_weight="600",
                color="#201f1e",
            ),
            rx.text(
                "or click to browse",
                font_size="13px",
                color="#605e5c",
            ),
            spacing="2",
            align="center",
        ),
        id="solution_upload",
        accept={"application/zip": [".zip"], "application/x-zip-compressed": [".zip"]},
        multiple=False,
        border=f"2px dashed {PRIMARY}",
        border_radius="14px",
        background="#f8fbff",
        padding="44px",
        cursor="pointer",
        width="100%",
        transition="all 180ms ease",
        on_drop=State.handle_upload(rx.upload_files(upload_id="solution_upload")),
        _hover={
            "background_color": "#eef4ff",
            "border": f"2px solid {PRIMARY_DARK}",
            "transform": "translateY(-1px)",
        },
    )


def unified_upload_area() -> rx.Component:
    """Drop zone that accepts both solution ZIPs and snapshot ZIPs."""
    return rx.upload(
        rx.vstack(
            rx.icon("cloud-upload", color=PRIMARY, size=40),
            rx.text(
                "Drag & drop a solution ZIP or snapshot ZIP",
                font_size="15px",
                font_weight="600",
                color="#201f1e",
            ),
            rx.text(
                "Any solution ZIP — dependencies  ·  Agent solution ZIP — rename/visualize/validate  ·  Snapshot ZIP — deep agent analysis",
                font_size="12px",
                color="#605e5c",
            ),
            rx.text("or click to browse", font_size="13px", color="#605e5c"),
            spacing="2",
            align="center",
        ),
        id="solution_upload",
        accept={"application/zip": [".zip"], "application/x-zip-compressed": [".zip"]},
        multiple=False,
        border=f"2px dashed {PRIMARY}",
        border_radius="14px",
        background="#f8fbff",
        padding="44px",
        cursor="pointer",
        width="100%",
        transition="all 180ms ease",
        on_drop=State.handle_upload(rx.upload_files(upload_id="solution_upload")),
        _hover={
            "background_color": "#eef4ff",
            "border": f"2px solid {PRIMARY_DARK}",
            "transform": "translateY(-1px)",
        },
    )


def json_upload_area() -> rx.Component:
    """Drop zone for conversation transcript JSON on the landing page."""
    return rx.vstack(
        rx.upload(
            rx.vstack(
                rx.icon("file-json", color=PRIMARY, size=40),
                rx.text(
                    "Drag & drop a conversation transcript JSON",
                    font_size="15px",
                    font_weight="600",
                    color="#201f1e",
                ),
                rx.text(
                    "Copilot Studio session transcript — conversation analysis",
                    font_size="12px",
                    color="#605e5c",
                ),
                rx.text("or click to browse", font_size="13px", color="#605e5c"),
                spacing="2",
                align="center",
            ),
            id="mcs_landing_upload",
            accept={".json": ["application/json"]},
            multiple=False,
            border=f"2px dashed {PRIMARY}",
            border_radius="14px",
            background="#f8fbff",
            padding="44px",
            cursor="pointer",
            width="100%",
            transition="all 180ms ease",
            on_drop=State.handle_mcs_upload(rx.upload_files(upload_id="mcs_landing_upload")),  # type: ignore[arg-type]
            _hover={
                "background_color": "#eef4ff",
                "border": f"2px solid {PRIMARY_DARK}",
                "transform": "translateY(-1px)",
            },
        ),
        rx.cond(
            State.mcs_upload_error != "",
            rx.callout(
                State.mcs_upload_error,
                icon="triangle-alert",
                color_scheme="red",
                margin_top="8px",
            ),
            rx.box(),
        ),
        spacing="3",
        width="100%",
        align="start",
    )


def _mcs_dataverse_fetch_block() -> rx.Component:
    """Shared Dataverse transcript fetch UI block."""
    return rx.vstack(
        sub_heading("FETCH FROM DATAVERSE"),
        rx.text(
            "Alternative to JSON upload: authenticate and fetch a transcript directly by transcript ID.",
            font_size="12px",
            color="#605e5c",
        ),
        rx.text(
            "Tip: environment IDs such as Default-... are best-effort resolved; Dataverse URL is always reliable.",
            font_size="11px",
            color="#605e5c",
        ),
        rx.text("Environment ID or URL", font_size="11px", font_weight="600", color="#334a6d"),
        rx.hstack(
            rx.input(
                placeholder="e.g. Default-1234... or https://org.crm.dynamics.com",
                value=State.mcs_dv_environment,
                on_change=State.set_mcs_dv_environment,
                size="2",
                width="50%",
            ),
            rx.input(
                placeholder="Dataverse URL override (optional)",
                value=State.mcs_dv_dataverse_url,
                on_change=State.set_mcs_dv_dataverse_url,
                size="2",
                width="50%",
            ),
            spacing="2",
            width="100%",
            flex_wrap="wrap",
        ),
        rx.text("Transcript ID", font_size="11px", font_weight="600", color="#334a6d"),
        rx.input(
            placeholder="Transcript ID",
            value=State.mcs_dv_transcript_id,
            on_change=State.set_mcs_dv_transcript_id,
            size="2",
            width="100%",
        ),
        rx.text("Authentication mode", font_size="11px", font_weight="600", color="#334a6d"),
        rx.hstack(
            rx.button(
                "Use Env Auth",
                on_click=State.set_mcs_dv_use_env_auth(True),
                size="1",
                variant=rx.cond(State.mcs_dv_use_env_auth, "solid", "outline"),
                color_scheme=rx.cond(State.mcs_dv_use_env_auth, "blue", "gray"),
                cursor="pointer",
            ),
            rx.button(
                "Manual Auth",
                on_click=State.set_mcs_dv_use_env_auth(False),
                size="1",
                variant=rx.cond(State.mcs_dv_use_env_auth, "outline", "solid"),
                color_scheme=rx.cond(State.mcs_dv_use_env_auth, "gray", "blue"),
                cursor="pointer",
            ),
            spacing="2",
            width="100%",
        ),
        rx.text(
            rx.cond(State.mcs_dv_use_env_auth, "Current mode: Environment credentials", "Current mode: Manual credentials"),
            font_size="11px",
            color="#605e5c",
        ),
        rx.cond(
            State.mcs_dv_use_env_auth,
            rx.callout(
                "Using environment credentials. If none are configured, the app will automatically switch to Manual Auth.",
                icon="shield-check",
                color_scheme="blue",
            ),
            rx.vstack(
                rx.text("OAuth Device Code (recommended)", font_size="11px", font_weight="700", color="#334a6d"),
                rx.hstack(
                    rx.input(
                        placeholder="Tenant ID",
                        value=State.mcs_dv_oauth_tenant_id,
                        on_change=State.set_mcs_dv_oauth_tenant_id,
                        size="2",
                        width="50%",
                    ),
                    rx.input(
                        placeholder="Client ID (public app)",
                        value=State.mcs_dv_oauth_client_id,
                        on_change=State.set_mcs_dv_oauth_client_id,
                        size="2",
                        width="50%",
                    ),
                    spacing="2",
                    width="100%",
                    flex_wrap="wrap",
                ),
                rx.hstack(
                    rx.button(
                        "Use Default Public Client ID",
                        on_click=State.use_mcs_dv_default_oauth_client_id,
                        size="1",
                        variant="ghost",
                        color_scheme="blue",
                        cursor="pointer",
                    ),
                    rx.text(
                        "Convenience preset; tenant policy may require your own app registration.",
                        font_size="11px",
                        color="#605e5c",
                    ),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                    width="100%",
                ),
                rx.hstack(
                    rx.button(
                        "Start Device Login",
                        on_click=State.start_mcs_dataverse_device_login,
                        size="1",
                        variant="outline",
                        color_scheme="blue",
                        is_disabled=State.mcs_is_processing,
                        _disabled={"opacity": "0.5", "cursor": "not-allowed"},
                    ),
                    rx.button(
                        "Complete Device Login",
                        on_click=State.complete_mcs_dataverse_device_login,
                        size="1",
                        variant="outline",
                        color_scheme="blue",
                        is_disabled=State.mcs_is_processing | (State.mcs_dv_oauth_device_code == ""),
                        _disabled={"opacity": "0.5", "cursor": "not-allowed"},
                    ),
                    spacing="2",
                    flex_wrap="wrap",
                ),
                rx.cond(
                    State.mcs_dv_oauth_user_code != "",
                    rx.box(
                        rx.text("User code", font_size="11px", font_weight="700", color="#334a6d"),
                        rx.code(State.mcs_dv_oauth_user_code),
                        rx.cond(
                            State.mcs_dv_oauth_verify_uri != "",
                            rx.link(
                                "Open verification URL",
                                href=State.mcs_dv_oauth_verify_uri,
                                is_external=True,
                                color=PRIMARY,
                                font_size="12px",
                            ),
                            rx.box(),
                        ),
                        width="100%",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    State.mcs_dv_oauth_message != "",
                    rx.callout(
                        State.mcs_dv_oauth_message,
                        icon="info",
                        color_scheme="blue",
                    ),
                    rx.box(),
                ),
                rx.divider(),
                rx.text("Manual token / app credentials", font_size="11px", font_weight="700", color="#334a6d"),
                rx.input(
                    placeholder="Bearer token (optional if using app credentials below)",
                    value=State.mcs_dv_token,
                    on_change=State.set_mcs_dv_token,
                    size="2",
                    width="100%",
                ),
                rx.hstack(
                    rx.input(
                        placeholder="Tenant ID",
                        value=State.mcs_dv_tenant_id,
                        on_change=State.set_mcs_dv_tenant_id,
                        size="2",
                        width="33%",
                    ),
                    rx.input(
                        placeholder="Client ID",
                        value=State.mcs_dv_client_id,
                        on_change=State.set_mcs_dv_client_id,
                        size="2",
                        width="33%",
                    ),
                    rx.input(
                        placeholder="Client Secret",
                        value=State.mcs_dv_client_secret,
                        on_change=State.set_mcs_dv_client_secret,
                        size="2",
                        type="password",
                        width="33%",
                    ),
                    spacing="2",
                    width="100%",
                    flex_wrap="wrap",
                ),
                rx.text(
                    "Secrets are only used for this request and client secret is cleared after fetch.",
                    font_size="11px",
                    color="#605e5c",
                ),
                spacing="2",
                width="100%",
                align="start",
            ),
        ),
        rx.button(
            rx.hstack(
                rx.icon("key-round", size=14),
                rx.text("Authenticate", font_size="13px"),
                spacing="2",
                align="center",
            ),
            on_click=State.authenticate_mcs_dataverse,
            is_disabled=State.mcs_is_processing,
            size="2",
            variant="outline",
            color_scheme="blue",
            cursor="pointer",
            _disabled={"opacity": "0.5", "cursor": "not-allowed"},
            width="100%",
        ),
        rx.button(
            rx.hstack(
                rx.icon("database", size=14),
                rx.text("Fetch Transcript by ID", font_size="13px"),
                spacing="2",
                align="center",
            ),
            on_click=State.fetch_mcs_transcript_from_dataverse,
            is_disabled=State.mcs_dv_actions_locked | State.mcs_is_processing,
            size="2",
            color_scheme="blue",
            cursor="pointer",
            _disabled={"opacity": "0.5", "cursor": "not-allowed"},
            width="100%",
        ),
        rx.button(
            rx.hstack(
                rx.icon("shield-check", size=14),
                rx.text("Test Connection", font_size="13px"),
                spacing="2",
                align="center",
            ),
            on_click=State.test_mcs_dataverse_connection,
            is_disabled=State.mcs_dv_actions_locked | State.mcs_is_processing,
            size="2",
            variant="outline",
            color_scheme="blue",
            cursor="pointer",
            _disabled={"opacity": "0.5", "cursor": "not-allowed"},
            width="100%",
        ),
        rx.cond(
            State.mcs_is_processing,
            rx.hstack(
                rx.spinner(size="2", color=PRIMARY),
                rx.text("Working on Dataverse request...", font_size="12px", color="#605e5c"),
                spacing="2",
                align="center",
            ),
            rx.box(),
        ),
        rx.cond(
            State.mcs_dv_actions_locked,
            rx.callout(
                "Manual Auth mode is locked. Click Authenticate first, then run Test Connection or Fetch.",
                icon="lock",
                color_scheme="amber",
            ),
            rx.box(),
        ),
        rx.cond(
            State.mcs_upload_error != "",
            rx.callout(
                State.mcs_upload_error,
                icon="triangle-alert",
                color_scheme="red",
            ),
            rx.box(),
        ),
        rx.cond(
            State.mcs_dv_auth_message != "",
            rx.callout(
                State.mcs_dv_auth_message,
                icon=rx.cond(State.mcs_dv_auth_ok, "badge-check", "triangle-alert"),
                color_scheme=rx.cond(State.mcs_dv_auth_ok, "green", "red"),
            ),
            rx.box(),
        ),
        rx.cond(
            State.mcs_dv_connection_message != "",
            rx.callout(
                State.mcs_dv_connection_message,
                icon=rx.cond(State.mcs_dv_connection_ok, "badge-check", "triangle-alert"),
                color_scheme=rx.cond(State.mcs_dv_connection_ok, "green", "red"),
            ),
            rx.box(),
        ),
        rx.cond(
            State.mcs_dv_last_transcript_id != "",
            rx.box(
                rx.text("Last fetched transcript", font_size="12px", font_weight="700", color="#334a6d"),
                rx.grid(
                    rx.text("Source", font_size="12px", color="#605e5c"),
                    rx.text(State.mcs_dv_last_source, font_size="12px", color="#201f1e"),
                    rx.text("Table", font_size="12px", color="#605e5c"),
                    rx.text(State.mcs_dv_last_table, font_size="12px", color="#201f1e"),
                    rx.text("Transcript ID", font_size="12px", color="#605e5c"),
                    rx.text(State.mcs_dv_last_transcript_id, font_size="12px", color="#201f1e"),
                    rx.text("Created", font_size="12px", color="#605e5c"),
                    rx.text(State.mcs_dv_last_created_at, font_size="12px", color="#201f1e"),
                    rx.text("Conversation ID", font_size="12px", color="#605e5c"),
                    rx.text(State.mcs_dv_last_conversation_id, font_size="12px", color="#201f1e"),
                    columns="2",
                    row_gap="6px",
                    column_gap="12px",
                    width="100%",
                ),
                border="1px solid #e1dfdd",
                border_radius="8px",
                padding="10px",
                width="100%",
            ),
            rx.box(),
        ),
        spacing="2",
        width="100%",
        align="start",
    )


def transcript_input_choice_area() -> rx.Component:
    """Landing first-step choice: upload JSON or fetch from Dataverse."""
    return rx.vstack(
        rx.text(
            "Step 1: Choose transcript input method",
            font_size="13px",
            font_weight="700",
            color="#201f1e",
        ),
        rx.hstack(
            rx.button(
                "Upload JSON",
                on_click=State.set_mcs_landing_transcript_mode("upload"),
                size="2",
                variant=rx.cond(State.mcs_landing_transcript_mode == "upload", "solid", "outline"),
                color_scheme=rx.cond(State.mcs_landing_transcript_mode == "upload", "blue", "gray"),
                cursor="pointer",
            ),
            rx.button(
                "Fetch from Dataverse",
                on_click=State.set_mcs_landing_transcript_mode("dataverse"),
                size="2",
                variant=rx.cond(State.mcs_landing_transcript_mode == "dataverse", "solid", "outline"),
                color_scheme=rx.cond(State.mcs_landing_transcript_mode == "dataverse", "blue", "gray"),
                cursor="pointer",
            ),
            spacing="2",
            flex_wrap="wrap",
        ),
        rx.cond(
            State.mcs_landing_transcript_mode == "dataverse",
            _mcs_dataverse_fetch_block(),
            json_upload_area(),
        ),
        width="100%",
        spacing="3",
        align="start",
    )


# ── Detected info panel (read-only summary) ────────────────────────────────────


def detected_info_panel() -> rx.Component:
    return rx.cond(
        State.has_detection,
        card(
            section_heading("Detected Solution"),
            info_row("Bot schema name", State.detected_bot_schema),
            info_row("Solution display name", State.detected_solution_display),
            info_row(
                "Botcomponent folders",
                rx.badge(State.detected_component_count, color_scheme="blue"),
            ),
            margin_top="16px",
        ),
        rx.box(),
    )


# ── Name inputs ──────────────────────────────────────────────────────────────────


def name_inputs() -> rx.Component:
    return rx.cond(
        State.has_detection,
        card(
            section_heading("New Names"),
            rx.text(
                "Enter the new names for the renamed copy. Technical identifiers are derived automatically.",
                font_size="13px",
                color="#605e5c",
                margin_bottom="16px",
            ),
            rx.vstack(
                # ── Agent sub-section ─────────────────────────────
                sub_heading("AGENT (COPILOT STUDIO)"),
                rx.box(
                    label("Display name"),
                    rx.input(
                        placeholder="e.g. My New Bot",
                        value=State.new_agent_name,
                        on_change=State.set_new_agent_name,
                        size="3",
                        width="100%",
                    ),
                    rx.cond(
                        State.derived_schema != "",
                        rx.text(
                            "→ Schema name: " + State.derived_schema,
                            font_size="11px",
                            color="#605e5c",
                            margin_top="4px",
                        ),
                        rx.box(),
                    ),
                    width="100%",
                ),
                rx.divider(margin_y="4px"),
                # ── Solution sub-section ──────────────────────────
                sub_heading("SOLUTION"),
                rx.box(
                    label("Display name"),
                    rx.input(
                        placeholder="e.g. My New Bot Solution",
                        value=State.new_solution_display_name,
                        on_change=State.set_new_solution_display_name,
                        size="3",
                        width="100%",
                    ),
                    rx.cond(
                        State.derived_solution_unique != "",
                        rx.text(
                            "→ Unique name: " + State.derived_solution_unique,
                            font_size="11px",
                            color="#605e5c",
                            margin_top="4px",
                        ),
                        rx.box(),
                    ),
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            margin_top="16px",
        ),
        rx.box(),
    )


# ── Action bar ────────────────────────────────────────────────────────────────


def action_bar() -> rx.Component:
    return rx.cond(
        State.has_detection,
        rx.hstack(
            rx.button(
                rx.cond(
                    State.is_processing,
                    rx.hstack(
                        rx.spinner(size="2"),
                        rx.text("Processing…"),
                        spacing="2",
                    ),
                    rx.hstack(rx.icon("refresh-cw", size=16), rx.text("Rename Solution"), spacing="2"),
                ),
                on_click=State.process,
                is_disabled=~State.can_process | State.is_processing,
                background_color=PRIMARY,
                color="white",
                size="3",
                border_radius="12px",
                _hover={"background_color": PRIMARY_DARK},
                _disabled={"opacity": "0.5", "cursor": "not-allowed"},
            ),
            rx.button(
                "Reset",
                on_click=State.clear_all,
                variant="outline",
                size="3",
                border_radius="12px",
            ),
            spacing="3",
            margin_top="16px",
        ),
        rx.box(),
    )


# ── Error / success banners ───────────────────────────────────────────────────
def no_agent_warning_banner() -> rx.Component:
    return rx.cond(
        State.no_agent_warning != "",
        rx.callout(
            State.no_agent_warning,
            icon="info",
            color_scheme="amber",
            margin_top="16px",
        ),
        rx.box(),
    )


def inspect_error_banner() -> rx.Component:
    return rx.cond(
        State.inspect_error != "",
        rx.callout(
            State.inspect_error,
            icon="triangle-alert",
            color_scheme="red",
            margin_top="16px",
        ),
        rx.box(),
    )


def process_error_banner() -> rx.Component:
    return rx.cond(
        State.process_error != "",
        rx.callout(
            State.process_error,
            icon="triangle-alert",
            color_scheme="red",
            margin_top="16px",
        ),
        rx.box(),
    )


# ── Result panel ──────────────────────────────────────────────────────────────


def result_panel() -> rx.Component:
    return rx.cond(
        State.process_success,
        card(
            rx.hstack(
                rx.icon("circle-check", color=SUCCESS, size=24),
                rx.heading("Rename Complete", size="4", color=SUCCESS),
                spacing="2",
                align="center",
                margin_bottom="12px",
            ),
            info_row("Files modified", rx.badge(State.result_files_modified, color_scheme="green")),
            info_row("Folders renamed", rx.badge(State.result_folders_renamed, color_scheme="green")),
            rx.divider(margin_y="10px"),
            sub_heading("AGENT (COPILOT STUDIO)"),
            info_row("Old schema name", State.result_old_schema),
            info_row("New schema name", State.result_new_schema),
            rx.divider(margin_y="10px"),
            sub_heading("SOLUTION"),
            info_row("Old unique name", State.result_old_solution),
            info_row("New unique name", State.result_new_solution),
            # Warnings
            rx.cond(
                State.has_result_warnings,
                rx.vstack(
                    rx.foreach(
                        State.result_warnings,
                        lambda w: rx.callout(w, icon="info", color_scheme="blue", size="1"),
                    ),
                    margin_top="12px",
                    width="100%",
                    spacing="2",
                ),
                rx.box(),
            ),
            # Download button – triggers a data-URL download via Reflex event
            # to avoid cross-origin issues between the Vite frontend (port 3000)
            # and the FastAPI backend (port 8000).
            rx.button(
                rx.hstack(
                    rx.icon("download", size=16),
                    rx.text("Download Renamed ZIP"),
                    spacing="2",
                ),
                on_click=State.download_result,
                background_color=SUCCESS,
                color="white",
                size="3",
                border_radius="4px",
                _hover={"background_color": "#0b6a0b"},
                margin_top="16px",
            ),
            border=f"1px solid {SUCCESS}",
            margin_top="16px",
        ),
        rx.box(),
    )


# ── Navbar ────────────────────────────────────────────────────────────────────


def navbar() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.hstack(
                rx.icon("bot", color="white", size=24),
                rx.heading(
                    "Power Platform Agent Toolkit",
                    size="5",
                    color="white",
                    font_weight="600",
                ),
                spacing="3",
                align="center",
            ),
            rx.text(
                "Rename · Visualise · Validate · Check · Analyse · Dependencies — Copilot Studio solution exports",
                color="rgba(255,255,255,0.7)",
                font_size="13px",
                display=["none", "none", "block"],
            ),
            # Show logged-in user + logout when auth is active
            rx.cond(
                State.is_authenticated,
                rx.hstack(
                    rx.icon("user", color="rgba(255,255,255,0.85)", size=16),
                    rx.text(State.username, color="rgba(255,255,255,0.85)", font_size="13px"),
                    rx.button(
                        "Sign out",
                        on_click=State.logout,
                        size="1",
                        variant="ghost",
                        color="rgba(255,255,255,0.85)",
                        _hover={"color": "white", "background": "rgba(255,255,255,0.15)"},
                        cursor="pointer",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.box(),
            ),
            justify="between",
            align="center",
            width="100%",
        ),
        background="linear-gradient(110deg, #0a66ff 0%, #0098d8 55%, #11b28f 100%)",
        box_shadow="0 8px 22px rgba(6, 42, 100, 0.18)",
        position="sticky",
        top="0",
        z_index="20",
        padding_x="24px",
        padding_y="14px",
        width="100%",
    )


def feedback_footer() -> rx.Component:
    """Bottom-left floating footer with GitHub feedback links and version info."""
    app_version = get_app_version()
    return rx.box(
        rx.hstack(
            rx.link(
                rx.hstack(
                    rx.icon("circle-alert", size=13),
                    rx.text("Create Issue", font_size="12px", font_weight="600"),
                    spacing="1",
                    align="center",
                ),
                href=ISSUE_URL,
                target="_blank",
                rel="noopener noreferrer",
                color="#a4262c",
                text_decoration="none",
                _hover={"text_decoration": "underline"},
            ),
            rx.text("·", font_size="12px", color="#a19f9d"),
            rx.link(
                rx.hstack(
                    rx.icon("square-pen", size=13),
                    rx.text("Feature Ask Simple", font_size="12px", font_weight="600"),
                    spacing="1",
                    align="center",
                ),
                href=OPEN_ISSUE_URL,
                target="_blank",
                rel="noopener noreferrer",
                color="#605e5c",
                text_decoration="none",
                _hover={"text_decoration": "underline"},
            ),
            rx.text("·", font_size="12px", color="#a19f9d"),
            rx.link(
                rx.hstack(
                    rx.icon("lightbulb", size=13),
                    rx.text("Request Feature", font_size="12px", font_weight="600"),
                    spacing="1",
                    align="center",
                ),
                href=FEATURE_URL,
                target="_blank",
                rel="noopener noreferrer",
                color="#0078d4",
                text_decoration="none",
                _hover={"text_decoration": "underline"},
            ),
            rx.text("·", font_size="12px", color="#a19f9d"),
            rx.text(f"v{app_version}", font_size="12px", color="#334a6d", font_weight="600"),
            rx.text("·", font_size="12px", color="#a19f9d"),
            rx.text(LICENSE_NAME, font_size="12px", color="#334a6d", font_weight="600"),
            spacing="2",
            align="center",
        ),
        position="fixed",
        left="16px",
        bottom="12px",
        background="rgba(255,255,255,0.97)",
        backdrop_filter="blur(3px)",
        border=f"1px solid {SURFACE_BORDER}",
        border_radius="999px",
        box_shadow="0 10px 26px rgba(11, 35, 76, 0.16)",
        padding="10px 14px",
        z_index="1000",
    )


# ── Visualization panel ───────────────────────────────────────────────────────


def visualization_panel() -> rx.Component:
    """Full-width visualization content rendered inside the Visualize tab."""
    return rx.cond(
        State.is_visualizing,
        rx.center(
            rx.vstack(
                rx.spinner(size="3", color=PRIMARY),
                rx.text("Analysing solution structure…", font_size="13px", color="#605e5c"),
                spacing="3",
                align="center",
            ),
            padding_y="48px",
            width="100%",
        ),
        rx.cond(
            State.viz_error != "",
            rx.callout(
                State.viz_error,
                icon="triangle-alert",
                color_scheme="orange",
                margin_top="8px",
            ),
            rx.cond(
                State.has_visualization,
                rx.vstack(
                    rx.foreach(State.viz_segments, render_segment),
                    width="100%",
                    spacing="4",
                ),
                rx.center(
                    rx.vstack(
                        rx.icon("git-branch", size=36, color="#c8c6c4"),
                        rx.text(
                            "Upload a solution ZIP or snapshot ZIP to see the visualization",
                            font_size="14px",
                            color="#a19f9d",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    padding_y="48px",
                    width="100%",
                ),
            ),
        ),
    )


# ── Validation panel ──────────────────────────────────────────────────────────


def _validation_result_item(result: dict) -> rx.Component:
    """Render a single validation result row with severity-coloured left border."""
    border_color = rx.match(
        result["severity"],
        ("pass", "#107c10"),
        ("warning", "#c7921e"),
        ("fail", "#a4262c"),
        "#797673",
    )
    bg_color = rx.match(
        result["severity"],
        ("pass", "#f6fff6"),
        ("warning", "#fffbe6"),
        ("fail", "#fff6f6"),
        "#fafafa",
    )
    badge = rx.match(
        result["severity"],
        ("pass", rx.badge("✓ PASS", color_scheme="green", variant="soft", size="1")),
        ("warning", rx.badge("⚠ WARN", color_scheme="amber", variant="soft", size="1")),
        ("fail", rx.badge("✗ FAIL", color_scheme="red", variant="soft", size="1")),
        rx.badge(result["severity"], color_scheme="gray", variant="soft", size="1"),
    )
    return rx.box(
        rx.hstack(
            badge,
            rx.text(
                result["title"],
                font_size="13px",
                font_weight="600",
                color="#201f1e",
            ),
            spacing="2",
            align="center",
            flex_wrap="wrap",
        ),
        rx.text(
            result["detail"],
            font_size="12px",
            color="#605e5c",
            margin_top="5px",
            line_height="1.55",
        ),
        padding="10px 14px",
        border_left_width="3px",
        border_left_style="solid",
        border_left_color=border_color,
        background=bg_color,
        border_radius="0 4px 4px 0",
        margin_bottom="8px",
        width="100%",
    )


def _validation_summary_badge(count: rx.Var, label: str, color: str) -> rx.Component:
    return rx.hstack(
        rx.text(count, font_size="20px", font_weight="700", color=color),
        rx.text(label, font_size="12px", color="#605e5c", font_weight="500"),
        spacing="1",
        align="baseline",
    )


def validation_panel() -> rx.Component:
    """Full-width validation content rendered inside the Validate tab."""
    return rx.cond(
        State.is_validating,
        rx.center(
            rx.vstack(
                rx.spinner(size="3", color=PRIMARY),
                rx.text(
                    "Validating instructions against best practices…",
                    font_size="13px",
                    color="#605e5c",
                ),
                spacing="3",
                align="center",
            ),
            padding_y="48px",
            width="100%",
        ),
        rx.cond(
            State.validation_error != "",
            rx.callout(
                State.validation_error,
                icon="triangle-alert",
                color_scheme="red",
                margin_top="8px",
            ),
            rx.cond(
                State.has_validation,
                rx.vstack(
                    # ── Header card ───────────────────────────────────────
                    card(
                        rx.hstack(
                            rx.vstack(
                                rx.hstack(
                                    rx.icon("shield-check", color=PRIMARY, size=20),
                                    rx.heading(
                                        "Validation Report",
                                        size="4",
                                        color="#201f1e",
                                    ),
                                    spacing="2",
                                    align="center",
                                ),
                                rx.hstack(
                                    rx.text(
                                        "Model: ",
                                        font_size="13px",
                                        color="#605e5c",
                                    ),
                                    rx.cond(
                                        State.validation_model_display != "",
                                        rx.badge(
                                            State.validation_model_display,
                                            color_scheme="blue",
                                            variant="soft",
                                        ),
                                        rx.badge("Unknown", color_scheme="gray", variant="soft"),
                                    ),
                                    rx.text(
                                        "·",
                                        font_size="13px",
                                        color="#c8c6c4",
                                    ),
                                    rx.text(
                                        State.validation_instructions_length_str + " chars",
                                        font_size="13px",
                                        color="#605e5c",
                                    ),
                                    spacing="2",
                                    align="center",
                                    flex_wrap="wrap",
                                ),
                                spacing="2",
                                align="start",
                            ),
                            rx.spacer(),
                            # ── Summary counts ────────────────────────────
                            rx.hstack(
                                _validation_summary_badge(State.validation_pass_count, "passed", "#107c10"),
                                rx.divider(orientation="vertical", height="32px"),
                                _validation_summary_badge(State.validation_warn_count, "warnings", "#c7921e"),
                                rx.divider(orientation="vertical", height="32px"),
                                _validation_summary_badge(State.validation_fail_count, "failed", "#a4262c"),
                                spacing="4",
                                align="center",
                            ),
                            align="center",
                            width="100%",
                            flex_wrap="wrap",
                            gap="16px",
                        ),
                        width="100%",
                    ),
                    # ── Results list ──────────────────────────────────────
                    card(
                        sub_heading("RULE CHECKS"),
                        rx.vstack(
                            rx.foreach(
                                State.validation_results,
                                _validation_result_item,
                            ),
                            width="100%",
                            spacing="0",
                        ),
                        width="100%",
                    ),
                    # ── Best practices toggle ─────────────────────────────
                    rx.cond(
                        State.validation_best_practices != "",
                        rx.vstack(
                            rx.button(
                                rx.hstack(
                                    rx.cond(
                                        State.show_best_practices,
                                        rx.icon("chevron-down", size=14),
                                        rx.icon("chevron-right", size=14),
                                    ),
                                    rx.text(
                                        rx.cond(
                                            State.show_best_practices,
                                            "Hide Best Practices for " + State.validation_model_display,
                                            "Show Best Practices for " + State.validation_model_display,
                                        ),
                                        font_size="13px",
                                        font_weight="600",
                                    ),
                                    spacing="2",
                                    align="center",
                                ),
                                on_click=State.toggle_best_practices,
                                variant="outline",
                                color=PRIMARY,
                                border_color=PRIMARY,
                                size="2",
                                cursor="pointer",
                            ),
                            rx.cond(
                                State.show_best_practices,
                                card(
                                    rx.markdown(
                                        State.validation_best_practices,
                                        component_map={
                                            "h1": lambda text: rx.heading(
                                                text,
                                                size="5",
                                                margin_bottom="10px",
                                                color="#201f1e",
                                            ),
                                            "h2": lambda text: rx.heading(
                                                text,
                                                size="4",
                                                margin_top="18px",
                                                margin_bottom="8px",
                                                color="#201f1e",
                                            ),
                                            "h3": lambda text: rx.heading(
                                                text,
                                                size="3",
                                                margin_top="14px",
                                                margin_bottom="6px",
                                                color="#323130",
                                            ),
                                            "p": lambda text: rx.text(
                                                text,
                                                font_size="13px",
                                                color="#323130",
                                                line_height="1.6",
                                            ),
                                            "code": lambda text: rx.code(text, font_size="12px"),
                                        },
                                    ),
                                    width="100%",
                                    border="1px solid #edebe9",
                                ),
                                rx.box(),
                            ),
                            width="100%",
                            spacing="3",
                            align="start",
                        ),
                        rx.box(),
                    ),
                    width="100%",
                    spacing="4",
                    align="start",
                ),
                # ── Empty state ───────────────────────────────────────────
                rx.center(
                    rx.vstack(
                        rx.icon("shield-check", size=36, color="#c8c6c4"),
                        rx.text(
                            "Upload a solution ZIP or snapshot ZIP to validate the agent's instructions",
                            font_size="14px",
                            color="#a19f9d",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    padding_y="48px",
                    width="100%",
                ),
            ),
        ),
    )


# ── Login form ────────────────────────────────────────────────────────────────


def login_form() -> rx.Component:
    """Centred login card shown on the /login page."""
    return rx.center(
        card(
            rx.vstack(
                rx.hstack(
                    rx.icon("bot", color=PRIMARY, size=28),
                    rx.heading(
                        "Power Platform Agent Toolkit",
                        size="5",
                        color="#201f1e",
                        font_weight="700",
                    ),
                    spacing="3",
                    align="center",
                ),
                rx.text(
                    "Sign in to continue",
                    font_size="14px",
                    color="#605e5c",
                    margin_bottom="4px",
                ),
                rx.divider(color_scheme="gray", margin_y="4px"),
                rx.cond(
                    State.auth_error != "",
                    rx.callout(
                        State.auth_error,
                        icon="circle-alert",
                        color_scheme="red",
                        size="1",
                    ),
                    rx.box(),
                ),
                rx.vstack(
                    rx.vstack(
                        label("Username"),
                        rx.input(
                            placeholder="Enter username",
                            value=State.username,
                            on_change=State.set_username,
                            width="100%",
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    rx.vstack(
                        label("Password"),
                        rx.input(
                            type="password",
                            placeholder="Enter password",
                            value=State.password,
                            on_change=State.set_password,
                            width="100%",
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.button(
                    "Sign in",
                    on_click=State.login,
                    width="100%",
                    background_color=PRIMARY,
                    color="white",
                    size="3",
                    cursor="pointer",
                    _hover={"background_color": "#005a9e"},
                ),
                spacing="4",
                align="start",
                width="320px",
            ),
        ),
        min_height="100vh",
        background_color=BG,
        width="100%",
    )


# ── MCS Analyse panel ─────────────────────────────────────────────────────────


def _mcs_section_tab_bar() -> rx.Component:
    """Inner tab bar for MCS analyse sub-sections."""

    def _btn(tab_id: str, icon_name: str, lbl: str) -> rx.Component:
        active = State.mcs_analyse_tab == tab_id
        return rx.box(
            rx.hstack(
                rx.icon(icon_name, size=14),
                rx.text(lbl, font_size="13px", font_weight="600"),
                spacing="2",
                align="center",
            ),
            on_click=State.set_mcs_analyse_tab(tab_id),
            padding="8px 16px",
            cursor="pointer",
            border_bottom=rx.cond(active, f"2px solid {PRIMARY}", "2px solid transparent"),
            color=rx.cond(active, PRIMARY, "#605e5c"),
            _hover={"color": PRIMARY},
            transition="all 0.15s ease",
            user_select="none",
        )

    return rx.cond(
        State.mcs_source == "transcript",
        rx.hstack(
            _btn("credits", "coins", "Credits"),
            _btn("conversation", "message-square", "Conversation"),
            spacing="0",
            border_bottom="1px solid #edebe9",
            width="100%",
            overflow_x="auto",
        ),
        rx.hstack(
            _btn("profile", "user-round", "Profile"),
            _btn("knowledge_tools", "database", "Knowledge & Tools"),
            _btn("topics", "list", "Topics"),
            _btn("graph", "git-branch", "Topic Graph"),
            _btn("model_comparison", "bar-chart-2", "Model"),
            _btn("credits", "coins", "Credits"),
            _btn("conversation", "message-square", "Conversation"),
            spacing="0",
            border_bottom="1px solid #edebe9",
            width="100%",
            overflow_x="auto",
        ),
    )


def _mcs_upload_form() -> rx.Component:
    """Transcript JSON upload form for the Conversation tab."""
    return rx.vstack(
        rx.upload(
            rx.vstack(
                rx.icon("file-json", color=PRIMARY, size=36),
                rx.text(
                    "Drag & drop session transcript JSON",
                    font_size="15px",
                    font_weight="600",
                    color="#201f1e",
                ),
                rx.text("or click to browse", font_size="13px", color="#605e5c"),
                spacing="2",
                align="center",
            ),
            id="mcs_upload",
            accept={".json": ["application/json"]},
            multiple=False,
            border=f"2px dashed {PRIMARY}",
            border_radius="8px",
            padding="32px",
            cursor="pointer",
            width="100%",
            on_drop=State.handle_mcs_upload(rx.upload_files(upload_id="mcs_upload")),  # type: ignore[arg-type]
            _hover={"background_color": "#deecf9"},
        ),
        rx.cond(
            State.mcs_upload_error != "",
            rx.callout(
                State.mcs_upload_error,
                icon="triangle-alert",
                color_scheme="red",
                margin_top="8px",
            ),
            rx.box(),
        ),
        rx.divider(margin_y="4px"),
        _mcs_dataverse_fetch_block(),
        spacing="3",
        width="100%",
        align="start",
    )


def _mcs_credit_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["meter"], font_size="13px", color="#201f1e", font_weight="500"),
        rx.text(item["count"], font_size="13px", color="#323130", text_align="right"),
        rx.text(item["rate"], font_size="13px", color="#605e5c", text_align="right"),
        rx.text(item["credits"], font_size="13px", color="#323130", font_weight="600", text_align="right"),
        columns="3fr 1fr 1fr 1fr",
        gap="8px",
        align="center",
        padding_y="8px",
        border_bottom="1px solid #f3f2f1",
        width="100%",
    )


def _mcs_credits_panel() -> rx.Component:
    return card(
        rx.hstack(
            rx.vstack(
                rx.text("Predicted Copilot Credits", font_size="12px", color="#605e5c", font_weight="600"),
                rx.text(
                    State.mcs_credit_total,
                    font_size="30px",
                    font_weight="800",
                    color=PRIMARY,
                    line_height="1.1",
                ),
                align="start",
                spacing="1",
            ),
            rx.spacer(),
            rx.badge("Heuristic Estimate", color_scheme="amber", variant="soft"),
            align="start",
            width="100%",
            margin_bottom="14px",
        ),
        rx.box(
            rx.grid(
                rx.text("Meter", font_size="12px", color="#605e5c", font_weight="700"),
                rx.text("Count", font_size="12px", color="#605e5c", font_weight="700", text_align="right"),
                rx.text("Rate", font_size="12px", color="#605e5c", font_weight="700", text_align="right"),
                rx.text("Credits", font_size="12px", color="#605e5c", font_weight="700", text_align="right"),
                columns="3fr 1fr 1fr 1fr",
                gap="8px",
                padding_y="8px",
                width="100%",
            ),
            rx.foreach(State.mcs_credit_rows, _mcs_credit_row),
            width="100%",
            border="1px solid #edebe9",
            border_radius="8px",
            padding_x="12px",
            background="#faf9f8",
        ),
        rx.vstack(
            rx.text("Assumptions", font_size="13px", color="#201f1e", font_weight="700"),
            rx.foreach(
                State.mcs_credit_assumptions,
                lambda line: rx.hstack(
                    rx.text("•", color="#605e5c", margin_top="1px"),
                    rx.text(line, font_size="13px", color="#605e5c"),
                    align="start",
                    spacing="2",
                    width="100%",
                ),
            ),
            align="start",
            spacing="2",
            margin_top="14px",
            width="100%",
        ),
        width="100%",
    )


def _mcs_flow_message(item: dict) -> rx.Component:
    """Render a single message bubble in transcript flow view."""
    is_user = item["role"] == "user"
    return rx.vstack(
        rx.hstack(
            rx.cond(
                is_user,
                rx.box(),
                rx.hstack(
                    rx.icon("bot", size=14, color="#0a66ff"),
                    rx.text(item["actor"], font_size="12px", font_weight="700", color="#1f3a63"),
                    rx.cond(
                        item["timestamp"] != "",
                        rx.text(item["timestamp"], font_size="11px", color="#8a8886"),
                        rx.box(),
                    ),
                    spacing="2",
                    align="center",
                ),
            ),
            rx.cond(
                is_user,
                rx.hstack(
                    rx.cond(
                        item["timestamp"] != "",
                        rx.text(item["timestamp"], font_size="11px", color="#8a8886"),
                        rx.box(),
                    ),
                    rx.text(item["actor"], font_size="12px", font_weight="700", color="#1f3a63"),
                    rx.icon("user-round", size=14, color="#0a66ff"),
                    spacing="2",
                    align="center",
                ),
                rx.box(),
            ),
            width="100%",
            justify=rx.cond(is_user, "end", "start"),
        ),
        rx.hstack(
            rx.box(
                rx.text(item["text"], font_size="15px", color="#222", line_height="1.55"),
                max_width=["100%", "100%", "72%"],
                background=rx.cond(is_user, "#cae8f5", "#ffffff"),
                border=rx.cond(is_user, "1px solid #9fd0e8", "1px solid #d9d8d7"),
                border_radius=rx.cond(is_user, "14px 14px 4px 14px", "14px 14px 14px 4px"),
                padding="14px 16px",
                box_shadow="0 6px 18px rgba(0,0,0,0.06)",
            ),
            width="100%",
            justify=rx.cond(is_user, "end", "start"),
        ),
        spacing="2",
        width="100%",
        align="stretch",
    )


def _mcs_flow_event(item: dict) -> rx.Component:
    """Render a system/tool event card between messages."""
    is_error = item["tone"] == "error"
    return rx.center(
        rx.box(
            rx.hstack(
                rx.icon(
                    rx.cond(is_error, "triangle-alert", "workflow"),
                    size=16,
                    color=rx.cond(is_error, "#a4262c", "#0a66ff"),
                ),
                rx.vstack(
                    rx.hstack(
                        rx.text(item["title"], font_size="12px", font_weight="700", color="#1f3a63"),
                        rx.cond(
                            item["timestamp"] != "",
                            rx.text(item["timestamp"], font_size="11px", color="#8a8886"),
                            rx.box(),
                        ),
                        spacing="2",
                        align="center",
                        flex_wrap="wrap",
                    ),
                    rx.text(item["summary"], font_size="12px", color="#5f5b56", line_height="1.45"),
                    align="start",
                    spacing="1",
                ),
                spacing="2",
                align="start",
                width="100%",
            ),
            width=["100%", "100%", "78%"],
            background=rx.cond(is_error, "#fff3f3", "#f5f9ff"),
            border=rx.cond(is_error, "1px solid #e6b3b3", "1px solid #cde0ff"),
            border_radius="12px",
            padding="10px 12px",
        ),
        width="100%",
    )


def _mcs_flow_item(item: dict) -> rx.Component:
    return rx.cond(item["kind"] == "message", _mcs_flow_message(item), _mcs_flow_event(item))


def _mcs_kpi_card(item: dict) -> rx.Component:
    border_color = rx.match(
        item["tone"],
        ("warn", "#d29a1f"),
        "#d7e2f2",
    )
    return rx.box(
        rx.text(item["label"], font_size="12px", color="#5d6f8f", font_weight="700"),
        rx.text(item["value"], font_size="26px", color="#14345c", font_weight="800", line_height="1.1"),
        rx.text(item["hint"], font_size="11px", color="#7d879a"),
        border=f"1px solid {border_color}",
        border_radius="12px",
        background="#ffffff",
        padding="12px 14px",
        width="100%",
    )


def _mcs_mix_row(item: dict) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.hstack(
                rx.box(width="10px", height="10px", border_radius="999px", background=item["color"]),
                rx.text(item["label"], font_size="12px", color="#30486d", font_weight="600"),
                spacing="2",
                align="center",
            ),
            rx.spacer(),
            rx.text(item["count"], font_size="12px", color="#30486d", font_weight="700"),
            spacing="2",
            width="100%",
            align="center",
        ),
        rx.box(
            rx.box(
                height="8px",
                border_radius="999px",
                background=item["color"],
                width=item["pct"],
                min_width="6px",
            ),
            height="8px",
            border_radius="999px",
            background="#e8eef8",
            width="100%",
        ),
        spacing="1",
        width="100%",
        align="start",
    )


def _mcs_highlight_chip(item: dict) -> rx.Component:
    tone_color = rx.match(
        item["tone"],
        ("good", "#107c10"),
        ("bad", "#a4262c"),
        "#0a66ff",
    )
    tone_bg = rx.match(
        item["tone"],
        ("good", "#f4fbf4"),
        ("bad", "#fff5f5"),
        "#f4f8ff",
    )
    return rx.box(
        rx.text(item["title"], font_size="11px", color="#5d6f8f", font_weight="700"),
        rx.text(item["value"], font_size="20px", color=tone_color, font_weight="800", line_height="1.1"),
        padding="10px 12px",
        border_radius="10px",
        background=tone_bg,
        border=f"1px solid {tone_color}33",
        min_width="120px",
    )


def _mcs_conversation_visual_dashboard() -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.hstack(
                    rx.icon("chart-column", size=16, color=PRIMARY),
                    rx.text("Conversation Analytics", font_size="14px", font_weight="700", color="#1f3a63"),
                    spacing="2",
                    align="center",
                ),
                rx.spacer(),
                rx.badge("Visual Summary", color_scheme="cyan", variant="soft", size="1"),
                width="100%",
                align="center",
            ),
            rx.grid(
                rx.foreach(State.mcs_conv_kpis, _mcs_kpi_card),
                columns="4",
                gap="10px",
                width="100%",
            ),
            rx.grid(
                rx.box(
                    rx.text("Event Mix", font_size="13px", color="#1f3a63", font_weight="700", margin_bottom="8px"),
                    rx.vstack(rx.foreach(State.mcs_conv_event_mix, _mcs_mix_row), spacing="2", width="100%"),
                    border="1px solid #dbe5f5",
                    border_radius="12px",
                    background="#fbfdff",
                    padding="12px",
                ),
                rx.box(
                    rx.text(
                        "Turn Latency Distribution",
                        font_size="13px",
                        color="#1f3a63",
                        font_weight="700",
                        margin_bottom="8px",
                    ),
                    rx.vstack(rx.foreach(State.mcs_conv_latency_bands, _mcs_mix_row), spacing="2", width="100%"),
                    border="1px solid #dbe5f5",
                    border_radius="12px",
                    background="#fbfdff",
                    padding="12px",
                ),
                columns="2",
                gap="10px",
                width="100%",
            ),
            rx.hstack(
                rx.foreach(State.mcs_conv_highlights, _mcs_highlight_chip),
                spacing="2",
                width="100%",
                flex_wrap="wrap",
            ),
            spacing="3",
            width="100%",
            align="start",
        ),
        width="100%",
        background="linear-gradient(130deg, #f8fbff 0%, #f6fbf8 100%)",
        border="1px solid #d4e4f9",
    )


def _mcs_conversation_flow_panel() -> rx.Component:
    return card(
        rx.hstack(
            rx.hstack(
                rx.icon("message-square", size=16, color=PRIMARY),
                rx.text("Conversation Flow", font_size="14px", font_weight="700", color="#1f3a63"),
                spacing="2",
                align="center",
            ),
            rx.spacer(),
            rx.badge(
                rx.cond(
                    State.mcs_conversation_flow_source == "snapshot",
                    "Snapshot Dialog View",
                    "Transcript View",
                ),
                color_scheme="blue",
                variant="soft",
                size="1",
            ),
            align="center",
            width="100%",
            margin_bottom="10px",
        ),
        rx.box(
            rx.vstack(
                rx.foreach(State.mcs_conversation_flow, _mcs_flow_item),
                spacing="4",
                width="100%",
                align="stretch",
            ),
            width="100%",
            background="linear-gradient(180deg, #f9fcff 0%, #f7f7f8 100%)",
            border="1px solid #dce6f5",
            border_radius="12px",
            padding=["10px", "12px", "14px"],
            max_height="720px",
            overflow_y="auto",
        ),
        width="100%",
    )


def _mcs_segment_block(segment: dict) -> rx.Component:
    """Render section segments as separated visual blocks for better readability."""
    return rx.box(
        render_segment(segment),
        width="100%",
        border="1px solid #e2e9f5",
        border_radius="12px",
        background="#ffffff",
        padding="14px",
        box_shadow="0 6px 18px rgba(9, 30, 66, 0.05)",
    )


# ── Solution Check panel ──────────────────────────────────────────────────────

_CHECK_CATEGORIES: list[str] = ["Solution", "Agent", "Topics", "Knowledge", "Security"]

_CAT_ICONS: dict[str, str] = {
    "Solution": "file-text",
    "Agent": "bot",
    "Topics": "list",
    "Knowledge": "database",
    "Security": "shield-alert",
}

_CAT_COLORS: dict[str, str] = {
    "Solution": "#0078d4",
    "Agent": "#7719aa",
    "Topics": "#107c10",
    "Knowledge": "#c7921e",
    "Security": "#a4262c",
}


def _check_category_pill(category: str) -> rx.Component:
    color = _CAT_COLORS.get(category, "#605e5c")
    icon_name = _CAT_ICONS.get(category, "circle")
    active = State.check_active_category == category
    return rx.box(
        rx.hstack(
            rx.icon(icon_name, size=13),
            rx.text(category, font_size="12px", font_weight="600"),
            spacing="1",
            align="center",
        ),
        on_click=rx.cond(
            active,
            State.set_check_active_category(""),
            State.set_check_active_category(category),
        ),
        padding="5px 12px",
        border_radius="16px",
        cursor="pointer",
        border=rx.cond(active, f"1.5px solid {color}", "1.5px solid #edebe9"),
        background=rx.cond(active, f"{color}18", "#ffffff"),
        color=rx.cond(active, color, "#605e5c"),
        _hover={"border_color": color, "color": color},
        transition="all 0.15s ease",
        user_select="none",
    )


def _check_result_item(result: dict) -> rx.Component:
    border_color = rx.match(
        result["severity"],
        ("pass", "#107c10"),
        ("warning", "#c7921e"),
        ("fail", "#a4262c"),
        ("info", "#0078d4"),
        "#797673",
    )
    bg_color = rx.match(
        result["severity"],
        ("pass", "#f6fff6"),
        ("warning", "#fffbe6"),
        ("fail", "#fff6f6"),
        ("info", "#f0f6ff"),
        "#fafafa",
    )
    badge = rx.match(
        result["severity"],
        ("pass", rx.badge("✓ PASS", color_scheme="green", variant="soft", size="1")),
        ("warning", rx.badge("⚠ WARN", color_scheme="amber", variant="soft", size="1")),
        ("fail", rx.badge("✗ FAIL", color_scheme="red", variant="soft", size="1")),
        ("info", rx.badge("ℹ INFO", color_scheme="blue", variant="soft", size="1")),
        rx.badge(result["severity"], color_scheme="gray", variant="soft", size="1"),
    )
    cat_color = rx.match(
        result["category"],
        ("Solution", "#0078d4"),
        ("Agent", "#7719aa"),
        ("Topics", "#107c10"),
        ("Knowledge", "#c7921e"),
        ("Security", "#a4262c"),
        "#605e5c",
    )
    return rx.box(
        rx.hstack(
            badge,
            rx.text(
                result["title"],
                font_size="13px",
                font_weight="600",
                color="#201f1e",
            ),
            rx.spacer(),
            rx.badge(
                result["category"],
                variant="soft",
                color_scheme="gray",
                size="1",
                font_size="10px",
                color=cat_color,
            ),
            spacing="2",
            align="center",
            flex_wrap="wrap",
            width="100%",
        ),
        rx.text(
            result["detail"],
            font_size="12px",
            color="#605e5c",
            margin_top="5px",
            line_height="1.55",
        ),
        padding="10px 14px",
        border_left_width="3px",
        border_left_style="solid",
        border_left_color=border_color,
        background=bg_color,
        border_radius="0 4px 4px 0",
        margin_bottom="8px",
        width="100%",
    )


def _check_summary_badge(count: rx.Var, label: str, color: str) -> rx.Component:
    return rx.hstack(
        rx.text(count, font_size="20px", font_weight="700", color=color),
        rx.text(label, font_size="12px", color="#605e5c", font_weight="500"),
        spacing="1",
        align="baseline",
    )


def solution_check_panel() -> rx.Component:
    """Full-width solution check report rendered inside the Check tab."""
    return rx.cond(
        State.is_checking,
        rx.center(
            rx.vstack(
                rx.spinner(size="3", color=PRIMARY),
                rx.text("Running solution checks…", font_size="13px", color="#605e5c"),
                spacing="3",
                align="center",
            ),
            padding_y="48px",
            width="100%",
        ),
        rx.cond(
            State.check_error != "",
            rx.callout(
                State.check_error,
                icon="triangle-alert",
                color_scheme="red",
                margin_top="8px",
            ),
            rx.cond(
                State.has_check,
                rx.vstack(
                    # ── Header card ───────────────────────────────────────
                    card(
                        rx.hstack(
                            rx.vstack(
                                rx.hstack(
                                    rx.icon("scan-search", color=PRIMARY, size=20),
                                    rx.heading(
                                        "Solution Check Report",
                                        size="4",
                                        color="#201f1e",
                                    ),
                                    spacing="2",
                                    align="center",
                                ),
                                rx.hstack(
                                    rx.cond(
                                        State.check_agent_name != "",
                                        rx.hstack(
                                            rx.text(
                                                "Agent:",
                                                font_size="13px",
                                                color="#605e5c",
                                            ),
                                            rx.badge(
                                                State.check_agent_name,
                                                color_scheme="purple",
                                                variant="soft",
                                            ),
                                            spacing="2",
                                            align="center",
                                        ),
                                        rx.box(),
                                    ),
                                    rx.cond(
                                        State.check_solution_name != "",
                                        rx.hstack(
                                            rx.text(
                                                "Solution:",
                                                font_size="13px",
                                                color="#605e5c",
                                            ),
                                            rx.badge(
                                                State.check_solution_name,
                                                color_scheme="blue",
                                                variant="soft",
                                            ),
                                            spacing="2",
                                            align="center",
                                        ),
                                        rx.box(),
                                    ),
                                    spacing="4",
                                    align="center",
                                    flex_wrap="wrap",
                                ),
                                spacing="2",
                                align="start",
                            ),
                            rx.spacer(),
                            # ── Summary counts ────────────────────────────
                            rx.hstack(
                                _check_summary_badge(State.check_pass_count, "passed", "#107c10"),
                                rx.divider(orientation="vertical", height="32px"),
                                _check_summary_badge(State.check_warn_count, "warnings", "#c7921e"),
                                rx.divider(orientation="vertical", height="32px"),
                                _check_summary_badge(State.check_fail_count, "failed", "#a4262c"),
                                rx.divider(orientation="vertical", height="32px"),
                                _check_summary_badge(State.check_info_count, "info", "#0078d4"),
                                spacing="4",
                                align="center",
                            ),
                            align="center",
                            width="100%",
                            flex_wrap="wrap",
                            gap="16px",
                        ),
                        width="100%",
                    ),
                    # ── Category filter pills ─────────────────────────────
                    card(
                        sub_heading("FILTER BY CATEGORY"),
                        rx.hstack(
                            _check_category_pill("Solution"),
                            _check_category_pill("Agent"),
                            _check_category_pill("Topics"),
                            _check_category_pill("Knowledge"),
                            _check_category_pill("Security"),
                            spacing="2",
                            flex_wrap="wrap",
                        ),
                        width="100%",
                    ),
                    # ── Results list ──────────────────────────────────────
                    card(
                        rx.hstack(
                            sub_heading("CHECK RESULTS"),
                            rx.spacer(),
                            rx.cond(
                                State.check_active_category != "",
                                rx.badge(
                                    State.check_active_category,
                                    color_scheme="blue",
                                    variant="soft",
                                    size="1",
                                ),
                                rx.text(
                                    "All categories",
                                    font_size="11px",
                                    color="#a19f9d",
                                ),
                            ),
                            align="center",
                            width="100%",
                            margin_bottom="12px",
                        ),
                        rx.vstack(
                            rx.foreach(
                                State.check_filtered_results,
                                _check_result_item,
                            ),
                            width="100%",
                            spacing="0",
                        ),
                        width="100%",
                    ),
                    width="100%",
                    spacing="4",
                    align="start",
                ),
                # ── Empty state ───────────────────────────────────────────
                rx.center(
                    rx.vstack(
                        rx.icon("scan-search", size=36, color="#c8c6c4"),
                        rx.text(
                            "Upload a solution ZIP to run the solution checker",
                            font_size="14px",
                            color="#a19f9d",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    padding_y="48px",
                    width="100%",
                ),
            ),
        ),
    )


def mcs_analyse_panel() -> rx.Component:
    """Full content for the Analyse tab with sub-section tabs."""
    return rx.cond(
        State.mcs_is_processing,
        rx.center(
            rx.vstack(
                rx.spinner(size="3", color=PRIMARY),
                rx.text("Analysing Copilot Studio snapshot…", font_size="13px", color="#605e5c"),
                spacing="3",
                align="center",
            ),
            padding_y="60px",
            width="100%",
        ),
        rx.cond(
            State.has_mcs_report,
            # ── Sub-tabbed report view ─────────────────────────────────────
            rx.vstack(
                # Header
                rx.hstack(
                    rx.icon("file-check-2", color=PRIMARY, size=20),
                    rx.heading(State.mcs_report_title, size="4", color="#201f1e"),
                    rx.spacer(),
                    rx.button(
                        rx.hstack(
                            rx.icon("download", size=14),
                            rx.text("Download .md", font_size="13px"),
                            spacing="2",
                            align="center",
                        ),
                        on_click=State.download_mcs_report,
                        variant="outline",
                        color=PRIMARY,
                        border_color=PRIMARY,
                        size="2",
                        cursor="pointer",
                    ),
                    rx.button(
                        rx.hstack(
                            rx.icon("x", size=14),
                            rx.text("Clear", font_size="13px"),
                            spacing="2",
                            align="center",
                        ),
                        on_click=State.clear_mcs_report,
                        variant="ghost",
                        color="#605e5c",
                        size="2",
                        cursor="pointer",
                    ),
                    align="center",
                    width="100%",
                    flex_wrap="wrap",
                    gap="8px",
                ),
                # Section tab bar
                _mcs_section_tab_bar(),
                # Active section content
                rx.box(
                    rx.vstack(
                        rx.cond(
                            State.mcs_analyse_tab == "credits",
                            _mcs_credits_panel(),
                            rx.cond(
                                (State.mcs_analyse_tab == "conversation") & State.has_mcs_conversation_flow,
                                rx.vstack(
                                    rx.cond(
                                        State.has_mcs_conv_visual_summary,
                                        _mcs_conversation_visual_dashboard(),
                                        rx.box(),
                                    ),
                                    _mcs_conversation_flow_panel(),
                                    rx.vstack(
                                        rx.foreach(State.mcs_current_section_segments, _mcs_segment_block),
                                        width="100%",
                                        spacing="3",
                                        align="start",
                                    ),
                                    width="100%",
                                    spacing="4",
                                    align="start",
                                ),
                                rx.vstack(
                                    rx.foreach(State.mcs_current_section_segments, _mcs_segment_block),
                                    width="100%",
                                    spacing="3",
                                    align="start",
                                ),
                            ),
                        ),
                        spacing="4",
                        width="100%",
                        padding_top="8px",
                        align="start",
                    ),
                    width="100%",
                ),
                spacing="3",
                width="100%",
                align="start",
            ),
            # ── No report yet: transcript JSON uploader ────────────────────
            rx.vstack(
                card(
                    section_heading("Conversation Transcript Analyser"),
                    rx.text(
                        "Drop a Copilot Studio snapshot ZIP in the upload zone above to analyse the agent, "
                        "or upload a standalone session transcript JSON here for conversation analysis.",
                        font_size="13px",
                        color="#605e5c",
                        margin_bottom="16px",
                    ),
                    _mcs_upload_form(),
                    width="100%",
                ),
                spacing="0",
                width="100%",
                align="start",
            ),
        ),
    )


# ── Evaluations panel ─────────────────────────────────────────────────────────


def _evals_sub_tab_btn(tab_id: str, icon_name: str, label_text: str, count: rx.Var) -> rx.Component:
    active = State.evals_sub_tab == tab_id
    return rx.box(
        rx.hstack(
            rx.icon(icon_name, size=14),
            rx.text(label_text, font_size="13px", font_weight="600"),
            rx.badge(count, color_scheme="gray", variant="soft", size="1"),
            spacing="2",
            align="center",
        ),
        on_click=State.set_evals_sub_tab(tab_id),
        padding="8px 16px",
        cursor="pointer",
        border_bottom=rx.cond(active, f"2px solid {PRIMARY}", "2px solid transparent"),
        color=rx.cond(active, PRIMARY, "#605e5c"),
        _hover={"color": PRIMARY},
        transition="all 0.15s ease",
        user_select="none",
    )


def _evals_test_set_pill(ts: dict) -> rx.Component:
    active = State.evals_active_test_set == ts["schema_name"]
    return rx.box(
        rx.hstack(
            rx.text(ts["display_name"], font_size="12px", font_weight="600"),
            rx.badge(ts["test_count"], color_scheme="purple", variant="soft", size="1"),
            spacing="1",
            align="center",
        ),
        on_click=rx.cond(
            active,
            State.set_evals_active_test_set(""),
            State.set_evals_active_test_set(ts["schema_name"]),
        ),
        padding="5px 12px",
        border_radius="16px",
        cursor="pointer",
        border=rx.cond(active, f"1.5px solid {PRIMARY}", "1.5px solid #edebe9"),
        background=rx.cond(active, f"{PRIMARY}18", "#ffffff"),
        color=rx.cond(active, PRIMARY, "#605e5c"),
        _hover={"border_color": PRIMARY, "color": PRIMARY},
        transition="all 0.15s ease",
        user_select="none",
    )


def _evals_eval_set_pill(es: dict) -> rx.Component:
    active = State.evals_active_eval_set == es["schema_name"]
    return rx.box(
        rx.hstack(
            rx.text(es["display_name"], font_size="12px", font_weight="600"),
            rx.badge(es["row_count"], color_scheme="teal", variant="soft", size="1"),
            spacing="1",
            align="center",
        ),
        on_click=rx.cond(
            active,
            State.set_evals_active_eval_set(""),
            State.set_evals_active_eval_set(es["schema_name"]),
        ),
        padding="5px 12px",
        border_radius="16px",
        cursor="pointer",
        border=rx.cond(active, f"1.5px solid {PRIMARY}", "1.5px solid #edebe9"),
        background=rx.cond(active, f"{PRIMARY}18", "#ffffff"),
        color=rx.cond(active, PRIMARY, "#605e5c"),
        _hover={"border_color": PRIMARY, "color": PRIMARY},
        transition="all 0.15s ease",
        user_select="none",
    )


def _test_case_row(tc: dict) -> rx.Component:
    """Render a single test case row."""
    return rx.box(
        rx.hstack(
            rx.box(
                rx.text(tc["set_name"], font_size="11px", color="#a19f9d", font_weight="500"),
                rx.text(tc["input"], font_size="13px", font_weight="600", color="#201f1e"),
                width="38%",
                flex_shrink="0",
            ),
            rx.box(
                rx.text(
                    tc["expected_response"],
                    font_size="12px",
                    color="#605e5c",
                    line_height="1.5",
                ),
                width="47%",
                flex_shrink="0",
                overflow="hidden",
            ),
            rx.vstack(
                rx.badge(
                    tc["origin_type"],
                    color_scheme="blue",
                    variant="soft",
                    size="1",
                ),
                rx.badge(
                    rx.hstack(
                        rx.text("≥", font_size="10px"),
                        rx.text(tc["score_threshold"], font_size="10px"),
                        rx.text("%", font_size="10px"),
                        spacing="0",
                    ),
                    color_scheme="green",
                    variant="soft",
                    size="1",
                ),
                spacing="1",
                align="center",
                width="15%",
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        padding="10px 14px",
        border_bottom="1px solid #f3f2f1",
        _hover={"background": "#faf9f8"},
        width="100%",
    )


def _eval_data_row(row: dict) -> rx.Component:
    """Render a single evaluation data row."""
    return rx.box(
        rx.hstack(
            rx.box(
                rx.text(row["set_name"], font_size="11px", color="#a19f9d", font_weight="500"),
                rx.text(row["input"], font_size="13px", font_weight="600", color="#201f1e"),
                width="33%",
                flex_shrink="0",
            ),
            rx.box(
                rx.text(
                    row["expected_output"],
                    font_size="12px",
                    color="#605e5c",
                    line_height="1.5",
                ),
                width="47%",
                flex_shrink="0",
                overflow="hidden",
            ),
            rx.vstack(
                rx.badge(
                    row["source"],
                    color_scheme=rx.cond(row["source"] == "Manual", "green", "blue"),
                    variant="soft",
                    size="1",
                ),
                rx.cond(
                    row["keywords"] != "",
                    rx.text(
                        row["keywords"],
                        font_size="10px",
                        color="#a19f9d",
                        max_width="140px",
                        overflow="hidden",
                        text_overflow="ellipsis",
                        white_space="nowrap",
                    ),
                    rx.box(),
                ),
                spacing="1",
                align="start",
                width="20%",
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        padding="10px 14px",
        border_bottom="1px solid #f3f2f1",
        _hover={"background": "#faf9f8"},
        width="100%",
    )


def evals_panel() -> rx.Component:
    """Full-width evaluations panel for the Evals tab."""
    return rx.cond(
        State.has_evals,
        rx.vstack(
            # ── Header card ───────────────────────────────────────────────
            card(
                rx.hstack(
                    rx.vstack(
                        rx.hstack(
                            rx.icon("flask-conical", color=PRIMARY, size=20),
                            rx.heading("Built-in Evaluations", size="4", color="#201f1e"),
                            spacing="2",
                            align="center",
                        ),
                        rx.hstack(
                            rx.cond(
                                State.evals_test_total > 0,
                                rx.hstack(
                                    rx.text("Test cases:", font_size="13px", color="#605e5c"),
                                    rx.badge(
                                        State.evals_test_total,
                                        color_scheme="purple",
                                        variant="soft",
                                    ),
                                    spacing="2",
                                    align="center",
                                ),
                                rx.box(),
                            ),
                            rx.cond(
                                State.evals_eval_total > 0,
                                rx.hstack(
                                    rx.text("Eval rows:", font_size="13px", color="#605e5c"),
                                    rx.badge(
                                        State.evals_eval_total,
                                        color_scheme="teal",
                                        variant="soft",
                                    ),
                                    spacing="2",
                                    align="center",
                                ),
                                rx.box(),
                            ),
                            spacing="4",
                            align="center",
                            flex_wrap="wrap",
                        ),
                        spacing="2",
                        align="start",
                    ),
                    align="center",
                    width="100%",
                ),
                width="100%",
            ),
            # ── Sub-tab bar ───────────────────────────────────────────────
            rx.box(
                rx.hstack(
                    rx.cond(
                        State.evals_test_total > 0,
                        _evals_sub_tab_btn("tests", "list-checks", "Test Cases", State.evals_test_total),
                        rx.box(),
                    ),
                    rx.cond(
                        State.evals_eval_total > 0,
                        _evals_sub_tab_btn("evals", "flask-conical", "Evaluations", State.evals_eval_total),
                        rx.box(),
                    ),
                    spacing="0",
                    border_bottom="1px solid #edebe9",
                    width="100%",
                ),
                background="#ffffff",
                border_radius="8px 8px 0 0",
                width="100%",
            ),
            # ── Content ───────────────────────────────────────────────────
            rx.cond(
                State.evals_sub_tab == "tests",
                # Test cases panel
                card(
                    rx.cond(
                        State.evals_test_sets.length() > 1,
                        rx.vstack(
                            sub_heading("FILTER BY TEST SET"),
                            rx.hstack(
                                rx.foreach(State.evals_test_sets, _evals_test_set_pill),
                                spacing="2",
                                flex_wrap="wrap",
                            ),
                            margin_bottom="16px",
                            width="100%",
                            spacing="2",
                            align="start",
                        ),
                        rx.box(),
                    ),
                    rx.hstack(
                        rx.text("Input / Test Set", font_size="11px", font_weight="700", color="#605e5c", width="38%"),
                        rx.text("Expected Response", font_size="11px", font_weight="700", color="#605e5c", width="47%"),
                        rx.text("Info", font_size="11px", font_weight="700", color="#605e5c", width="15%"),
                        spacing="4",
                        padding_x="14px",
                        padding_y="6px",
                        background="#f3f2f1",
                        border_radius="4px",
                        margin_bottom="4px",
                        width="100%",
                    ),
                    rx.box(
                        rx.foreach(State.evals_filtered_test_cases, _test_case_row),
                        width="100%",
                        border="1px solid #edebe9",
                        border_radius="4px",
                        overflow="hidden",
                    ),
                    width="100%",
                ),
                # Evaluations panel
                card(
                    rx.cond(
                        State.evals_eval_sets.length() > 1,
                        rx.vstack(
                            sub_heading("FILTER BY EVALUATION SET"),
                            rx.hstack(
                                rx.foreach(State.evals_eval_sets, _evals_eval_set_pill),
                                spacing="2",
                                flex_wrap="wrap",
                            ),
                            margin_bottom="16px",
                            width="100%",
                            spacing="2",
                            align="start",
                        ),
                        rx.box(),
                    ),
                    # Graders info
                    rx.cond(
                        State.evals_active_eval_set != "",
                        rx.foreach(
                            State.evals_eval_sets,
                            lambda es: rx.cond(
                                es["schema_name"] == State.evals_active_eval_set,
                                rx.hstack(
                                    rx.text("Grader:", font_size="12px", color="#605e5c"),
                                    rx.badge(es["graders"], color_scheme="orange", variant="soft", size="1"),
                                    margin_bottom="12px",
                                    spacing="2",
                                    align="center",
                                ),
                                rx.box(),
                            ),
                        ),
                        rx.box(),
                    ),
                    rx.hstack(
                        rx.text("Input / Set", font_size="11px", font_weight="700", color="#605e5c", width="33%"),
                        rx.text("Expected Output", font_size="11px", font_weight="700", color="#605e5c", width="47%"),
                        rx.text("Info", font_size="11px", font_weight="700", color="#605e5c", width="20%"),
                        spacing="4",
                        padding_x="14px",
                        padding_y="6px",
                        background="#f3f2f1",
                        border_radius="4px",
                        margin_bottom="4px",
                        width="100%",
                    ),
                    rx.box(
                        rx.foreach(State.evals_filtered_eval_rows, _eval_data_row),
                        width="100%",
                        border="1px solid #edebe9",
                        border_radius="4px",
                        overflow="hidden",
                    ),
                    width="100%",
                ),
            ),
            width="100%",
            spacing="4",
            align="start",
        ),
        # Empty state
        rx.center(
            rx.vstack(
                rx.icon("flask-conical", size=36, color="#c8c6c4"),
                rx.text(
                    "No built-in evaluations found in the uploaded solution",
                    font_size="14px",
                    color="#a19f9d",
                ),
                spacing="3",
                align="center",
            ),
            padding_y="48px",
            width="100%",
        ),
    )


# ── Dependencies panel ────────────────────────────────────────────────────────


def _deps_segment_card(segment: dict) -> rx.Component:
    """Render dependency report segments with clear visual separation."""
    return rx.cond(
        segment["type"] == "mermaid",
        card(
            rx.hstack(
                rx.icon("git-branch", color=PRIMARY, size=16),
                rx.text("Dependency Diagram", font_size="13px", font_weight="700", color="#201f1e"),
                rx.spacer(),
                rx.button(
                    "-",
                    on_click=State.deps_zoom_out,
                    variant="outline",
                    size="1",
                    min_width="30px",
                    height="24px",
                    padding="0",
                ),
                rx.button(
                    "+",
                    on_click=State.deps_zoom_in,
                    variant="outline",
                    size="1",
                    min_width="30px",
                    height="24px",
                    padding="0",
                ),
                rx.button(
                    "Reset",
                    on_click=State.deps_zoom_reset,
                    variant="outline",
                    size="1",
                    height="24px",
                    padding_x="8px",
                ),
                rx.badge(State.deps_diagram_zoom_style, color_scheme="gray", variant="soft", size="1"),
                spacing="2",
                align="center",
                margin_bottom="10px",
            ),
            rx.box(
                rx.el.pre(
                    segment["content"],
                    class_name="mermaid",
                    width=State.deps_diagram_zoom_style,
                    min_width=State.deps_diagram_zoom_style,
                    background="#f7fbff",
                    border="1px solid #d7e2f2",
                    border_radius="14px",
                    box_shadow="inset 0 1px 0 rgba(255,255,255,0.85)",
                    padding="22px",
                ),
                width="100%",
                overflow_x="auto",
                overflow_y="auto",
            ),
            width="100%",
        ),
        card(
            rx.hstack(
                rx.icon("list", color=PRIMARY, size=16),
                rx.text("Dependency Summary", font_size="13px", font_weight="700", color="#201f1e"),
                spacing="2",
                align="center",
                margin_bottom="10px",
            ),
            render_segment(segment),
            width="100%",
        ),
    )


def _deps_mode_btn(mode_id: str, label_text: str) -> rx.Component:
    active = State.deps_diagram_mode == mode_id
    return rx.box(
        rx.text(label_text, font_size="12px", font_weight="700"),
        on_click=State.set_deps_diagram_mode(mode_id),
        padding="6px 12px",
        border_radius="999px",
        border=rx.cond(active, f"1.5px solid {PRIMARY}", "1.5px solid #d7e2f2"),
        background=rx.cond(active, "#eaf2ff", "#ffffff"),
        color=rx.cond(active, PRIMARY, "#51627a"),
        cursor="pointer",
        _hover={"border_color": PRIMARY, "color": PRIMARY},
        transition="all 0.15s ease",
    )


def _deps_relation_row(row: dict) -> rx.Component:
    return rx.grid(
        rx.text(row["dependent"], font_size="12px", color="#1f3a63", font_weight="600"),
        rx.badge(row["dependent_type"], color_scheme="blue", variant="soft", size="1"),
        rx.text(row["required"], font_size="12px", color="#201f1e", font_weight="600"),
        rx.badge(row["required_type"], color_scheme="red", variant="soft", size="1"),
        rx.text(row["source"], font_size="11px", color="#605e5c"),
        columns="2.2fr 1fr 2.2fr 1fr 1.4fr",
        gap="10px",
        align="center",
        padding_y="8px",
        padding_x="10px",
        border_bottom="1px solid #f3f2f1",
        width="100%",
    )


def _deps_sort_indicator(key: str) -> rx.Component:
    return rx.cond(
        State.deps_relation_sort_key == key,
        rx.icon(
            rx.cond(State.deps_relation_sort_dir == "asc", "arrow-up", "arrow-down"),
            size=12,
            color=PRIMARY,
        ),
        rx.icon("arrow-up-down", size=12, color="#9aa8bf"),
    )


def _deps_sortable_header(label: str, key: str) -> rx.Component:
    return rx.hstack(
        rx.text(label, font_size="11px", font_weight="700", color="#51627a"),
        _deps_sort_indicator(key),
        spacing="1",
        align="center",
        cursor="pointer",
        on_click=State.set_deps_relation_sort(key),
        _hover={"color": PRIMARY},
    )


def _deps_component_sort_indicator(key: str) -> rx.Component:
    return rx.cond(
        State.deps_component_sort_key == key,
        rx.icon(
            rx.cond(State.deps_component_sort_dir == "asc", "arrow-up", "arrow-down"),
            size=12,
            color=PRIMARY,
        ),
        rx.icon("arrow-up-down", size=12, color="#9aa8bf"),
    )


def _deps_component_sortable_header(label: str, key: str) -> rx.Component:
    return rx.hstack(
        rx.text(label, font_size="11px", font_weight="700", color="#51627a"),
        _deps_component_sort_indicator(key),
        spacing="1",
        align="center",
        cursor="pointer",
        on_click=State.set_deps_component_sort(key),
        _hover={"color": PRIMARY},
    )


def _deps_component_row(row: dict) -> rx.Component:
    cols = "1.6fr 2.4fr 1.2fr 0.6fr 1fr 1.2fr 1.2fr"

    def _cell(text: str, size: str = "11px", color: str = "#51627a", weight: str = "500") -> rx.Component:
        return rx.text(
            text,
            font_size=size,
            color=color,
            font_weight=weight,
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            width="100%",
            min_width="0",
            title=text,
        )

    return rx.grid(
        rx.box(_cell(row["name"], size="12px", color="#1f3a63", weight="600"), min_width="0"),
        rx.box(_cell(row["schema"], size="11px", color="#51627a"), min_width="0"),
        rx.box(
            rx.badge(
                row["type"],
                color_scheme="blue",
                variant="soft",
                size="1",
                white_space="nowrap",
                overflow="hidden",
                text_overflow="ellipsis",
                max_width="100%",
                title=row["type"],
            ),
            min_width="0",
        ),
        rx.box(_cell(row["type_code"], size="11px", color="#605e5c"), min_width="0"),
        rx.box(
            rx.badge(
                row["group"],
                color_scheme="gray",
                variant="soft",
                size="1",
                white_space="nowrap",
                overflow="hidden",
                text_overflow="ellipsis",
                max_width="100%",
                title=row["group"],
            ),
            min_width="0",
        ),
        rx.box(_cell(row["kind"], size="11px", color="#51627a"), min_width="0"),
        rx.box(
            rx.badge(
                row["source"],
                color_scheme="cyan",
                variant="soft",
                size="1",
                white_space="nowrap",
                overflow="hidden",
                text_overflow="ellipsis",
                max_width="100%",
                title=row["source"],
            ),
            min_width="0",
        ),
        columns=cols,
        gap="10px",
        align="center",
        padding_y="8px",
        padding_x="10px",
        border_bottom="1px solid #f3f2f1",
        width="100%",
    )


def _deps_components_table() -> rx.Component:
    cols = "1.6fr 2.4fr 1.2fr 0.6fr 1fr 1.2fr 1.2fr"

    return card(
        rx.hstack(
            rx.icon("boxes", color=PRIMARY, size=16),
            rx.text("Components In Solution", font_size="13px", font_weight="700", color="#201f1e"),
            rx.spacer(),
            rx.badge(State.deps_filtered_component_rows.length(), color_scheme="gray", variant="soft", size="1"),
            spacing="2",
            align="center",
            margin_bottom="10px",
            width="100%",
        ),
        rx.hstack(
            rx.input(
                placeholder="Filter by name, schema, type, code, group, kind, or source...",
                value=State.deps_component_query,
                on_change=State.set_deps_component_query,
                width="100%",
                size="2",
            ),
            rx.button(
                "Clear",
                variant="outline",
                size="2",
                on_click=State.set_deps_component_query(""),
            ),
            spacing="2",
            align="center",
            margin_bottom="10px",
            width="100%",
        ),
        rx.box(
            rx.grid(
                _deps_component_sortable_header("Name", "name"),
                _deps_component_sortable_header("Schema", "schema"),
                _deps_component_sortable_header("Type", "type"),
                _deps_component_sortable_header("Code", "type_code"),
                _deps_component_sortable_header("Group", "group"),
                _deps_component_sortable_header("Detected Kind", "kind"),
                _deps_component_sortable_header("Source", "source"),
                columns=cols,
                gap="10px",
                padding_y="8px",
                padding_x="10px",
                background="#f7faff",
                border_bottom="1px solid #e6edf8",
                width="100%",
                position="sticky",
                top="0",
                z_index="2",
            ),
            rx.foreach(State.deps_filtered_component_rows, _deps_component_row),
            width="100%",
            max_height="360px",
            overflow_x="auto",
            overflow_y="auto",
            border="1px solid #e6edf8",
            border_radius="10px",
            background="#ffffff",
        ),
        width="100%",
    )


def _deps_relations_table() -> rx.Component:
    return card(
        rx.hstack(
            rx.icon("table", color=PRIMARY, size=16),
            rx.text("Dependency Relations Table", font_size="13px", font_weight="700", color="#201f1e"),
            rx.spacer(),
            rx.badge(State.deps_filtered_relation_rows.length(), color_scheme="gray", variant="soft", size="1"),
            spacing="2",
            align="center",
            margin_bottom="10px",
            width="100%",
        ),
        rx.hstack(
            rx.input(
                placeholder="Filter by dependent, required, type, or source...",
                value=State.deps_relation_query,
                on_change=State.set_deps_relation_query,
                width="100%",
                size="2",
            ),
            rx.button(
                "Clear",
                variant="outline",
                size="2",
                on_click=State.set_deps_relation_query(""),
            ),
            spacing="2",
            align="center",
            margin_bottom="10px",
            width="100%",
        ),
        rx.box(
            rx.grid(
                _deps_sortable_header("Dependent", "dependent"),
                _deps_sortable_header("Type", "dependent_type"),
                _deps_sortable_header("Required", "required"),
                _deps_sortable_header("Type", "required_type"),
                _deps_sortable_header("Source", "source"),
                columns="2.2fr 1fr 2.2fr 1fr 1.4fr",
                gap="10px",
                padding_y="8px",
                padding_x="10px",
                background="#f7faff",
                border_bottom="1px solid #e6edf8",
                width="100%",
            ),
            rx.foreach(State.deps_filtered_relation_rows, _deps_relation_row),
            width="100%",
            max_height="420px",
            overflow_y="auto",
            border="1px solid #e6edf8",
            border_radius="10px",
            background="#ffffff",
        ),
        width="100%",
    )


def deps_panel() -> rx.Component:
    """Full-width dependency analysis panel for the Dependencies tab."""
    return rx.cond(
        State.deps_is_analyzing,
        rx.center(
            rx.vstack(
                rx.spinner(size="3", color=PRIMARY),
                rx.text(
                    "Analysing solution dependencies…",
                    font_size="13px",
                    color="#605e5c",
                ),
                spacing="3",
                align="center",
            ),
            padding_y="48px",
            width="100%",
        ),
        rx.cond(
            State.deps_error != "",
            rx.callout(
                State.deps_error,
                icon="triangle-alert",
                color_scheme="orange",
                margin_top="8px",
            ),
            rx.cond(
                State.has_deps,
                rx.vstack(
                    # ── Header card ───────────────────────────────────────
                    card(
                        rx.hstack(
                            rx.icon("network", color=PRIMARY, size=20),
                            rx.heading(
                                "Solution Dependency Map",
                                size="4",
                                color="#201f1e",
                            ),
                            spacing="2",
                            align="center",
                            margin_bottom="8px",
                        ),
                        rx.hstack(
                            rx.text("Diagram mode:", font_size="12px", font_weight="700", color="#51627a"),
                            _deps_mode_btn("aggregated", "Aggregated"),
                            _deps_mode_btn("detailed", "Detailed"),
                            spacing="2",
                            align="center",
                            margin_bottom="10px",
                        ),
                        rx.text(
                            "Components declared in this solution export, their types, "
                            "relationships, and any external dependencies that must be present "
                            "in the target environment before import.",
                            font_size="13px",
                            color="#605e5c",
                            line_height="1.55",
                        ),
                        width="100%",
                    ),
                    # ── Segments (markdown summary + Mermaid graph) ───────
                    rx.vstack(
                        rx.foreach(State.deps_visible_segments, _deps_segment_card),
                        width="100%",
                        spacing="4",
                    ),
                    rx.cond(
                        (State.deps_diagram_mode != "detailed") & State.has_deps_components,
                        _deps_components_table(),
                        rx.box(),
                    ),
                    rx.cond(
                        (State.deps_diagram_mode != "detailed") & State.has_deps_relations,
                        _deps_relations_table(),
                        rx.box(),
                    ),
                    width="100%",
                    spacing="4",
                    align="start",
                ),
                # ── Empty state ───────────────────────────────────────────
                rx.center(
                    rx.vstack(
                        rx.icon("network", size=36, color="#c8c6c4"),
                        rx.text(
                            "Upload a solution ZIP to analyse its component dependencies",
                            font_size="14px",
                            color="#a19f9d",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    padding_y="48px",
                    width="100%",
                ),
            ),
        ),
    )
