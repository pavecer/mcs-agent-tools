"""Mermaid diagram rendering support for the Reflex web UI.

Loads Mermaid.js from CDN and uses a MutationObserver to auto-render
any ``<pre class="mermaid">`` blocks that appear in the DOM.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

import re

import reflex as rx


def mermaid_script() -> rx.Component:
    """Return Reflex script components that load Mermaid.js and wire up auto-rendering."""
    return rx.fragment(
        rx.script(src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"),
        rx.script(
            """
            (function () {
                function initMermaid() {
                    if (typeof mermaid === 'undefined') {
                        setTimeout(initMermaid, 100);
                        return;
                    }

                    // Keep large graphs readable: render at natural SVG width and let
                    // the container scroll horizontally instead of shrinking everything.
                    if (!document.getElementById('pp-mermaid-viewport-style')) {
                        var style = document.createElement('style');
                        style.id = 'pp-mermaid-viewport-style';
                        style.textContent = `
                            pre.mermaid svg {
                                max-width: none !important;
                                width: auto !important;
                                min-width: 100%;
                                height: auto !important;
                            }
                            pre.mermaid {
                                display: flex;
                                justify-content: center;
                                align-items: flex-start;
                                overflow-x: auto;
                                overflow-y: auto;
                            }
                            pre.mermaid .label {
                                font-weight: 600;
                                letter-spacing: 0.01em;
                            }
                        `;
                        document.head.appendChild(style);
                    }

                    mermaid.initialize({ startOnLoad: false, theme: 'neutral' });

                    function renderUnprocessed() {
                        var els = document.querySelectorAll('pre.mermaid:not([data-processed])');
                        if (els.length > 0) {
                            mermaid.run({ nodes: els });
                        }
                    }

                    renderUnprocessed();

                    var observer = new MutationObserver(function (mutations) {
                        var hasAdded = mutations.some(function (m) { return m.addedNodes.length > 0; });
                        if (hasAdded) { renderUnprocessed(); }
                    });
                    observer.observe(document.body, { childList: true, subtree: true });
                }
                initMermaid();
            })();
            """
        ),
    )


def render_segment(segment: dict) -> rx.Component:
    """Render a single report segment — either Markdown prose or a Mermaid diagram."""

    def _split_table_row(line: str) -> list[str]:
        stripped = line.strip().strip("|")
        return [cell.strip() for cell in stripped.split("|")]

    def _is_table_divider(line: str) -> bool:
        cells = _split_table_row(line)
        if not cells:
            return False
        return all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)

    def _status_chip(value: str) -> rx.Component | None:
        normalized = value.strip().lower()
        if normalized == "":
            return None

        chip_map = {
            "active": ("green", "Active"),
            "inactive": ("amber", "Inactive"),
            "enabled": ("green", "Enabled"),
            "disabled": ("gray", "Disabled"),
            "true": ("green", "True"),
            "false": ("gray", "False"),
            "high": ("red", "High"),
            "medium": ("orange", "Medium"),
            "low": ("blue", "Low"),
            "missing resource": ("red", "Missing Resource"),
            "unknown": ("gray", "Unknown"),
        }
        if normalized in chip_map:
            scheme, text = chip_map[normalized]
            return rx.badge(text, color_scheme=scheme, variant="soft", size="1")

        if normalized.startswith("on") and len(normalized) <= 24 and normalized.isascii():
            return rx.badge(value, color_scheme="blue", variant="soft", size="1")

        return None

    def _styled_cell(value: str) -> rx.Component:
        chip = _status_chip(value)
        if chip is not None:
            return chip
        return rx.text(value if value else "-", font_size="12px", color="#2f425f", line_height="1.45")

    def _parse_table_blocks(markdown: str) -> list[dict]:
        lines = markdown.splitlines()
        blocks: list[dict] = []
        i = 0
        text_buffer: list[str] = []

        while i < len(lines):
            current = lines[i]
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            is_table_start = "|" in current and "|" in next_line and _is_table_divider(next_line)

            if is_table_start:
                if text_buffer:
                    blocks.append({"kind": "text", "content": "\n".join(text_buffer).strip()})
                    text_buffer = []

                table_lines = [current, next_line]
                i += 2
                while i < len(lines) and "|" in lines[i] and lines[i].strip() != "":
                    table_lines.append(lines[i])
                    i += 1

                header = _split_table_row(table_lines[0])
                rows: list[list[str]] = []
                for row_line in table_lines[2:]:
                    row = _split_table_row(row_line)
                    if len(row) < len(header):
                        row.extend([""] * (len(header) - len(row)))
                    rows.append(row[: len(header)])
                blocks.append({"kind": "table", "header": header, "rows": rows})
                continue

            text_buffer.append(current)
            i += 1

        if text_buffer:
            blocks.append({"kind": "text", "content": "\n".join(text_buffer).strip()})

        return blocks

    def _render_markdown_block(markdown: str) -> rx.Component:
        return rx.markdown(
            markdown,
            component_map={
                "h1": lambda text: rx.heading(text, size="5", margin_bottom="10px", color="#102548"),
                "h2": lambda text: rx.heading(
                    text, size="4", margin_top="18px", margin_bottom="8px", color="#102548", letter_spacing="-0.01em"
                ),
                "h3": lambda text: rx.heading(text, size="3", margin_top="14px", margin_bottom="6px", color="#2a3f63"),
                "p": lambda text: rx.text(text, font_size="14px", color="#2f425f", line_height="1.65"),
                "code": lambda text: rx.code(text, font_size="12px", background="#edf4ff", color="#1f3a63"),
            },
        )

    def _render_table_block(header: list[str], rows: list[list[str]]) -> rx.Component:
        col_template = f"repeat({max(len(header), 1)}, minmax(120px, 1fr))"
        return rx.box(
            rx.grid(
                rx.foreach(
                    header,
                    lambda h: rx.text(
                        h,
                        font_size="11px",
                        font_weight="700",
                        color="#4d6287",
                        letter_spacing="0.04em",
                        text_transform="uppercase",
                    ),
                ),
                columns=col_template,
                gap="10px",
                padding="10px 12px",
                background="#f4f8ff",
                border_bottom="1px solid #e3ecfa",
                width="100%",
            ),
            rx.vstack(
                rx.foreach(
                    rows,
                    lambda row: rx.grid(
                        rx.foreach(row, _styled_cell),
                        columns=col_template,
                        gap="10px",
                        padding="10px 12px",
                        width="100%",
                        border_bottom="1px solid #edf2fb",
                        _hover={"background": "#f9fbff"},
                    ),
                ),
                spacing="0",
                width="100%",
                align="start",
            ),
            border="1px solid #d7e2f2",
            border_radius="12px",
            overflow="hidden",
            background="#ffffff",
            box_shadow="0 8px 20px rgba(12, 33, 70, 0.06)",
            width="100%",
            margin_y="8px",
        )

    return rx.cond(
        segment["type"] == "mermaid",
        rx.box(
            rx.el.pre(segment["content"], class_name="mermaid"),
            width="100%",
            overflow_x="auto",
            padding="18px",
            background="linear-gradient(180deg, #f8fbff 0%, #f5f9ff 100%)",
            border="1px solid #d9e5f6",
            border_radius="14px",
            box_shadow="inset 0 1px 0 rgba(255,255,255,0.85)",
        ),
        rx.box(
            rx.vstack(
                rx.foreach(
                    _parse_table_blocks(segment["content"]),
                    lambda block: rx.cond(
                        block["kind"] == "table",
                        _render_table_block(block["header"], block["rows"]),
                        rx.cond(
                            block["content"] != "",
                            _render_markdown_block(block["content"]),
                            rx.box(),
                        ),
                    ),
                ),
                spacing="2",
                width="100%",
                align="start",
            ),
            width="100%",
            overflow_x="auto",
            padding="2px 2px 4px",
        ),
    )
