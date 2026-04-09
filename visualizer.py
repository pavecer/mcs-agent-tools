"""Backward-compatible exports for moved module."""

import sys

from toolkit.core import visualizer as _impl

sys.modules[__name__] = _impl
