"""Mermaid diagram rendering support for the Reflex web UI.

Loads Mermaid.js — preferring a locally-bundled copy so that the app works
in environments where external CDNs are blocked (e.g. Azure Container Apps).
Falls back to the jsDelivr CDN only if the local asset is unavailable (handy
for local ``reflex run`` without running the asset-download step).

The local copy lives at ``assets/external/mermaid.min.js`` which is bundled
into the Docker image at build time (see ``Dockerfile``).  The path is
gitignored so the 3 MB file is never committed.

A MutationObserver auto-renders any ``<pre class="mermaid">`` blocks that
appear in the DOM after the initial page load.

Adapted from github.com/Roelzz/mcs-agent-analyser (MIT licence).
"""

from __future__ import annotations

import reflex as rx

_LOCAL_MERMAID = "/external/mermaid.min.js"
_CDN_MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"


def mermaid_script() -> rx.Component:
    """Return Reflex script components that load Mermaid.js and wire up auto-rendering."""
    return rx.script(
        f"""
        (function () {{
            var _LOCAL = "{_LOCAL_MERMAID}";
            var _CDN   = "{_CDN_MERMAID}";

            function initMermaid() {{
                if (typeof mermaid === 'undefined') {{
                    setTimeout(initMermaid, 100);
                    return;
                }}

                // Keep large graphs readable: render at natural SVG width and let
                // the container scroll horizontally instead of shrinking everything.
                if (!document.getElementById('pp-mermaid-viewport-style')) {{
                    var style = document.createElement('style');
                    style.id = 'pp-mermaid-viewport-style';
                    style.textContent = `
                        pre.mermaid svg {{
                            max-width: none !important;
                            width: auto !important;
                            min-width: 100%;
                            height: auto !important;
                        }}
                        pre.mermaid {{
                            display: flex;
                            justify-content: center;
                            align-items: flex-start;
                            overflow-x: auto;
                            overflow-y: auto;
                        }}
                        pre.mermaid .label {{
                            font-weight: 600;
                            letter-spacing: 0.01em;
                        }}
                    `;
                    document.head.appendChild(style);
                }}

                mermaid.initialize({{ startOnLoad: false, theme: 'neutral' }});

                function renderUnprocessed() {{
                    var els = document.querySelectorAll('pre.mermaid:not([data-processed])');
                    if (els.length > 0) {{
                        mermaid.run({{ nodes: els }});
                    }}
                }}

                renderUnprocessed();

                var observer = new MutationObserver(function (mutations) {{
                    var hasAdded = mutations.some(function (m) {{ return m.addedNodes.length > 0; }});
                    if (hasAdded) {{ renderUnprocessed(); }}
                }});
                observer.observe(document.body, {{ childList: true, subtree: true }});
            }}

            // Load local asset first only when it is truly a JavaScript file.
            // In dev, missing static assets can be rewritten to index.html (200 text/html),
            // which would otherwise trigger "Unexpected token '<'" in the browser.
            function loadScript(src, onLoad, onError) {{
                var s = document.createElement('script');
                s.src = src;
                s.onload = onLoad;
                s.onerror = onError;
                document.head.appendChild(s);
            }}

            function loadCdnFallback() {{
                loadScript(_CDN, initMermaid, function () {{
                    console.error('[mermaid] Failed to load Mermaid.js from both local and CDN.');
                }});
            }}

            function looksLikeJavascriptContentType(contentType) {{
                var ct = (contentType || '').toLowerCase();
                return ct.includes('javascript') || ct.includes('ecmascript') || ct.includes('x-javascript');
            }}

            fetch(_LOCAL, {{ method: 'HEAD', cache: 'no-store' }})
                .then(function (response) {{
                    var contentType = response.headers.get('content-type') || '';
                    if (response.ok && looksLikeJavascriptContentType(contentType)) {{
                        loadScript(_LOCAL, initMermaid, loadCdnFallback);
                    }} else {{
                        loadCdnFallback();
                    }}
                }})
                .catch(function () {{
                    loadCdnFallback();
                }});
        }})();
        """
    )


def render_segment(segment: dict) -> rx.Component:
    """Render a single report segment — Markdown prose, Mermaid diagram, or raw SVG."""

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
        rx.cond(
            segment["type"] == "svg",
            rx.box(
                rx.html(segment["content"]),
                width="100%",
                overflow_x="auto",
                padding="18px",
                background="linear-gradient(180deg, #f8fbff 0%, #f5f9ff 100%)",
                border="1px solid #d9e5f6",
                border_radius="14px",
                box_shadow="inset 0 1px 0 rgba(255,255,255,0.85)",
            ),
        rx.box(
            rx.markdown(
                segment["content"],
                component_map={
                    "h1": lambda text: rx.heading(text, size="5", margin_bottom="10px", color="#102548"),
                    "h2": lambda text: rx.heading(
                        text,
                        size="4",
                        margin_top="18px",
                        margin_bottom="8px",
                        color="#102548",
                        letter_spacing="-0.01em",
                    ),
                    "h3": lambda text: rx.heading(
                        text, size="3", margin_top="14px", margin_bottom="6px", color="#2a3f63"
                    ),
                    "p": lambda text: rx.text(text, font_size="14px", color="#2f425f", line_height="1.65"),
                    "blockquote": lambda text: rx.box(
                        text,
                        background="linear-gradient(180deg, #f7fbff 0%, #f4f9ff 100%)",
                        border="1px solid #dce8f7",
                        border_left_width="4px",
                        border_left_style="solid",
                        border_left_color="#0a66ff",
                        border_radius="0 12px 12px 0",
                        padding="14px 16px",
                        margin_y="10px",
                        box_shadow="0 8px 18px rgba(12, 33, 70, 0.05)",
                        width="100%",
                    ),
                    "code": lambda text: rx.code(text, font_size="12px", background="#edf4ff", color="#1f3a63"),
                    "table": lambda text: rx.box(
                        rx.el.table(
                            text,
                            style={
                                "width": "100%",
                                "border-collapse": "collapse",
                                "table-layout": "auto",
                            },
                        ),
                        width="100%",
                        overflow_x="auto",
                        border="1px solid #d7e2f2",
                        border_radius="12px",
                        background="#ffffff",
                        box_shadow="0 8px 20px rgba(12, 33, 70, 0.06)",
                        margin_y="8px",
                    ),
                    "thead": lambda text: rx.el.thead(
                        text,
                        style={
                            "background": "#f4f8ff",
                            "border-bottom": "1px solid #e3ecfa",
                        },
                    ),
                    "tbody": lambda text: rx.el.tbody(text),
                    "tr": lambda text: rx.el.tr(
                        text,
                        style={"border-bottom": "1px solid #edf2fb"},
                        _hover={"background": "#f9fbff"},
                    ),
                    "th": lambda text: rx.el.th(
                        text,
                        style={
                            "padding": "10px 12px",
                            "font-size": "11px",
                            "font-weight": "700",
                            "color": "#4d6287",
                            "letter-spacing": "0.04em",
                            "text-transform": "uppercase",
                            "text-align": "left",
                            "vertical-align": "top",
                        },
                    ),
                    "td": lambda text: rx.el.td(
                        text,
                        style={
                            "padding": "10px 12px",
                            "font-size": "12px",
                            "color": "#2f425f",
                            "line-height": "1.45",
                            "vertical-align": "top",
                        },
                    ),
                },
            ),
            width="100%",
            overflow_x="auto",
            padding="2px 2px 4px",
        ),
        ),
    )
