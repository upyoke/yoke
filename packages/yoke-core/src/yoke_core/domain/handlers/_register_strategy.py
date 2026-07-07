"""Handler registrations for the ``strategy.*`` family.

Per-project DB-authoritative strategy documents: ``strategy.doc.list``
/ ``strategy.doc.get`` (reads), ``strategy.doc.create`` (new row),
``strategy.doc.replace`` (process-claim-gated write),
``strategy.render.run`` (the only writer of each project's tracked
``.yoke/strategy/`` rendered view),
``strategy.ingest.run`` (CAS write-back from operator-edited rendered
files), and ``strategy.seed_defaults.run`` (cold-start placeholder
rows for a project with no corpus).
"""
from __future__ import annotations

from yoke_core.domain.handlers import (
    strategy_operations,
    strategy_master_plan_check,
    strategy_docs,
    strategy_docs_create,
    strategy_docs_ingest,
    strategy_docs_seed,
)


def register(registry) -> None:
    """Register the strategy family handlers via the given registry."""
    for entry in (
        *strategy_operations.REGISTRATIONS,
        *strategy_master_plan_check.REGISTRATIONS,
        *strategy_docs.REGISTRATIONS,
        *strategy_docs_create.REGISTRATIONS,
        *strategy_docs_ingest.REGISTRATIONS,
        *strategy_docs_seed.REGISTRATIONS,
    ):
        registry.register(**entry)
