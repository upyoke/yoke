"""Literal QA teaching uses product contracts without executing recipes."""

from pathlib import Path
import json
import shlex

import pytest

from yoke_cli.product_boundary_teaching import generate_teaching_audit
from yoke_cli.product_boundary_teaching_extract import extract_recipe_rows
from yoke_core.tools.taught_recipe_parse_probe import normalize, parse_probe
from yoke_core.tools.taught_recipe_semantic_probe import (
    capability_example_errors,
    probe_recipe,
)


def _recipe(config):
    return (
        "yoke qa requirement add --item PREFIX-N --method-id browser-inspection "
        "--qa-phase post_deploy --workflow-transition release "
        "--instructions 'Inspect intake' --expected-outcome 'Capture intake' "
        f"--method-config '{json.dumps(config)}'"
    )


@pytest.fixture
def no_dispatch(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("teaching audit attempted a live operation")

    monkeypatch.setattr("yoke_cli.commands.adapters.qa_crud.dispatch_and_emit", refuse)
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("subprocess.run", refuse)


@pytest.mark.parametrize("key,valid", [("name", False), ("label", True)])
def test_screenshot_literal_uses_runtime_schema(key, valid, no_dispatch, tmp_path):
    recipe = _recipe(
        {
            "steps": [
                {"action": "navigate", "route": "/<route>"},
                {"action": "screenshot", "capture": True, key: "intake"},
            ]
        }
    )
    ok, _, error = parse_probe(recipe)
    assert ok is valid
    if not valid:
        assert "step_key_unrecognized" in error
    (tmp_path / "AGENTS.md").write_text(f"```bash\n{recipe}\n```\n")
    audit = generate_teaching_audit(repo_root=tmp_path, smoke_yoke=parse_probe)
    assert bool(audit.surfaces[0].drift_type) is not valid


@pytest.mark.parametrize(
    "value,valid",
    [
        ("test-machine", True),
        ("test-machine:<registered-name>", True),
        ("macos-examplehine", False),
        ("macos-examplehine:<name>", False),
        ("test-machine:bad/name", False),
    ],
)
def test_marked_capability_literals_use_declared_type(value, valid, no_dispatch):
    text = f"<!-- qa:test-machine-capability -->`{value}`"
    assert bool(capability_example_errors(text, normalize)) is not valid


def test_prose_is_not_inferred_as_a_capability_contract():
    assert capability_example_errors("`arbitrary` capability prose", normalize) == []


def test_dynamic_payload_is_explicitly_unverifiable(no_dispatch):
    recipe = _recipe({}).replace("'{}'", "'$METHOD_CONFIG'")
    ok, _, detail = parse_probe(recipe)
    assert ok
    assert "semantic_unverifiable" in detail
    assert probe_recipe(recipe, normalize).status == "unverifiable"


def test_multiline_literal_keeps_original_keys(tmp_path, no_dispatch):
    recipe = _recipe(
        {"steps": [{"action": "screenshot", "capture": True, "name": "bad"}]}
    )
    recipe = recipe.replace('"capture":', '\n"capture":')
    (tmp_path / "example.md").write_text(f"```bash\n{recipe}\n```\n")
    rows = list(extract_recipe_rows(tmp_path, ("*.md",)))
    assert len(rows) == 1
    assert rows[0][1] == 2
    assert "step_key_unrecognized" in parse_probe(rows[0][2])[2]


def test_literal_css_selector_survives_placeholder_normalization(no_dispatch):
    recipe = _recipe(
        {"steps": [{"action": "click", "target": '[data-testid="intake"]'}]}
    )
    assert probe_recipe(recipe, normalize).status == "validated"


def _rendered_recipe():
    root = Path(__file__).resolve().parents[3]
    rows = list(
        extract_recipe_rows(
            root, (".agents/skills/yoke/idea/delivery-requirements.md",)
        )
    )
    return next(row[2] for row in rows if "--method-config" in row[2])


def test_rendered_delivery_recipe_is_valid(no_dispatch):
    recipe = _rendered_recipe()
    assert probe_recipe(recipe, normalize).status == "validated"
    assert parse_probe(recipe)[0]


def test_rendered_recipe_authors_in_isolated_database():
    from runtime.api.fixtures.backlog_inserts import insert_item
    from runtime.api.fixtures.pg_testdb import test_database
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.handlers.qa_requirement_create import (
        handle_qa_requirement_add,
    )

    argv = shlex.split(_rendered_recipe())
    config = json.loads(argv[argv.index("--method-config") + 1])
    with test_database() as conn:
        item_id = 42
        insert_item(conn, id=item_id, title="Capture evidence", status="implementing")
        conn.commit()
        outcome = handle_qa_requirement_add(
            FunctionCallRequest(
                function="qa.requirement.add",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="item", item_id=item_id),
                payload={
                    "method_id": "browser-inspection",
                    "qa_phase": "post_deploy",
                    "workflow_transition_id": "release",
                    "instructions": "Inspect intake",
                    "expected_outcome": "Capture intake",
                    "method_config": config,
                },
            )
        )
        assert outcome.primary_success, outcome.error
        row = conn.execute(
            "SELECT method_config FROM qa_requirements WHERE id = %s",
            (outcome.result_payload["requirement_id"],),
        ).fetchone()
        assert json.loads(row[0])["steps"][-1] == {
            "action": "screenshot",
            "capture": True,
            "label": "intake",
        }
