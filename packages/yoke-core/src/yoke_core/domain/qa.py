"""QA domain logic — thin re-export shim.

Canonical owner for the ``qa`` domain. Schema/init/QA-vocab migration live
in :mod:`yoke_core.domain.qa_schema`; the CLI parser/dispatcher lives in
:mod:`yoke_core.domain.qa_cli`. The CRUD command implementations live in
:mod:`yoke_core.domain.qa_requirements`,
:mod:`yoke_core.domain.qa_execution`, and
:mod:`yoke_core.domain.qa_reporting`.

This module re-exports the public surface so that existing callers
(``from yoke_core.domain.qa import ...``) keep working unchanged, and
the ``python3 -m yoke_core.domain.qa`` CLI continues to dispatch via
:func:`yoke_core.domain.qa_cli.main`.

CLI usage::

    python3 -m yoke_core.domain.qa <subcmd> [args...]

Subcommands:

    init, requirement-add, requirement-add-batch, requirement-list, requirement-get,
    requirement-update, requirement-waive, run-add, run-add-batch, run-complete,
    run-list, run-get, artifact-add, artifact-list,
    baseline-record, baseline-list, baseline-get, baseline-promote,
    satisfy-screenshot-evidence

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Child module imports — all public symbols re-exported for backward compat
# ---------------------------------------------------------------------------

from yoke_core.domain.qa_constants import (  # noqa: F401
    VALID_QA_PHASES,
    VALID_BLOCKING_MODES,
    VALID_REQUIREMENT_SOURCES,
    VALID_VERDICTS,
    VALID_BROWSER_QA_KINDS,
    _coalesce,
    _normalize_qa_phase,
    _normalize_qa_kind,
    _pipe_row,
    _REQ_SELECT,
)

from yoke_core.domain.qa_requirements import (  # noqa: F401
    UPDATABLE_REQUIREMENT_FIELDS,
    cmd_requirement_add,
    cmd_requirement_add_batch,
    cmd_requirement_list,
    cmd_requirement_get,
    cmd_requirement_update,
    cmd_requirement_waive,
)

from yoke_core.domain.qa_execution import (  # noqa: F401
    _RUN_SELECT,
    _ART_SELECT,
    _resolve_requirement_event_target,
    _emit_qa_requirement_event,
    _emit_qa_run_event,
    _linked_artifact_handle,
    cmd_run_add,
    cmd_run_add_batch,
    cmd_run_complete,
    cmd_run_list,
    cmd_run_get,
    cmd_artifact_add,
    cmd_artifact_list,
    cmd_satisfy_screenshot_evidence,
)

from yoke_core.domain.qa_reporting import (  # noqa: F401
    _route_slug,
    _baseline_path,
    cmd_baseline_record,
    cmd_baseline_list,
    cmd_baseline_get,
    cmd_baseline_promote,
)

from yoke_core.domain.qa_schema import (  # noqa: F401
    _QA_SCHEMA,
    _migrate_qa_vocab,
    cmd_init,
)

from yoke_core.domain.qa_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
