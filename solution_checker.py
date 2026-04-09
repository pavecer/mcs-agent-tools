"""Backward-compatible exports for moved module."""

import sys

from toolkit.core import solution_checker as _impl

sys.modules[__name__] = _impl
