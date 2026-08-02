"""Follower detection must be spelling-independent.

``print_streaming_pair`` emits ``yoke watch tail <capture>`` as the
progress leg, so the duplicate-Monitor and background-waiter guards have
to recognise that spelling. Matching only the module form would silently
retire the fire-once-per-capture contract the moment the emitted pair
changed shape.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_monitor_capture_file,
)
from yoke_core.domain.lint_long_command_polling_waiter import (
    _extract_waiter_target,
)

CAPTURE = "/tmp/yoke-pytest.progress.log"


class TestMonitorCaptureExtraction(unittest.TestCase):
    def test_yoke_watch_tail_command(self):
        self.assertEqual(
            _extract_monitor_capture_file(f"yoke watch tail {CAPTURE}"),
            CAPTURE,
        )

    def test_cwd_anchored_yoke_watch_tail_command(self):
        # The emitted progress leg is `cd <dir> && yoke watch tail <path>`.
        self.assertEqual(
            _extract_monitor_capture_file(f"cd /repo && yoke watch tail {CAPTURE}"),
            CAPTURE,
        )

    def test_module_fallback_still_matches(self):
        self.assertEqual(
            _extract_monitor_capture_file(
                f"python3 -m yoke_core.tools.watch_tail {CAPTURE}"
            ),
            CAPTURE,
        )


class TestWaiterExtraction(unittest.TestCase):
    def test_yoke_watch_tail_command(self):
        shape, target = _extract_waiter_target(f"yoke watch tail {CAPTURE}")
        self.assertEqual(shape, "watch-tail")
        self.assertEqual(target, CAPTURE)

    def test_module_fallback_still_matches(self):
        shape, target = _extract_waiter_target(
            f"python3 -m yoke_core.tools.watch_tail {CAPTURE}"
        )
        self.assertEqual(shape, "watch-tail")
        self.assertEqual(target, CAPTURE)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
