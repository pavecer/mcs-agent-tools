"""Pydantic models for the Power Platform Agent Renamer."""

from pathlib import Path
from pydantic import BaseModel, field_validator
import re


class RenameConfig(BaseModel):
    """Configuration for a solution rename operation."""

    source_path: Path
    new_agent_name: str
    new_solution_name: str
    new_bot_schema_name: str | None = None  # auto-derived from new_agent_name if not set
    output_path: Path
    new_solution_display_name: str | None = None  # human-readable solution name for solution.xml
    # Optional user-provided overrides for the *current* names (corrects bad auto-detection)
    old_agent_name_override: str | None = None
    old_solution_name_override: str | None = None

    @field_validator("new_agent_name", "new_solution_name")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("new_solution_name")
    @classmethod
    def solution_name_valid(cls, v: str) -> str:
        """Solution unique names must be alphanumeric (no spaces, hyphens only)."""
        if not re.match(r'^[A-Za-z][A-Za-z0-9_]{0,99}$', v):
            raise ValueError(
                "Solution unique name must start with a letter and contain only "
                "letters, digits, and underscores (max 100 characters)."
            )
        return v

    @field_validator("new_bot_schema_name")
    @classmethod
    def schema_name_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r'^[a-z][a-z0-9_]{0,99}$', v):
            raise ValueError(
                "Bot schema name must be lowercase, start with a letter, and contain "
                "only lowercase letters, digits, and underscores (max 100 characters)."
            )
        return v


class SolutionInfo(BaseModel):
    """Metadata detected from an existing solution export."""

    bot_schema_name: str
    bot_display_name: str
    solution_unique_name: str
    solution_display_name: str
    botcomponent_folders: list[str] = []


class RenameResult(BaseModel):
    """Result of a completed rename operation."""

    old_bot_schema: str
    new_bot_schema: str
    old_solution_name: str
    new_solution_name: str
    old_agent_name: str
    new_agent_name: str
    files_modified: int
    folders_renamed: int
    output_path: Path
    warnings: list[str] = []
