"""Backward-compatible exports for moved module."""

import sys

from toolkit.core import evals_manager as _impl

sys.modules[__name__] = _impl
