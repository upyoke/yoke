"""What this serving runtime actually executes, on both of its axes.

``test_deployment_flow_versioning.py`` owns definition identity and
mutation; this file owns the answer to "may it run here?", which is two
independent questions and reports both:

* the definition schema — the vocabulary this runtime executes, and
* target observability — whether anything can produce the receipt each
  QA stage reads its target from, which splits again into whether a
  producer for the kind exists at all and whether the producing step
  runner returns a verified candidate identity.

The external persistent target is the case worth naming: a project that
deploys its own environment through its own workflow has a perfectly
valid target kind behind a runner that reports what the workflow did
rather than what the environment now serves. Advertising that as
executable would admit a release that could never settle.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.test_deployment_flow_versioning import (
    ADVANCED_STAGES,
    LEGACY_STAGES,
    SUPPORTED_ADVANCED_STAGES,
    _seed_ephemeral_capability,
)
from yoke_core.domain.deployment_flow_target_support import (
    unsupported_stage_target_kinds,
)
from yoke_core.domain.deployment_flow_versioning import cmd_validate_definition
from yoke_core.domain.flow_create import cmd_create


def test_a_preview_definition_is_observable_and_may_activate(
    test_db: Any,
) -> None:
    """A run preview now has a producer, so both axes clear.

    This definition was unexecutable for exactly one reason: no receipt
    producer existed for ``run_preview``, so nothing could observe what
    its QA stage would read. One is registered now — it deploys the run's
    frozen candidate and reads the served revision back from the preview
    itself — so the kind is supported, and the stage owes no separate
    runner identity proof because the producer does that reading itself.
    """
    _seed_ephemeral_capability(test_db)
    result = cmd_validate_definition(
        test_db, project="yoke", stages=ADVANCED_STAGES, status="disabled"
    )
    assert result["definition_schema_version"] == 2
    assert result["unsupported_target_kinds"] == []
    assert result["unprovable_qa_identity_stages"] == []
    assert result["execution_supported"] is True
    # And the guard that held it disabled lifts with them.
    activated = cmd_validate_definition(
        test_db, project="yoke", stages=ADVANCED_STAGES, status="active"
    )
    assert activated["execution_supported"] is True


def test_a_preview_definition_naming_no_registered_capability_is_refused(
    test_db: Any,
) -> None:
    """Supporting the kind does not excuse naming a capability nobody has.

    The producer resolves where a project publishes previews from that
    capability, so a definition naming one the project never registered
    could not be produced for — and the refusal says which name is
    missing rather than reporting the kind as unsupported.
    """
    with pytest.raises(LookupError, match="capability 'ephemeral-env' is not"):
        cmd_validate_definition(
            test_db, project="yoke", stages=ADVANCED_STAGES, status="disabled"
        )



def test_an_external_persistent_target_without_identity_proof_is_refused(
    test_db: Any,
) -> None:
    """The generic case: a project deploying its own environment.

    A non-Yoke project ordinarily deploys through its own Actions
    workflow and would expose its own served-revision endpoint. The
    target kind is supported and the schema is served, so kind alone
    reports this executable — but the producing runner returns prose
    about what the workflow did, not a verified candidate identity, so
    nothing could settle its QA stage's receipt. It is refused before it
    deploys anything rather than deployed and then stuck.
    """
    stages = json.dumps(
        [
            {
                "name": "deploy-via-actions",
                "step_runner": "github-actions-workflow",
                "stage_kind": "execution",
                "scope": "run",
                "workflow": "deploy.yml",
            },
            {
                "name": "release-qa",
                "step_runner": "qa",
                "stage_kind": "qa",
                "scope": "run",
                "target": {
                    "kind": "persistent_environment",
                    "environment": "development",
                    "source_stage": "deploy-via-actions",
                },
                "verdict": {"mode": "agent_only"},
            },
        ]
    )

    result = cmd_validate_definition(
        test_db, project="yoke", stages=stages, status="disabled"
    )

    # The kind itself is fine; the producer behind it is the gap.
    assert result["unsupported_target_kinds"] == []
    assert result["execution_supported"] is False
    assert result["unprovable_qa_identity_stages"] == [
        "'release-qa' reads its target from 'deploy-via-actions', whose step "
        "runner 'github-actions-workflow' returns no verified candidate identity"
    ]
    with pytest.raises(ValueError, match="cannot verify"):
        cmd_validate_definition(
            test_db, project="yoke", stages=stages, status="active"
        )


def _environment_stating_its_path(conn: Any, name: str, path: str) -> None:
    """One environment that states the path it proves its own revision at."""
    site = conn.execute(
        "INSERT INTO sites (project_id, name, created_at) "
        "VALUES (1, %s, %s) RETURNING id",
        (f"site-{name}", "2026-09-17T00:00:00Z"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO environments (site, project_id, name, settings, created_at) "
        "VALUES (%s, 1, %s, %s, %s)",
        (
            int(site),
            name,
            json.dumps({"qa": {"identity_path": path}}),
            "2026-09-17T00:00:00Z",
        ),
    )
    conn.commit()


def test_the_preview_reads_the_environment_statement_the_gate_reads(
    test_db: Any,
) -> None:
    """A preview and the gate that admits it must answer alike.

    An environment states its own served-revision path, because a project
    reaches each of its environments under a different prefix. Asking the
    project alone misses that statement, and the definition below is the
    case where the two answers diverge: the producing runner proves no
    identity, so without the statement this is refused — but the
    environment proves itself, so the gate admits it. A preview that
    reported it unexecutable would send an operator to configure
    something already configured.
    """
    _environment_stating_its_path(test_db, "attested", "/v1/health")
    stages = json.dumps(
        [
            {
                "name": "deploy-via-actions",
                "step_runner": "github-actions-workflow",
                "stage_kind": "execution",
                "scope": "run",
                "workflow": "deploy.yml",
            },
            {
                "name": "release-qa",
                "step_runner": "qa",
                "stage_kind": "qa",
                "scope": "run",
                "target": {
                    "kind": "persistent_environment",
                    "environment": "attested",
                    "source_stage": "deploy-via-actions",
                },
                "verdict": {"mode": "agent_only"},
            },
        ]
    )

    result = cmd_validate_definition(
        test_db, project="yoke", stages=stages, status="disabled"
    )

    assert result["unprovable_qa_identity_stages"] == []
    assert result["execution_supported"] is True
    # The gate agrees, which is the whole point of reading one configuration.
    assert cmd_validate_definition(
        test_db, project="yoke", stages=stages, status="active"
    )["execution_supported"] is True


def test_a_definition_whose_targets_are_observable_activates(test_db: Any) -> None:
    """The enabled boundary: schema 2 with an environment-backed QA target."""
    result = cmd_validate_definition(
        test_db,
        project="yoke",
        stages=SUPPORTED_ADVANCED_STAGES,
        status="disabled",
    )
    assert result["definition_schema_version"] == 2
    assert result["execution_supported"] is True
    assert result["unsupported_target_kinds"] == []
    assert result["unprovable_qa_identity_stages"] == []
    activated = cmd_validate_definition(
        test_db, project="yoke", stages=SUPPORTED_ADVANCED_STAGES, status="active"
    )
    assert activated["execution_supported"] is True



def test_a_legacy_definition_stays_executable_once_the_newer_schema_is_served(
    test_db: Any,
) -> None:
    """Serving the release schema must not strand version-1 definitions.

    A hosted delivery route is ordinarily a legacy definition —
    ``merged`` / ``github-actions-workflow`` / ``complete``, no QA stage
    and so no target kind to observe. Raising the served vocabulary
    widens what is executable and must never narrow it, and the
    target-kind guard must find nothing to refuse in a definition that
    declares no QA stage at all. Getting this wrong is an outage at
    deploy time rather than a failing test, so it is asserted rather
    than reasoned about.
    """
    result = cmd_validate_definition(
        test_db, project="yoke", stages=LEGACY_STAGES, status="disabled"
    )
    assert result["definition_schema_version"] == 1
    assert result["execution_supported"] is True
    assert result["unsupported_target_kinds"] == []

    # The gates that guard activation, assignment and start accept it.
    activated = cmd_validate_definition(
        test_db, project="yoke", stages=LEGACY_STAGES, status="active"
    )
    assert activated["execution_supported"] is True
    assert unsupported_stage_target_kinds(LEGACY_STAGES) == ()

    # And through the real create/activate path, not only the validator.
    cmd_create(
        test_db,
        "legacy-active-flow",
        "yoke",
        "Legacy active flow",
        "",
        LEGACY_STAGES,
        status="active",
    )
    assert (
        test_db.execute(
            "SELECT status FROM deployment_flows WHERE id='legacy-active-flow'"
        ).fetchone()["status"]
        == "active"
    )

