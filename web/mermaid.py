"""Mermaid diagram rendering support for the Reflex web UI.

Loads Mermaid.js from CDN and uses a MutationObserver to auto-render
any ``<pre class="mermaid">`` blocks that appear in the DOM.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

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
    return rx.cond(
        segment["type"] == "mermaid",
        rx.box(
            rx.el.pre(segment["content"], class_name="mermaid"),
            width="100%",
            overflow_x="auto",
            padding="22px",
            background="#f7fbff",
            border="1px solid #d7e2f2",
            border_radius="14px",
            box_shadow="inset 0 1px 0 rgba(255,255,255,0.85)",
            margin_y="4px",
        ),
        rx.box(
            rx.markdown(
                segment["content"],
                component_map={
                    "h1": lambda text: rx.heading(text, size="6", margin_bottom="10px", color="#102548"),
                    "h2": lambda text: rx.heading(
                        text, size="4", margin_top="18px", margin_bottom="8px", color="#102548"
                    ),
                    "h3": lambda text: rx.heading(
                        text, size="3", margin_top="14px", margin_bottom="6px", color="#2a3f63"
                    ),
                    "p": lambda text: rx.text(text, font_size="13px", color="#2f425f", line_height="1.65"),
                    "code": lambda text: rx.code(text, font_size="12px", background="#ecf3ff"),
                },
            ),
            width="100%",
            overflow_x="auto",
            padding="2px 2px 6px",
        ),
    )
