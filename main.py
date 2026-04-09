"""Backward-compatible CLI entrypoint wrapper for moved module."""

import sys

from toolkit.cli import main as _impl

if __name__ == "__main__":
    _impl.app()
else:
    sys.modules[__name__] = _impl
