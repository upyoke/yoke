"""Consumer declarations reject unsafe or ambiguous candidate inputs."""

import pytest

from yoke_core.domain.consumer_proof_policy import parse_settings


def test_contract_paths_select_only_matching_changes():
    policy = parse_settings(
        '{"producers":{"producer":{"contract_paths":["api/**"],"workflow":"proof.yml"}}}'
    )
    proof = policy.producers["producer"]
    assert proof.touches(["api/contracts/request.py"])
    assert not proof.touches(["docs/news.md"])


@pytest.mark.parametrize(
    "fields",
    [
        '"contract_paths":[]',
        '"contract_paths":["../outside"]',
        '"contract_paths":["/absolute"]',
        '"candidate_input":"yoke_dispatch_id"',
        '"inputs":{"product_ref":"fixed"}',
        '"inputs":{"yoke_dispatch_id":"fixed"}',
        '"inputs":{"mode":""}',
        '"extra":"unknown"',
    ],
)
def test_invalid_declaration_refuses(fields):
    raw = (
        '{"producers":{"producer":{"workflow":"proof.yml","contract_paths":["api/**"],'
        + fields
        + "}}}"
    )
    with pytest.raises(ValueError):
        parse_settings(raw)
