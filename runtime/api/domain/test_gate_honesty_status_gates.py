"""Status-write gates must run, be delisted, or name their own skip.

A gate a definition lists, a catalog describes, or a doc teaches, that does
nothing on the write path is indistinguishable from an enforced one to every
reader — so each case below pins the honest outcome instead.
"""

from __future__ import annotations

import inspect

from yoke_core.domain import backlog_authoritative_status_gate
from yoke_core.domain import backlog_updates_helpers


def test_no_inert_file_line_gate_on_the_status_write_path():
    """The 350-line limit is enforced where a checkout exists, not here."""
    assert not hasattr(backlog_updates_helpers, "_run_file_line_gate")
    source = inspect.getsource(backlog_authoritative_status_gate)
    assert "file_line" not in source
