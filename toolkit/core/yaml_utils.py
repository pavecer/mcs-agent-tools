"""Shared YAML preprocessing helpers for Power Platform exports."""

from __future__ import annotations

import re


def sanitize_yaml(text: str) -> str:
    """Fix common Power Platform YAML quirks before parsing with PyYAML."""
    text = text.replace("\t", "    ")
    text = re.sub(r"^(\s*)(@[a-zA-Z0-9_.]+)(\s*:)", r'\1"\2"\3', text, flags=re.MULTILINE)
    text = re.sub(
        r"(:\s+)(@[^\n]+)$",
        lambda m: m.group(1) + '"' + m.group(2) + '"',
        text,
        flags=re.MULTILINE,
    )
    return text
