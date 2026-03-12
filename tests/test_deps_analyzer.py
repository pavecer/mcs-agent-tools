"""Tests for dependency analyzer formatting helpers."""

from __future__ import annotations

from deps_analyzer import _truncate_middle


def test_truncate_middle_keeps_short_text_unchanged():
    assert _truncate_middle("short", 10) == "short"


def test_truncate_middle_compacts_long_text_with_ellipsis():
    value = "msdyn_employeeeselfservicetemplateconfig_long_component_name"
    out = _truncate_middle(value, 20)

    assert len(out) == 20
    assert "…" in out
    assert out.startswith("msdyn_emp")
    assert out.endswith("t_name")
