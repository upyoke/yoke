"""Watcher wrapper entry points, keyed by wrapper module id.

The ``yoke watch <kind>`` adapters need a wrapper's ``main`` from the
other side of the CLI-to-engine package boundary. Collecting the four
here gives that boundary exactly one crossing to classify instead of one
per wrapper, and keeps the adapter free of a second module-id roster.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.tools import (
    watch_doctor,
    watch_merge,
    watch_pytest,
    watch_qa_case,
    watch_tail,
)

# Each wrapper's ``main(argv, *, prog=...)``.
WrapperMain = Callable[..., Any]

WRAPPER_MAINS: dict[str, WrapperMain] = {
    module.WRAPPER_MODULE: module.main
    for module in (
        watch_pytest,
        watch_doctor,
        watch_merge,
        watch_qa_case,
        watch_tail,
    )
}


__all__ = ["WRAPPER_MAINS", "WrapperMain"]
