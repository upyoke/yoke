"""Keep ambient launch-custody reads and deletes off the real machine cache.

Native supervision records live in the machine cache whenever no explicit
``state_dir`` is given, and that default is correct in production: custody is
machine-wide, shared with the hook that writes it, the relay that reads it,
and containment. It is wrong under test. A relay poll exercised by a test
both READS those records — reporting the developer's or the CI runner's own
dead launches as this poll's launch deaths — and DELETES each one it reports.

The read is what makes such a test environment-coupled: it passes on a
machine whose custody directory happens to be empty and fails on one that
holds a record, which reads as flakiness rather than as the ambient
dependency it is. The delete is worse, because it spends real state a test
never created.

The redirect is applied at ``cache_dir`` — the one root every custody
resolver bottoms out at — and deliberately NOT at any single resolver
derived from it. Several modules compose that root independently
(containment, relay termination, launch handoff, launch handles), so moving
one of them alone points the writer and the reader at different directories,
which is the very split ``test_launch_handle_directory`` exists to catch.
An explicit ``state_dir`` still wins, and a test that pins ``cache_dir``
itself overrides this fixture the moment it does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import machine_config

#: The machine's own cache, read once before any test can redirect it, so a
#: test can still prove the isolated root is not the real one.
REAL_MACHINE_CACHE: Path = machine_config.cache_dir()


@pytest.fixture(autouse=True)
def _isolate_launch_supervision_custody(tmp_path, monkeypatch: pytest.MonkeyPatch):
    isolated = tmp_path / "machine-cache"
    isolated.mkdir(mode=0o700, parents=True, exist_ok=True)
    monkeypatch.setattr(machine_config, "cache_dir", lambda: isolated)


__all__ = ["REAL_MACHINE_CACHE", "_isolate_launch_supervision_custody"]
