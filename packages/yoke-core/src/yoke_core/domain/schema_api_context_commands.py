"""Wrapper-command recipes for the agent-context packet generator.

Pure data sibling of :mod:`schema_api_context_seed`. Holds the canonical
``WRAPPER_COMMANDS`` list (one entry per topic + purpose) by combining
per-topic siblings. The packet renderer in
:mod:`yoke_core.domain.schema_api_context` groups entries by topic
when expanding a marker pair.

Topic-scoped siblings (added 2026-05-14 to keep this module under the
350-line authored-file cap while preserving the
``WRAPPER_COMMANDS`` public export):

- :mod:`schema_api_context_commands_core` — structured-field reads /
  writes, epic task body/metadata, dependency CRUD, db-claim amendment,
  raw diagnostic read.
- :mod:`schema_api_context_commands_claims` — work-claim, path-claim
  CRUD / widen / conflicts, coordination-decision helper.
- :mod:`schema_api_context_commands_qa` — QA requirement / run reads,
  verdict recording, gate preview / summary, events read.
- :mod:`schema_api_context_commands_project` — project test-command
  read / list helpers.
- :mod:`schema_api_context_commands_watchers` — watcher / Monitor /
  background-command recipes (``watch_pytest``, ``watch_doctor``,
  ``watch_merge``) for main-session and subagent-foreground patterns.

Agent-surface doctrine
----------------------
Mutation recipes teach CLI adapters as the executable agent shape.
Function ids remain the underlying contract: adapters dispatch typed
envelopes, validate claims, and emit ``YokeFunctionCalled`` evidence.
The packet therefore names important function ids in notes, but it does
not teach agents to start ``api_server``, call ``curl`` against the local
HTTP boundary, or build direct ``runtime.api`` Python import one-liners.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_commands_claims import (
    CLAIMS_COMMANDS,
)
from yoke_core.domain.schema_api_context_commands_core import (
    CORE_COMMANDS,
)
from yoke_core.domain.schema_api_context_commands_project import (
    PROJECT_COMMANDS,
)
from yoke_core.domain.schema_api_context_commands_qa import (
    QA_COMMANDS,
)
from yoke_core.domain.schema_api_context_commands_watchers import (
    WATCHERS_COMMANDS,
)


WRAPPER_COMMANDS: list[dict] = (
    CORE_COMMANDS
    + CLAIMS_COMMANDS
    + QA_COMMANDS
    + PROJECT_COMMANDS
    + WATCHERS_COMMANDS
)


__all__ = ["WRAPPER_COMMANDS"]
