"""Regression tests for visualizer topic graph Mermaid output."""

from __future__ import annotations

from toolkit.pp.visualizer import BotProfile, TopicConnection, _make_node_id, _render_topic_graph


def test_make_node_id_always_has_alpha_prefix():
    assert _make_node_id("123 Start") == "N_123Start"
    assert _make_node_id("") == "N_Unknown"


def test_render_topic_graph_uses_flowchart_and_omits_inline_init_directive():
    profile = BotProfile(
        display_name="Sample",
        topic_connections=[
            TopicConnection(source_display="Welcome", target_display="Escalate", condition="when needed")
        ],
    )

    graph_md = _render_topic_graph(profile)

    assert "```mermaid" in graph_md
    assert "flowchart TD" in graph_md
    assert "%%{init:" not in graph_md
    assert "N_Welcome" in graph_md
    assert "N_Escalate" in graph_md
