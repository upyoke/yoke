"""The suite never reads or spends the machine's real launch custody.

Native supervision records default to ``machine_config.cache_dir()``, which
is right in production and wrong under test: a relay poll exercised by a
test reports the machine's own dead launches as that poll's launch deaths
and then deletes each record it reports. The autouse isolation redirects
only that default.

Nothing here plants a record at the real resolved location. Doing so is the
very accident the guard exists to prevent, and it is not undone by isolating
``YOKE_MACHINE_HOME``: an exported ``YOKE_MACHINE_CONFIG_FILE`` still selects
the real config, whose absolute ``cache_dir`` wins. The guard is asserted
through the resolver instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_cli.config import machine_config
from yoke_harness import session_launch_containment as custody


def test_the_default_custody_directory_is_not_the_real_machine_cache() -> None:
    """Nothing a poll reads by default can be the machine's live custody."""
    default = custody._directory()

    assert not default.is_relative_to(machine_config.cache_dir())


def test_a_poll_that_names_no_directory_reads_only_the_isolated_one(
    tmp_path: Path,
) -> None:
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
