"""Compatibility alias for the product CLI project-install runner."""

from __future__ import annotations

import sys

from yoke_cli.project_install import runner as _runner

sys.modules[__name__] = _runner
