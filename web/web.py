"""Reflex page definitions and app setup."""

from __future__ import annotations

import reflex as rx

from web.components import (
    action_bar,
    detected_info_panel,
    inspect_error_banner,
    login_form,
    mcs_analyse_panel,
    name_inputs,
    navbar,
    no_agent_warning_banner,
    process_error_banner,
    result_panel,
    unified_upload_area,
    validation_panel,
    visualization_panel,
)
from web.mermaid import mermaid_script
from web.state import State

BG = "#f3f2f1"
MAX_WIDTH = "920px"
VIZ_MAX_WIDTH = "1200px"


# ── Shared: file status bar shown at top of both tabs ────────────────────────


def _file_bar() -> rx.Component:
    return rx.cond(
        State.has_upload,
        rx.hstack(
            rx.icon("file-archive", color="#0078d4", size=18),
            rx.text(
                State.upload_filename,
                font_size="13px",
                font_weight="600",
                color="#201f1e",
            ),
            rx.cond(
                State.is_inspecting,
                rx.spinner(size="2"),
                rx.badge("Ready", color_scheme="green", variant="soft"),
            ),
            rx.spacer(),
            rx.button(
                rx.icon("x", size=14),
                on_click=State.clear_all,
                variant="ghost",
                size="1",
                color="#605e5c",
                cursor="pointer",
                _hover={"color": "#a4262c"},
            ),
            spacing="2",
            align="center",
            padding="10px 16px",
            background="#ffffff",
            border="1px solid #edebe9",
            border_radius="8px",
            width="100%",
        ),
        rx.box(),
    )


# ── Tab trigger helper ────────────────────────────────────────────────────────


def _tab_trigger(label: str, icon: str, tab_id: str) -> rx.Component:
    """Custom styled tab button."""
    active = State.active_tab == tab_id
    return rx.box(
        rx.hstack(
            rx.icon(icon, size=16),
            rx.text(label, font_size="14px", font_weight="600"),
            spacing="2",
            align="center",
        ),
        on_click=State.set_active_tab(tab_id),
        padding="10px 20px",
        cursor="pointer",
        border_bottom=rx.cond(active, "2px solid #0078d4", "2px solid transparent"),
        color=rx.cond(active, "#0078d4", "#605e5c"),
        _hover={"color": "#0078d4"},
        transition="all 0.15s ease",
        user_select="none",
    )


# ── Rename tab content ────────────────────────────────────────────────────────


def _rename_tab() -> rx.Component:
    return rx.vstack(
        inspect_error_banner(),
        detected_info_panel(),
        name_inputs(),
        action_bar(),
        process_error_banner(),
        result_panel(),
        spacing="0",
        width="100%",
        align="start",
    )


# ── Visualize tab content ─────────────────────────────────────────────────────


def _visualize_tab() -> rx.Component:
    return rx.box(
        visualization_panel(),
        width="100%",
    )


# ── Validate tab content ──────────────────────────────────────────────────


def _validate_tab() -> rx.Component:
    return rx.box(
        validation_panel(),
        width="100%",
    )


# ── Analyse tab content ───────────────────────────────────────────────────────


def _analyse_tab() -> rx.Component:
    return rx.box(
        mcs_analyse_panel(),
        width="100%",
    )


def index() -> rx.Component:
    """Main page with a unified upload zone and context-sensitive tab layout."""
    return rx.vstack(
        mermaid_script(),
        navbar(),
        rx.box(
            rx.cond(
                ~State.has_upload,
                # ── No file yet: unified drop zone ────────────────────────
                rx.box(
                    rx.vstack(
                        rx.heading(
                            "Get Started",
                            size="4",
                            margin_bottom="4px",
                            color="#201f1e",
                        ),
                        rx.text(
                            "Upload a Power Platform solution ZIP to rename, visualise and validate, "
                            "or drop a Copilot Studio snapshot ZIP for deep agent analysis.",
                            font_size="13px",
                            color="#605e5c",
                            margin_bottom="8px",
                        ),
                        unified_upload_area(),
                        inspect_error_banner(),
                        spacing="4",
                        width="100%",
                        align="start",
                    ),
                    background="#ffffff",
                    border_radius="8px",
                    box_shadow="0 2px 8px rgba(0,0,0,.08)",
                    padding="24px",
                    width="100%",
                ),
                # ── File uploaded: conditional tabs + content ─────────────
                rx.vstack(
                    # Tab bar – first tab adapted to ZIP type
                    rx.box(
                        rx.hstack(
                            rx.cond(
                                State.is_solution_zip,
                                _tab_trigger("Rename", "refresh-cw", "rename"),
                                _tab_trigger("Analyse", "search", "analyse"),
                            ),
                            _tab_trigger("Visualize", "git-branch", "visualize"),
                            _tab_trigger("Validate", "shield-check", "validate"),
                            spacing="0",
                            border_bottom="1px solid #edebe9",
                            width="100%",
                        ),
                        width="100%",
                        background="#ffffff",
                        border_radius="8px 8px 0 0",
                        box_shadow="0 2px 8px rgba(0,0,0,.08)",
                    ),
                    # Content area
                    rx.box(
                        _file_bar(),
                        inspect_error_banner(),
                        no_agent_warning_banner(),
                        rx.cond(
                            State.active_tab == "rename",
                            _rename_tab(),
                            rx.cond(
                                State.active_tab == "visualize",
                                _visualize_tab(),
                                rx.cond(
                                    State.active_tab == "validate",
                                    _validate_tab(),
                                    _analyse_tab(),
                                ),
                            ),
                        ),
                        padding="20px 24px 28px",
                        background="#ffffff",
                        border_radius="0 0 8px 8px",
                        box_shadow="0 2px 8px rgba(0,0,0,.08)",
                        width="100%",
                    ),
                    spacing="0",
                    width="100%",
                    align="start",
                ),
            ),
            max_width=rx.cond(
                ~State.has_upload | (State.active_tab == "rename"),
                MAX_WIDTH,
                VIZ_MAX_WIDTH,
            ),
            margin_x="auto",
            padding_x="16px",
            padding_y="24px",
            width="100%",
        ),
        background_color=BG,
        min_height="100vh",
        width="100%",
        spacing="0",
        align="start",
        on_mount=State.check_auth,
    )


def login_page() -> rx.Component:
    """Login page at /login."""
    return login_form()


app = rx.App(
    theme=rx.theme(appearance="light", accent_color="blue"),
)
app.add_page(index, route="/", title="PP Agent Toolkit")
app.add_page(login_page, route="/login", title="Sign in — PP Agent Toolkit", on_load=State.check_already_authed)
