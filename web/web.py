"""Reflex page definitions and app setup."""

from __future__ import annotations

import reflex as rx

from web.components import (
    action_bar,
    detected_info_panel,
    inspect_error_banner,
    name_inputs,
    navbar,
    process_error_banner,
    result_panel,
    upload_area,
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
        rx.cond(
            ~State.has_upload,
            upload_area(),
            rx.box(),
        ),
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

def index() -> rx.Component:
    """Main page with a Rename / Visualize tab layout."""
    return rx.vstack(
        mermaid_script(),
        navbar(),
        rx.box(
            rx.vstack(
                # ── Tab bar ──────────────────────────────────────────────
                rx.box(
                    rx.hstack(
                        _tab_trigger("Rename", "refresh-cw", "rename"),
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
                # ── Tab content area ──────────────────────────────────────
                rx.box(
                    _file_bar(),
                    rx.cond(
                        State.active_tab == "rename",
                        _rename_tab(),
                        rx.cond(
                            State.active_tab == "visualize",
                            _visualize_tab(),
                            _validate_tab(),
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
            max_width=rx.cond(
                State.active_tab == "rename",
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
    )


app = rx.App(
    theme=rx.theme(appearance="light", accent_color="blue"),
)
app.add_page(index, route="/", title="PP Agent Renamer")
