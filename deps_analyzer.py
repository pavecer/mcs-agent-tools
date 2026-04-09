"""Backward-compatible exports for moved module."""

import sys

from toolkit.core import deps_analyzer as _impl

sys.modules[__name__] = _impl
