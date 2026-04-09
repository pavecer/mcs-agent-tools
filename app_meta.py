"""Backward-compatible exports for moved module."""

import sys

from toolkit.shared import app_meta as _impl

sys.modules[__name__] = _impl
