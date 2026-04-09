"""Backward-compatible exports for moved module."""

import sys

from toolkit.core import yaml_utils as _impl

sys.modules[__name__] = _impl
