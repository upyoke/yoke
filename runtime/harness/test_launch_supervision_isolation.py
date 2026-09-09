"""The suite never reads or spends the machine's real launch custody.

Native supervision records default to the machine cache, which is right in
production and wrong under test: a relay poll exercised by a test reports the
machine's own dead launches as that poll's launch deaths and then deletes
each record it reports.

Nothing here plants a record at the real location. Doing so is the accident
the guard exists to prevent, and it is not undone by isolating
``YOKE_MACHINE_HOME``: an exported ``YOKE_MACHINE_CONFIG_FILE`` still selects
the real config, whose absolute ``cache_dir`` wins.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_harness import session_launch_containment as custody
from yoke_harness import session_relay_termination

from runtime.harness.launch_supervision_isolation import REAL_MACHINE_CACHE


def test_the_default_custody_directory_is_not_the_real_machine_cache() -> None:
    """Nothing a poll reads by default can be the machine's live custody."""
    assert not custody._directory().is_relative_to(REAL_MACHINE_CACHE)


def test_every_custody_resolver_still_agrees_on_one_directory() -> None:
    """Isolation must move the shared root, never one resolver derived from it.

    The hook writes custody through containment and the relay reads it back
    through termination — two independent compositions of the same machine
    root. Redirecting either alone points the writer and the reader at
    different directories, and the launch handle silently stops resolving:
    the split the handle-directory suite exists to catch.
    """
    written = custody._directory()
    read = session_relay_termination.local_state_root(None) / (
        custody.SUPERVISION_DIRECTORY_NAME
    )

    assert written == read


def test_a_poll_that_names_no_directory_reads_only_the_isolated_one() -> None:
    """Reads still work — they just land in the redirected default."""
    (custody._directory() / "launch-isolated.json").write_text(
        json.dumps({
            "supervision_kind": "launch",
            "launch_id": "launch-isolated",
            "pid": 999999,
            "process_start_time": "a start time no process ever had",
        }),
        encoding="utf-8",
    )

    launch_ids = [
        record.get("launch_id") for _path, record in custody.supervised_records()
    ]

    assert launch_ids == ["launch-isolated"]


def test_an_explicit_directory_still_resolves_where_production_puts_it(
    tmp_path: Path,
) -> None:
    """Isolation replaces only the default; a passed directory is untouched."""
    assert custody._directory(tmp_path) == (
        tmp_path / custody.SUPERVISION_DIRECTORY_NAME
    )
