"""Only registered exact-capture triage can discharge a simulation."""

import json
import pytest
from yoke_core.domain import sections, item_field_transform_sections
from yoke_core.domain.handlers import items_section, items_structured_field
from yoke_core.domain.item_json_sections import read_json_section
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    ActorContext,
    TargetRef,
)
from unittest.mock import patch

from runtime.api.domain.test_qa_simulation_triage import (
    _BorrowedConnection,
    _record,
    _seed,
    REPORT,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.events_acting_identity import acting_event_identity
from yoke_core.domain.qa_execution import cmd_run_complete
from yoke_core.domain.qa_simulation_triage import (
    current_simulation_triage,
    triage_discharge_sql,
)


@pytest.mark.parametrize(
    "changed_report",
    [REPORT.replace("PROCEED", "FIX_FIRST"), REPORT.replace("WARNING", "CRITICAL")],
)
def test_same_run_report_mutation_invalidates_sql_and_python_discharge(changed_report):
    with test_database() as conn:
        item, requirement, attempt, ref, actor = _seed(conn)
        with acting_event_identity(session_id="simulation-owner", actor_id=actor):
            _record(conn, item, [ref])
            with patch(
                "yoke_core.domain.qa_execution.connect",
                return_value=_BorrowedConnection(conn),
            ):
                cmd_run_complete(
                    run_id=attempt["id"],
                    verdict="fail",
                    verdict_reason="Revised failed report",
                    raw_result=json.dumps(
                        {
                            "body": changed_report,
                            "phase": "integration",
                        }
                    ),
                )
        assert current_simulation_triage(conn, requirement) is None
        assert not conn.execute(
            f"SELECT {triage_discharge_sql(conn, 'q')} FROM qa_requirements q WHERE id=%s",
            (requirement,),
        ).fetchone()[0]


def _request(function, item, section, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="simulation-owner", actor_id="7"),
        target=TargetRef(
            kind="section" if function.startswith("items.section.") else "item",
            item_id=item,
            section_name=section if function.startswith("items.section.") else None,
        ),
        payload=payload,
    )


def test_general_section_writes_cannot_forge_or_destroy_discharge():
    with test_database() as conn:
        item, requirement, attempt, ref, actor = _seed(conn)
        section = f"Simulation Triage {requirement}:{attempt['id']}"
        forged = json.dumps(
            {
                "actor_id": actor,
                "run_id": attempt["id"],
                "requirement_id": requirement,
                "discharge_kind": "simulation_triage",
            }
        )
        for operation in [items_section.handle_upsert, items_section.handle_delete]:
            function = (
                "items.section.upsert"
                if operation == items_section.handle_upsert
                else "items.section.delete"
            )
            result = operation(
                _request(
                    function,
                    item,
                    section,
                    {"content": forged, "source": "direct-workflow"},
                )
            )
            assert (
                not result.primary_success
                and result.error.code == "section_authority_reserved"
            )
        for operation, function, payload in [
            (
                items_structured_field.handle_section_upsert,
                "items.structured_field.section_upsert",
                {"section": section, "content": forged},
            ),
            (
                items_structured_field.handle_section_append,
                "items.structured_field.section_append",
                {"section": section, "headline": "Forge", "content": forged},
            ),
            (
                items_structured_field.handle_replace,
                "items.structured_field.replace",
                {"field": section, "content": forged},
            ),
            (
                items_structured_field.handle_replace,
                "items.structured_field.replace",
                {"field": "body", "content": forged},
            ),
        ]:
            result = operation(_request(function, item, section, payload))
            assert not result.primary_success
        assert read_json_section(conn, item_id=item, section=section) is None
        assert current_simulation_triage(conn, requirement) is None
        with acting_event_identity(session_id="simulation-owner", actor_id=actor):
            receipt = _record(conn, item, [ref])
        for operation in [
            lambda: sections.upsert_section(
                item, section, forged, source="direct-workflow"
            ),
            lambda: sections.delete_section(item, section),
        ]:
            with pytest.raises(ValueError, match="section_authority_reserved"):
                operation()
        assert not item_field_transform_sections.section_append(
            item_id=item, section=section, headline="Forge", content=forged
        ).success
        assert current_simulation_triage(conn, requirement) == receipt
        conn.execute("UPDATE work_claims SET released_at='2026-10-08T00:00:00Z'")
        conn.commit()
        assert current_simulation_triage(conn, requirement) == receipt


def test_only_the_authenticated_claim_holder_can_write_triage():
    with test_database() as conn:
        item, requirement, _attempt, ref, actor = _seed(conn)
        with acting_event_identity(session_id="different-session", actor_id=actor):
            with pytest.raises(ValueError, match="claim_required"):
                _record(conn, item, [ref])
        assert current_simulation_triage(conn, requirement) is None


def test_replay_cannot_replace_a_changed_capture_audit():
    with test_database() as conn:
        item, requirement, attempt, ref, actor = _seed(conn)
        section = f"Simulation Triage {requirement}:{attempt['id']}"
        with acting_event_identity(session_id="simulation-owner", actor_id=actor):
            receipt = _record(conn, item, [ref])
            conn.execute(
                "UPDATE qa_runs SET completed_at='2026-10-01T00:00:03Z' WHERE id=%s",
                (attempt["id"],),
            )
            conn.commit()
            with pytest.raises(ValueError, match="attempt_changed"):
                _record(conn, item, [ref])
        assert read_json_section(conn, item_id=item, section=section) == receipt
        assert current_simulation_triage(conn, requirement) is None
        assert not conn.execute(
            f"SELECT {triage_discharge_sql(conn, 'q')} FROM qa_requirements q WHERE id=%s",
            (requirement,),
        ).fetchone()[0]
