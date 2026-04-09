"""Backward-compatible exports for moved module."""

import sys

from toolkit.web import rxconfig as _impl

sys.modules[__name__] = _impl
