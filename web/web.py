"""Reflex page definitions and app setup."""

from __future__ import annotations

import reflex as rx

from web.components import (
    action_bar,
    deps_panel,
    detected_info_panel,
    evals_panel,
    feedback_footer,
    inspect_error_banner,
    login_form,
    mcs_analyse_panel,
    name_inputs,
    navbar,
    no_agent_warning_banner,
    process_error_banner,
    result_panel,
    solution_check_panel,
    transcript_input_choice_area,
    tutorial_dialog,
    unified_upload_area,
    validation_panel,
    visualization_panel,
)
from web.mermaid import mermaid_script
from web.state import State

BG_BLUE_RADIAL = "radial-gradient(1200px 500px at 15% -5%, #d8e8ff 0%, rgba(216, 232, 255, 0) 60%)"
BG_MINT_RADIAL = "radial-gradient(1000px 450px at 90% 0%, #d7fff0 0%, rgba(215, 255, 240, 0) 55%)"
BG_BASE_COLOR = "#eef3fb"
BG = f"{BG_BLUE_RADIAL}, {BG_MINT_RADIAL}, {BG_BASE_COLOR}"
MAX_WIDTH = "980px"
VIZ_MAX_WIDTH = "1280px"


# ── Shared: file status bar shown at top of both tabs ────────────────────────


def _file_bar() -> rx.Component:
    return rx.cond(
        State.has_upload,
        rx.hstack(
            rx.cond(
                State.mcs_source == "transcript",
                rx.icon("file-json", color="#0078d4", size=18),
                rx.icon("file-archive", color="#0078d4", size=18),
            ),
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
            padding="12px 16px",
            background="#f7faff",
            border="1px solid #d7e2f2",
            border_radius="12px",
            box_shadow="inset 0 1px 0 rgba(255,255,255,0.8)",
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
        padding="10px 16px",
        cursor="pointer",
        border_radius="10px 10px 0 0",
        border_bottom=rx.cond(active, "2px solid #0a66ff", "2px solid transparent"),
        background=rx.cond(active, "#eef4ff", "transparent"),
        color=rx.cond(active, "#0a66ff", "#51627a"),
        _hover={"color": "#0a66ff", "background": "#f3f8ff"},
        transition="all 0.18s ease",
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


# ── Check tab content ─────────────────────────────────────────────────────────


def _check_tab() -> rx.Component:
    return rx.box(
        solution_check_panel(),
        width="100%",
    )


# ── Analyse tab content ───────────────────────────────────────────────────────


def _analyse_tab() -> rx.Component:
    return rx.box(
        mcs_analyse_panel(),
        width="100%",
    )


# ── Evals tab content ──────────────────────────────────────────────────


def _evals_tab() -> rx.Component:
    return rx.box(
        evals_panel(),
        width="100%",
    )


# ── Dependencies tab content ────────────────────────────────────────────


def _deps_tab() -> rx.Component:
    return rx.box(
        deps_panel(),
        width="100%",
    )


def index() -> rx.Component:
    """Main page with a unified upload zone and context-sensitive tab layout."""
    return rx.vstack(
        mermaid_script(),
        tutorial_dialog(),
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
                            "Choose your transcript analysis input first, then optionally upload a ZIP for solution workflows.",
                            font_size="13px",
                            color="#605e5c",
                            margin_bottom="8px",
                        ),
                        transcript_input_choice_area(),
                        rx.hstack(
                            rx.divider(flex="1"),
                            rx.text("or", font_size="12px", color="#605e5c", padding_x="12px"),
                            rx.divider(flex="1"),
                            align="center",
                            width="100%",
                            margin_y="4px",
                        ),
                        rx.text(
                            "Upload a ZIP export",
                            font_size="13px",
                            font_weight="600",
                            color="#201f1e",
                        ),
                        rx.text(
                            "Use solution or snapshot ZIPs for rename, dependency, visual, and deep agent analysis workflows.",
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
                    border="1px solid #d7e2f2",
                    border_radius="16px",
                    box_shadow="0 16px 40px rgba(12, 33, 70, 0.10)",
                    padding="26px",
                    width="100%",
                ),
                # ── File uploaded: conditional tabs + content ─────────────
                rx.vstack(
                    # Tab bar – first tab adapted to ZIP type
                    rx.box(
                        rx.hstack(
                            rx.cond(
                                State.is_solution_zip,
                                rx.box(),
                                _tab_trigger("Analyse", "search", "analyse"),
                            ),
                            rx.cond(
                                State.is_snapshot_zip | State.is_agent_solution_zip,
                                _tab_trigger("Visualize", "git-branch", "visualize"),
                                rx.box(),
                            ),
                            rx.cond(
                                State.is_snapshot_zip | State.is_agent_solution_zip,
                                _tab_trigger("Validate", "shield-check", "validate"),
                                rx.box(),
                            ),
                            rx.cond(
                                State.is_agent_solution_zip,
                                _tab_trigger("Check", "scan-search", "check"),
                                rx.box(),
                            ),
                            rx.cond(
                                State.is_agent_solution_zip,
                                _tab_trigger("Evals", "flask-conical", "evals"),
                                rx.box(),
                            ),
                            rx.cond(
                                State.is_solution_zip,
                                _tab_trigger("Dependencies", "network", "deps"),
                                rx.box(),
                            ),
                            rx.cond(
                                State.is_agent_solution_zip,
                                _tab_trigger("Rename", "refresh-cw", "rename"),
                                rx.box(),
                            ),
                            spacing="0",
                            border_bottom="1px solid #edebe9",
                            padding_x="8px",
                            width="100%",
                        ),
                        width="100%",
                        background="#ffffff",
                        border="1px solid #d7e2f2",
                        border_bottom="0",
                        border_radius="16px 16px 0 0",
                        box_shadow="0 16px 40px rgba(12, 33, 70, 0.10)",
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
                                    rx.cond(
                                        State.active_tab == "check",
                                        _check_tab(),
                                        rx.cond(
                                            State.active_tab == "evals",
                                            _evals_tab(),
                                            rx.cond(
                                                State.active_tab == "deps",
                                                _deps_tab(),
                                                _analyse_tab(),
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                        padding="20px 22px 28px",
                        background="#ffffff",
                        border="1px solid #d7e2f2",
                        border_top="0",
                        border_radius="0 0 16px 16px",
                        box_shadow="0 16px 40px rgba(12, 33, 70, 0.10)",
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
            padding_y="28px",
            width="100%",
        ),
        feedback_footer(),
        background=BG,
        font_family="Manrope, Segoe UI, sans-serif",
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
    theme=rx.theme(appearance="light", accent_color="cyan"),
)
app.add_page(index, route="/", title="PP Agent Toolkit")
app.add_page(login_page, route="/login", title="Sign in — PP Agent Toolkit", on_load=State.check_already_authed)
