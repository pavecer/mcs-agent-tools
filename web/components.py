"""Reusable UI components for the Agent Renamer web app."""

from __future__ import annotations

import reflex as rx

from web.state import State


# ── Colour palette ────────────────────────────────────────────────────────────
PRIMARY = "#0078d4"       # Microsoft blue
SUCCESS = "#107c10"       # Microsoft green
WARNING = "#797673"       # muted amber label
ERROR_COLOR = "#a4262c"   # Microsoft red
BG = "#f3f2f1"            # Fabric neutral light
CARD_BG = "#ffffff"


# ── Building blocks ───────────────────────────────────────────────────────────

def card(*children, **props) -> rx.Component:
    """White card with shadow."""
    return rx.box(
        *children,
        background_color=CARD_BG,
        border_radius="8px",
        box_shadow="0 2px 8px rgba(0,0,0,.12)",
        padding="24px",
        **props,
    )


def section_heading(text: str) -> rx.Component:
    return rx.heading(text, size="4", margin_bottom="12px", color="#201f1e")


def label(text: str) -> rx.Component:
    return rx.text(text, font_size="13px", font_weight="600", color="#605e5c", margin_bottom="4px")


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
        color=PRIMARY,
        letter_spacing="0.08em",
        margin_bottom="6px",
    )

# ── Upload area ───────────────────────────────────────────────────────────────

def upload_area() -> rx.Component:
    return rx.upload(
        rx.vstack(
            rx.icon("upload-cloud", color=PRIMARY, size=40),
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
        accept={".zip": ["application/zip", "application/x-zip-compressed"]},
        multiple=False,
        border=f"2px dashed {PRIMARY}",
        border_radius="8px",
        padding="40px",
        cursor="pointer",
        width="100%",
        on_drop=State.handle_upload(rx.upload_files(upload_id="solution_upload")),
        _hover={"background_color": "#deecf9"},
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


# ── Editable current-names panel ────────────────────────────────────────────

def current_names_panel() -> rx.Component:
    """Editable fields for the current agent / solution names.

    Pre-filled from auto-detection; user can correct them before renaming.
    """
    return rx.cond(
        State.has_detection,
        card(
            section_heading("Current Names"),
            rx.text(
                "Auto-detected from the uploaded ZIP. Correct if needed before renaming.",
                font_size="13px",
                color="#605e5c",
                margin_bottom="12px",
            ),
            rx.vstack(
                # Current agent display name
                rx.box(
                    label("Current agent display name"),
                    rx.input(
                        placeholder="Detected agent name",
                        value=State.current_agent_name,
                        on_change=State.set_current_agent_name,
                        size="3",
                        width="100%",
                    ),
                    width="100%",
                ),
                # Current solution unique name
                rx.box(
                    label("Current solution unique name"),
                    rx.input(
                        placeholder="Detected solution name",
                        value=State.current_solution_name,
                        on_change=State.set_current_solution_name,
                        size="3",
                        width="100%",
                    ),
                    width="100%",
                ),
                spacing="4",
                width="100%",
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
                "Enter the new names for the renamed copy. "
                "Technical identifiers are derived automatically.",
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
                        placeholder="e.g. ACME Legal Bot",
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
                        placeholder="e.g. ACME Legal Bot",
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
                border_radius="4px",
                _hover={"background_color": "#006cbf"},
                _disabled={"opacity": "0.5", "cursor": "not-allowed"},
            ),
            rx.button(
                "Reset",
                on_click=State.clear_all,
                variant="outline",
                size="3",
                border_radius="4px",
            ),
            spacing="3",
            margin_top="16px",
        ),
        rx.box(),
    )


# ── Error / success banners ───────────────────────────────────────────────────

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
                State.result_warnings.length() > 0,
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
            # Download button
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
                margin_top="16px",
                _hover={"background_color": "#0b6a0b"},
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
                    "Power Platform Agent Renamer",
                    size="5",
                    color="white",
                    font_weight="600",
                ),
                spacing="3",
                align="center",
            ),
            rx.text(
                "Rename Copilot Studio solution exports for re-import",
                color="rgba(255,255,255,0.7)",
                font_size="13px",
                display=["none", "none", "block"],
            ),
            justify="between",
            align="center",
            width="100%",
        ),
        background_color=PRIMARY,
        padding_x="24px",
        padding_y="14px",
        width="100%",
    )
