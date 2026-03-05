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
)
from web.state import State

BG = "#f3f2f1"
MAX_WIDTH = "860px"


def index() -> rx.Component:
    """Main (and only) page of the app."""
    return rx.vstack(
        navbar(),
        rx.box(
            rx.vstack(
                # ── Upload card ──────────────────────────────────────────
                rx.box(
                    rx.vstack(
                        rx.cond(
                            ~State.has_upload,
                            upload_area(),
                            rx.hstack(
                                rx.icon("file-archive", color="#0078d4", size=20),
                                rx.text(
                                    State.upload_filename,
                                    font_size="14px",
                                    font_weight="600",
                                    color="#201f1e",
                                ),
                                rx.cond(
                                    State.is_inspecting,
                                    rx.spinner(size="2"),
                                    rx.text("✓", color="#107c10", font_weight="700"),
                                ),
                                spacing="2",
                                align="center",
                                padding="16px",
                                border="1px solid #edebe9",
                                border_radius="8px",
                                width="100%",
                                background_color="#ffffff",
                            ),
                        ),
                        width="100%",
                    ),
                    width="100%",
                ),
                inspect_error_banner(),
                # ── Detection + inputs ────────────────────────────────────
                detected_info_panel(),
                name_inputs(),
                action_bar(),
                process_error_banner(),
                # ── Result ────────────────────────────────────────────────
                result_panel(),
                spacing="0",
                width="100%",
                align="start",
            ),
            max_width=MAX_WIDTH,
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
