"""Application metadata helpers shared across CLI and web UI."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import tomllib

PACKAGE_NAME = "pp-agent-toolkit"
REPO_URL = "https://github.com/pavecer/mcs-agent-tools"
ISSUE_URL = f"{REPO_URL}/issues/new?template=bug_report.yml"
FEATURE_URL = f"{REPO_URL}/issues/new?template=feature_request.yml"
LICENSE_NAME = "MIT"


@lru_cache(maxsize=1)
def get_app_version() -> str:
    """Return installed package version, with pyproject fallback for local runs."""
    try:
        return package_version(PACKAGE_NAME)
    except PackageNotFoundError:
        pass
    except Exception:
        pass

    pyproject_path = Path(__file__).resolve().parent / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
        project = data.get("project", {})
        version = project.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    except Exception:
        pass

    return "0.0.0-dev"
