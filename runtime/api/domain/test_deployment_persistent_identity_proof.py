"""A persistent environment proving which revision it serves.

Two proofs settle a persistent-environment receipt and the producer prefers
the stronger one: with a served-revision path configured the environment
answers for itself, whatever deployed it, and only with no such path does
the producing step runner's own verified identity carry the receipt. That
distinction is what makes the release runtime project-agnostic rather than
restricted to Yoke's own health semantics, so each half is exercised here
against the real probe seam.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.deploy_image_tag import canonical_image_tag
from yoke_core.domain.deploy_pipeline_stage_receipt_producers import (
    RECEIPT_PRODUCERS,
    ProducerContext,
)
from yoke_core.domain.deployment_flow_target_support import (
    require_provable_qa_identity,
    unprovable_qa_identity_stages,
)

LINEAGE = "b" * 40
OTHER = "c" * 40
ORIGIN = "https://stage.example.test"
PATH = "/candidate-revision"


def _context(
    *,
    identity_origin: str = ORIGIN,
    identity_path: str = PATH,
    diagnostic: str = "",
    exit_code: int = 0,
    release_lineage: str = LINEAGE,
) -> ProducerContext:
    return ProducerContext(
        dispatch=lambda **_kwargs: (exit_code, diagnostic),
        stage={"name": "deploy", "step_runner": "github-actions-workflow"},
        target={"kind": "persistent_environment", "environment": "stage"},
        run_id="run-identity-1",
        stage_name="deploy",
        project="externalwebapp",
        correlation_id="corr-1",
        dispatch_environment="stage",
        release_lineage=release_lineage,
        identity_origin=identity_origin,
        identity_path=identity_path,
    )


def _produce(context: ProducerContext, monkeypatch: Any, read: Any) -> Any:
    monkeypatch.setattr(probe, "fetch_served_revision", lambda _url: read)
    return RECEIPT_PRODUCERS["persistent_environment"](context)


def _read(body: str, status: int = 200, error: str = "") -> Any:
    return probe.ServedRevisionRead(status=status, body=body, error=error)


class TestConfiguredProof:
    def test_the_environment_serving_the_candidate_is_observed(
        self, monkeypatch: Any
    ) -> None:
        """No health-check ran: the environment answered for itself."""
        rc, diag, observation = _produce(_context(), monkeypatch, _read(LINEAGE + "\n"))

        assert rc == 0
        assert observation is not None
        assert observation.observed_release_lineage == LINEAGE
        assert observation.target_name == "stage"
        assert f"{ORIGIN}{PATH}" in diag

    def test_a_different_revision_is_not_observed(self, monkeypatch: Any) -> None:
        rc, diag, observation = _produce(_context(), monkeypatch, _read(OTHER))

        assert rc == 0
        assert observation is None
        assert "mismatch" in diag

    def test_a_plaintext_placeholder_is_not_an_identity(self, monkeypatch: Any) -> None:
        """A live endpoint answering 'unknown' is malformed, never a match."""
        rc, diag, observation = _produce(_context(), monkeypatch, _read("unknown"))

        assert rc == 0
        assert observation is None
        assert "malformed" in diag
        assert "unknown" in diag

    def test_an_abbreviated_revision_is_malformed(self, monkeypatch: Any) -> None:
        rc, _diag, observation = _produce(_context(), monkeypatch, _read(LINEAGE[:12]))

        assert observation is None

    def test_a_non_200_answer_proves_nothing(self, monkeypatch: Any) -> None:
        """Even with the right body: a 503 page is not the deployment's word."""
        rc, diag, observation = _produce(
            _context(), monkeypatch, _read(LINEAGE, status=503)
        )

        assert observation is None
        assert "unreachable" in diag

    def test_an_unreachable_environment_proves_nothing(self, monkeypatch: Any) -> None:
        rc, diag, observation = _produce(
            _context(), monkeypatch, _read("", status=0, error="connection refused")
        )

        assert observation is None
        assert "connection refused" in diag

    def test_an_environment_with_no_registered_url_refuses_by_name(
        self, monkeypatch: Any
    ) -> None:
        """The origin is authority, so its absence is a configuration refusal."""
        rc, diag, observation = _produce(
            _context(identity_origin=""), monkeypatch, _read(LINEAGE)
        )

        assert observation is None
        assert "no registered url" in diag

    def test_a_failed_dispatch_is_never_probed(self, monkeypatch: Any) -> None:
        """Asking a stage that did not deploy what it serves proves nothing."""
        calls: list[str] = []
        monkeypatch.setattr(
            probe,
            "fetch_served_revision",
            lambda url: calls.append(url) or _read(LINEAGE),
        )

        rc, diag, observation = RECEIPT_PRODUCERS["persistent_environment"](
            _context(exit_code=1, diagnostic="the workflow failed")
        )

        assert (rc, diag) == (1, "the workflow failed")
        assert observation is None
        assert calls == []


class TestRunnerVerifiedFallback:
    def test_with_no_configured_path_the_runner_identity_carries_the_receipt(
        self,
    ) -> None:
        context = _context(
            identity_path="",
            identity_origin="",
            diagnostic=canonical_image_tag(LINEAGE),
        )

        rc, _diag, observation = RECEIPT_PRODUCERS["persistent_environment"](context)

        assert rc == 0
        assert observation is not None
        assert observation.observed_release_lineage == LINEAGE

    def test_a_runner_verifying_another_build_is_not_observed(self) -> None:
        context = _context(
            identity_path="", identity_origin="", diagnostic=canonical_image_tag(OTHER)
        )

        _rc, diag, observation = RECEIPT_PRODUCERS["persistent_environment"](context)

        assert observation is None
        assert "does not identify" in diag

    def test_a_liveness_only_runner_is_not_observed(self) -> None:
        context = _context(identity_path="", identity_origin="", diagnostic="")

        _rc, _diag, observation = RECEIPT_PRODUCERS["persistent_environment"](context)

        assert observation is None


def _stages() -> list[dict[str, Any]]:
    """A non-Yoke project's own shape: its workflow deploys, then QA runs."""
    return [
        {"name": "deploy", "step_runner": "github-actions-workflow"},
        {
            "name": "stage-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "deploy",
            },
        },
    ]


class TestDefinitionGate:
    def test_without_configuration_a_workflow_deployed_target_is_unprovable(
        self,
    ) -> None:
        assert unprovable_qa_identity_stages(_stages())

    def test_a_configured_path_makes_it_provable(self) -> None:
        """The functional requirement: persistent QA for a non-Yoke project."""
        assert (
            unprovable_qa_identity_stages(_stages(), identity_path_configured=True)
            == ()
        )

    def test_the_gate_refuses_when_the_configuration_cannot_be_read(
        self, test_db: Any
    ) -> None:
        """An unreadable capability is not an absent one; activation stops."""
        from yoke_core.domain.deployment_target_identity_config import (
            IDENTITY_CAPABILITY,
        )

        test_db.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            "VALUES (1, %s, %s)",
            (IDENTITY_CAPABILITY, "{not json"),
        )
        test_db.commit()

        try:
            require_provable_qa_identity(
                _stages(), operation="activating", conn=test_db, project=1
            )
        except ValueError as exc:
            assert "cannot be checked for provable QA identity" in str(exc)
        else:
            raise AssertionError("an unreadable identity capability must refuse")

    def test_a_stored_path_admits_the_definition_through_the_gate(
        self, test_db: Any
    ) -> None:
        from yoke_core.domain.deployment_target_identity_config import (
            IDENTITY_CAPABILITY,
        )

        test_db.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            "VALUES (1, %s, %s)",
            (IDENTITY_CAPABILITY, '{"identity_path": "/candidate-revision"}'),
        )
        test_db.commit()

        require_provable_qa_identity(
            _stages(), operation="activating", conn=test_db, project=1
        )
