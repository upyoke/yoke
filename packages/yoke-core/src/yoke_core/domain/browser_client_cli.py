"""CLI subcommand handlers for ``browser_client``: daemon / snapshot / exec.

Each handler consumes the public ``browser_client`` API plus the
sibling-owned ``daemon_start`` / ``daemon_stop`` and snapshot helpers.
The argparse tree itself stays in the parent ``browser_client.main``; this
module only owns the post-parse dispatch.

**Parent-module patch routing.** The test suite patches public and private
parent names (``browser_client._state_file_path``,
``browser_client.daemon_request``, etc.) and expects those patches to
affect CLI behavior. To preserve that contract every parent-bound symbol —
``DaemonState``, ``daemon_running``, ``daemon_status``, ``daemon_health``,
``daemon_start``, ``daemon_stop``, ``execute_step``,
``snapshot_accessibility`` / ``snapshot_screenshot`` / ``snapshot_diff``,
``_log`` — is resolved via ``_bc = yoke_core.domain.browser_client`` at
call time, never via a direct sibling import. Importing those names
directly into this module would bypass the parent's patched names and
silently break the test contract.
"""

from __future__ import annotations

import argparse
import json


def _cli_daemon(args: argparse.Namespace) -> int:
    """Handle ``daemon`` subcommand."""
    from yoke_core.domain import browser_client as _bc

    if args.daemon_cmd == "status":
        print(json.dumps(_bc.daemon_status()))
        st = _bc.DaemonState.load()
        return 0 if st and _bc.daemon_running(st) else 2

    elif args.daemon_cmd == "health":
        try:
            print(json.dumps(_bc.daemon_health()))
            return 0
        except RuntimeError as e:
            _bc._log(str(e))
            return 2

    elif args.daemon_cmd == "start":
        try:
            result = _bc.daemon_start(
                port=getattr(args, "port", None),
                headed=getattr(args, "headed", False),
                idle_timeout=getattr(args, "idle_timeout", None),
            )
            print(json.dumps(result))
            return 0
        except RuntimeError as e:
            _bc._log(str(e))
            return 1

    elif args.daemon_cmd == "stop":
        try:
            msg = _bc.daemon_stop()
            print(msg)
            return 0
        except RuntimeError as e:
            _bc._log(str(e))
            return 2

    return 3


def _cli_snapshot(args: argparse.Namespace) -> int:
    """Handle ``snapshot`` subcommand."""
    from yoke_core.domain import browser_client as _bc

    if not _bc.daemon_running():
        _bc._log("daemon not running")
        return 2

    try:
        if args.snap_cmd == "accessibility":
            print(json.dumps(_bc.snapshot_accessibility(args.url)))
        elif args.snap_cmd == "screenshot":
            print(json.dumps(_bc.snapshot_screenshot(
                args.url,
                annotate=getattr(args, "annotate", False),
                output_path=getattr(args, "output", None),
                viewport=getattr(args, "viewport", None),
            )))
        elif args.snap_cmd == "diff":
            print(json.dumps(_bc.snapshot_diff(
                args.url,
                baseline=args.baseline,
                viewport=args.viewport,
                output_dir=getattr(args, "output_dir", None),
                threshold=getattr(args, "threshold", None),
            )))
        else:
            return 3
        return 0
    except RuntimeError as e:
        _bc._log(str(e))
        return 1


def _cli_exec(args: argparse.Namespace) -> int:
    """Handle ``exec`` subcommand."""
    from yoke_core.domain import browser_client as _bc

    if not _bc.daemon_running():
        _bc._log("daemon not running")
        return 2

    try:
        step = json.loads(args.step_json)
        result = _bc.execute_step(step, args.base_url, output_dir=getattr(args, "output_dir", None))
        print(json.dumps(result))
        return 0
    except json.JSONDecodeError as e:
        _bc._log(f"invalid step JSON: {e}")
        return 3
    except RuntimeError as e:
        _bc._log(str(e))
        return 1
