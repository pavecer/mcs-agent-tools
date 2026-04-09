"""Backward-compatible exports for moved module."""

import sys

from toolkit.core import models as _impl

sys.modules[__name__] = _impl
