"""Backward-compatible exports for moved module."""

import sys

from toolkit.core import remote_fetch as _impl

sys.modules[__name__] = _impl
