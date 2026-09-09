"""Keep ambient launch-custody reads and deletes off the real machine cache.

Native supervision records resolve through ``machine_config.cache_dir()``
whenever no ``state_dir`` is given, and that default is correct in
production: custody is machine-wide, shared with hooks and containment. It
is wrong under test. A relay poll exercised by a test both READS those
records — reporting the developer's or the CI runner's own dead launches as
this poll's launch deaths — and DELETES each one it reports.

The read is what makes such a test environment-coupled: it passes on a
machine whose custody directory happens to be empty and fails on one that
holds a record, which reads as flakiness rather than as the ambient
dependency it is. The delete is worse, because it spends real state a test
never created.

Only the machine's own cache is redirected, and only when a test has not
already said where custody lives. An explicit ``state_dir`` resolves exactly
as it does in production, and a test that pins ``cache_dir`` itself — the
ones whose subject IS this defaulting — keeps the directory it chose.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_launch_supervision_custody(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from yoke_cli.config import machine_config
    from yoke_harness import session_launch_containment as custody

    resolve = custody._directory
    machine_cache = machine_config.cache_dir()
    isolated = tmp_path / "machine-cache"

    def directory(state_dir=None):
        if state_dir is not None:
            return resolve(state_dir)
        selected = machine_config.cache_dir()
        return resolve(isolated if selected == machine_cache else selected)

    monkeypatch.setattr(custody, "_directory", directory)


__all__ = ["_isolate_launch_supervision_custody"]
