"""Reusable UI components for the Agent Renamer web app."""

from __future__ import annotations

import reflex as rx

from web.mermaid import render_segment
from web.state import State


# ── Colour palette ────────────────────────────────────────────────────────────
PRIMARY = "#0078d4"       # Microsoft blue
SUCCESS = "#107c10"       # Microsoft green
WARNING = "#797673"       # muted amber label
WARNING_AMBER = "#c7921e" # amber for validation badges
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
                    "Power Platform Agent Toolkit",
                    size="5",
                    color="white",
                    font_weight="600",
                ),
                spacing="3",
                align="center",
            ),
            rx.text(
                "Rename · Visualise · Validate — Copilot Studio solution exports",
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
                            "Upload a solution ZIP to see the visualization",
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
                                        State.validation_instructions_length.to_string()
                                        + " chars",
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
                                _validation_summary_badge(
                                    State.validation_pass_count, "passed", "#107c10"
                                ),
                                rx.divider(orientation="vertical", height="32px"),
                                _validation_summary_badge(
                                    State.validation_warn_count, "warnings", "#c7921e"
                                ),
                                rx.divider(orientation="vertical", height="32px"),
                                _validation_summary_badge(
                                    State.validation_fail_count, "failed", "#a4262c"
                                ),
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
                                            "Hide Best Practices for "
                                            + State.validation_model_display,
                                            "Show Best Practices for "
                                            + State.validation_model_display,
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
                                            "code": lambda text: rx.code(
                                                text, font_size="12px"
                                            ),
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
                            "Upload a solution ZIP to validate the agent's instructions",
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
