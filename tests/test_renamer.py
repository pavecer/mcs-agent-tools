"""Unit tests for core renaming utilities."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from renamer import derive_schema_name, derive_solution_unique_name, safe_extractall, sanitize_schema_name
from models import RenameConfig, SolutionInfo


# ── sanitize_schema_name ──────────────────────────────────────────────────────


def test_sanitize_schema_name_basic():
    assert sanitize_schema_name("My New Bot") == "my_new_bot"


def test_sanitize_schema_name_special_chars():
    assert sanitize_schema_name("My Bot (Copy)!") == "my_bot_copy"


def test_sanitize_schema_name_leading_trailing_underscores():
    result = sanitize_schema_name("  --My Bot--  ")
    assert not result.startswith("_")
    assert not result.endswith("_")


def test_sanitize_schema_name_max_length():
    long_name = "a" * 200
    assert len(sanitize_schema_name(long_name)) <= 50


# ── derive_schema_name ────────────────────────────────────────────────────────


def test_derive_schema_name_preserves_prefix():
    result = derive_schema_name("copilots_new_myoldbot", "My New Bot")
    assert result.startswith("copilots_new_")
    assert "my_new_bot" in result


def test_derive_schema_name_single_part_schema():
    result = derive_schema_name("copilots_mybot", "Renamed Bot")
    assert result.startswith("copilots_")


# ── derive_solution_unique_name ───────────────────────────────────────────────


def test_derive_solution_unique_name_pascal_case():
    assert derive_solution_unique_name("My New Bot") == "MyNewBot"


def test_derive_solution_unique_name_strips_specials():
    assert derive_solution_unique_name("My Bot (Copy)") == "MyBotCopy"


def test_derive_solution_unique_name_starts_with_letter():
    result = derive_solution_unique_name("123 Bot")
    assert result[0].isalpha(), f"Expected first char to be a letter, got '{result[0]}'"


def test_derive_solution_unique_name_empty():
    assert derive_solution_unique_name("") == ""


# ── safe_extractall ───────────────────────────────────────────────────────────


def test_safe_extractall_rejects_path_traversal(tmp_path: Path):
    """safe_extractall must raise ValueError for entries that escape the dest dir."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("../evil.txt", "malicious content")
    zip_buf.seek(0)
    dest = tmp_path / "dest"
    dest.mkdir()
    with zipfile.ZipFile(zip_buf) as zf:
        with pytest.raises(ValueError, match="Rejected unsafe ZIP entry"):
            safe_extractall(zf, dest)


def test_safe_extractall_allows_normal_entries(tmp_path: Path):
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("solution.xml", "<root/>")
        zf.writestr("bots/mybot/bot.xml", "<bot/>")
    zip_buf.seek(0)
    dest = tmp_path / "dest"
    dest.mkdir()
    with zipfile.ZipFile(zip_buf) as zf:
        safe_extractall(zf, dest)
    assert (dest / "solution.xml").exists()
    assert (dest / "bots" / "mybot" / "bot.xml").exists()


# ── RenameConfig validation ───────────────────────────────────────────────────


def test_rename_config_rejects_blank_agent_name(tmp_path: Path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RenameConfig(
            source_path=tmp_path,
            new_agent_name="   ",
            new_solution_name="ValidName",
            output_path=tmp_path / "out.zip",
        )


def test_rename_config_rejects_invalid_solution_name(tmp_path: Path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="must start with a letter"):
        RenameConfig(
            source_path=tmp_path,
            new_agent_name="Valid Agent",
            new_solution_name="1InvalidStart",
            output_path=tmp_path / "out.zip",
        )


def test_rename_config_rejects_solution_name_with_spaces(tmp_path: Path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RenameConfig(
            source_path=tmp_path,
            new_agent_name="Valid Agent",
            new_solution_name="Has Spaces",
            output_path=tmp_path / "out.zip",
        )


def test_rename_config_rejects_invalid_schema_name(tmp_path: Path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="lowercase"):
        RenameConfig(
            source_path=tmp_path,
            new_agent_name="Valid Agent",
            new_solution_name="ValidSolution",
            new_bot_schema_name="HasUpperCase",
            output_path=tmp_path / "out.zip",
        )


# ── SolutionInfo ──────────────────────────────────────────────────────────────


def test_solution_info_defaults():
    info = SolutionInfo(
        bot_schema_name="copilots_new_mybot",
        bot_display_name="My Bot",
        solution_unique_name="MySolution",
        solution_display_name="My Solution",
    )
    assert info.botcomponent_folders == []
