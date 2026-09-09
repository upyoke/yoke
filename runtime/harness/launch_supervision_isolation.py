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

Scope is the custody resolvers themselves, not ``cache_dir``. Several
modules compose the machine root independently, so moving only one points
the writer and the reader at different directories — the split
``test_launch_handle_directory`` exists to catch — while moving ``cache_dir``
reaches every unrelated consumer of it, which is far more of the suite than
a custody concern should touch. Patching this enumerated set keeps those
resolvers agreeing with each other and with nothing else.

Three behaviours are preserved exactly:

* an explicit ``state_dir`` resolves as production does;
* a test that pins ``cache_dir`` itself keeps the directory it chose, since
  the fallback re-reads the resolver and only substitutes while it still
  names the real machine cache;
* the isolated root lives outside the test's own ``tmp_path``, so a test
  asserting on its temp directory's contents does not see it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import machine_config


@pytest.fixture(autouse=True)
def _isolate_launch_supervision_custody(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
    from yoke_harness import session_launch_containment as containment
    from yoke_harness import session_launch_handoff as handoff
    from yoke_harness import session_relay_termination as termination

    real_machine_cache = machine_config.cache_dir()
    isolated = tmp_path_factory.mktemp("launch-custody")

    def root(state_dir: Path | None) -> Path:
        if state_dir is not None:
            return state_dir
        selected = machine_config.cache_dir()
        return isolated if selected == real_machine_cache else selected

    containment_directory = containment._directory
    handoff_directory = handoff._directory

    monkeypatch.setattr(
        containment, "_directory",
        lambda state_dir=None: containment_directory(root(state_dir)),
    )
    monkeypatch.setattr(
        handoff, "_directory",
        lambda state_dir=None: handoff_directory(root(state_dir)),
    )
    monkeypatch.setattr(
        termination, "local_state_root", lambda state_dir=None: root(state_dir),
    )


__all__ = ["_isolate_launch_supervision_custody"]
