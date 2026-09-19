"""A refused mutation has to look refused in --json, not just in prose.

An agent reads the exit status and the JSON; a human reads the sentence on
stderr. If the machine-readable path ever answered an empty success envelope
with exit 0, a caller would record a write that never happened and the next
reader would see obsolete state presented as current. That is the quietest
way this CLI can lie, so the contract is pinned here against the shared
emitter every registered adapter routes through.
"""

from __future__ import annotations

import json

import pytest

from yoke_cli.commands import _helpers
from yoke_cli.commands.adapters.qa_requirement_supersede import (
    qa_requirement_supersede,
)
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)


REFUSAL = "requirement 28054 latest verdict is missing, not pass."
ARGV = [
    "--requirement-id",
    "28013",
    "--superseded-by-requirement-id",
    "28054",
    "--rationale",
    "the corrected case passed in its place",
]


@pytest.fixture
def refused(monkeypatch):
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        _helpers,
        "call_dispatcher",
        lambda **_kwargs: FunctionCallResponse(
            function="qa.requirement.supersede",
            version="v1",
            request_id="r-1",
            success=False,
            result={},
            error=FunctionError(code="supersession_refused", message=REFUSAL),
        ),
    )


def test_json_prints_the_refusal_envelope_and_exits_non_zero(
    refused, capsys
) -> None:
    code = qa_requirement_supersede([*ARGV, "--json"])
    printed = json.loads(capsys.readouterr().out)
    assert code != 0
    assert printed["success"] is False
    assert printed["error"]["code"] == "supersession_refused"
    assert printed["error"]["message"] == REFUSAL


def test_the_human_path_names_the_reason_and_exits_non_zero(
    refused, capsys
) -> None:
    code = qa_requirement_supersede(ARGV)
    captured = capsys.readouterr()
    assert code != 0
    assert "supersession_refused" in captured.err
    assert REFUSAL in captured.err
    # Nothing on stdout may read as a completed supersession.
    assert "superseded by" not in captured.out
