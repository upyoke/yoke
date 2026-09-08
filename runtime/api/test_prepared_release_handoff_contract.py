"""The hand-off names a real connection and a deliverable recipient.

Both halves of this hand-off are strings that look right until something
tries to use them, which is why they are asserted against the contracts that
consume them rather than against a mock that accepts anything.

The recipient selector is built by :class:`RecipientSelector` itself and its
steering scope by the same resolver the send path runs, so a scope shaped for
a reader that does not exist fails here instead of at the one moment the
hand-off matters — when no session holds the deploy lock and the message is
the only thing left carrying the release.

The execute recipe is checked for the mistake that makes it useless: naming a
connection derived from the project or the deployment target. ``--env`` names
the CONTROL PLANE holding the run row; one control plane serves every target,
so a label built from either of those points an operator at a connection this
machine has never heard of.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yoke_contracts.machine_config.schema import DB_ADMIN_ENV_SUFFIX
from yoke_contracts.session_control.recipient_selector import (
    STEERING_SCOPE_PROJECT_KEY,
    RecipientSelector,
)
from yoke_core.engines.runs_release_handoff import (
    CONTROL_PLANE_ENV_PLACEHOLDER,
    compose_handoff_body,
)


PROJECT_ID = 1
PROJECT_SLUG = "yoke"
RUN_ID = "run-20260908-001"
MERGE_COMMIT = "c" * 40


def _steering_selector(project_id: int) -> RecipientSelector:
    """The no-holder selector, built through the real model."""
    return RecipientSelector.model_validate(
        {
            "steering": True,
            "steering_scope": {STEERING_SCOPE_PROJECT_KEY: project_id},
        }
    )


class TestTheNoHolderSelector:
    def test_the_steering_scope_carries_an_integer_project_id(self) -> None:
        selector = _steering_selector(PROJECT_ID)
        assert selector.steering is True
        assert selector.steering_scope == {STEERING_SCOPE_PROJECT_KEY: PROJECT_ID}

    def test_the_scope_key_the_resolver_reads_is_present(self) -> None:
        """The resolver indexes this key directly; a scope without it raises."""
        selector = _steering_selector(PROJECT_ID)
        assert selector.steering_scope is not None
        assert STEERING_SCOPE_PROJECT_KEY in selector.steering_scope

    def test_a_slug_keyed_scope_is_refused_by_the_model(self) -> None:
        """The shape that looks addressed but names no readable project.

        The selector refuses it outright rather than accepting a scope the
        resolver would later fail to index, so this class of hand-off breaks
        at construction with a named reason instead of at delivery.
        """
        with pytest.raises(ValidationError) as refusal:
            RecipientSelector.model_validate(
                {"steering": True, "steering_scope": {"projects": [PROJECT_SLUG]}}
            )
        assert STEERING_SCOPE_PROJECT_KEY in str(refusal.value)

    def test_the_holder_selector_names_one_session(self) -> None:
        holder = "112bd83c-b07b-4204-b8e5-29dcd0aa4e7d"
        selector = RecipientSelector.model_validate({"session_ids": [holder]})
        assert selector.session_ids == [holder]
        assert selector.steering is False


class TestTheExecuteRecipe:
    @pytest.fixture
    def body(self) -> str:
        return compose_handoff_body(
            project_slug=PROJECT_SLUG,
            run_id=RUN_ID,
            release_lineage=MERGE_COMMIT,
        )

    def test_the_recipe_never_derives_a_connection_from_the_project(
        self, body: str
    ) -> None:
        assert f"{PROJECT_SLUG}{DB_ADMIN_ENV_SUFFIX}" not in body

    def test_the_recipe_names_an_admin_connection(self, body: str) -> None:
        assert DB_ADMIN_ENV_SUFFIX in body

    def test_an_unresolvable_machine_still_teaches_the_shape(
        self, body: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no resolvable pairing the recipe is a placeholder, not a guess."""
        monkeypatch.setattr(
            "yoke_core.engines.runs_release_handoff._control_plane_admin_env",
            lambda: "",
        )
        unresolved = compose_handoff_body(
            project_slug=PROJECT_SLUG,
            run_id=RUN_ID,
            release_lineage=MERGE_COMMIT,
        )
        assert CONTROL_PLANE_ENV_PLACEHOLDER in unresolved
        assert f"{PROJECT_SLUG}{DB_ADMIN_ENV_SUFFIX}" not in unresolved

    def test_the_body_names_the_run_and_the_commit_it_will_deploy(
        self, body: str
    ) -> None:
        assert RUN_ID in body
        assert MERGE_COMMIT in body

    def test_the_body_states_that_nothing_has_deployed_yet(self, body: str) -> None:
        assert "Nothing has been deployed" in body
