"""Consumer dispatch refuses producer commits GitHub cannot fetch."""

from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import ci_case, wire_ci_case
from yoke_core.domain import (
    qa_case_ci_candidate_inputs as inputs,
    qa_case_ci_lane as lane,
    qa_case_ci_product_publication as publication,
    qa_case_ci_run,
)
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

SHA = "c" * 40
REPO = "acme/library"


@pytest.fixture()
def remote(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_authority.machine_github_user_authority",
        nullcontext,
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.bound_local_github_user_token_provider",
        lambda: lambda: "test-token",
    )
    read = Mock(return_value={"sha": SHA})
    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_get", read)
    return read


def candidate_case():
    case = ci_case()
    case["method_config"]["ci_workflow_inputs"] = {
        "product_ref": SHA,
        "product_repo": REPO,
    }
    return case


@pytest.mark.parametrize("published", [False, True])
def test_publication_is_checked_before_consumer_dispatch(
    tmp_path,
    monkeypatch,
    remote,
    published,
):
    checkout, _, _ = wire_ci_case(tmp_path, monkeypatch)
    remote.return_value = {"sha": SHA} if published else None
    dispatch = Mock(return_value="77")
    monkeypatch.setattr(lane, "dispatch_workflow", dispatch)
    monkeypatch.setattr(lane, "await_workflow", lambda **k: (0, "success"))
    if published:
        assert (
            qa_case_ci_run.execute_ci_case(
                candidate_case(),
                checkout_path=checkout,
            )["verdict"]
            == "pass"
        )
        dispatch.assert_called_once()
    else:
        with pytest.raises(
            QaCaseExecutionError, match="product_ref_unpublished"
        ) as error:
            qa_case_ci_run.execute_ci_case(candidate_case(), checkout_path=checkout)
        assert REPO in str(error.value) and SHA in str(error.value)
        assert "gate" in str(error.value) and "pushed commit" in str(error.value)
        dispatch.assert_not_called()
    remote.assert_called_once_with(
        f"/repos/{REPO}/git/commits/{SHA}",
        token="test-token",
    )


def test_no_product_ref_does_not_read_github(tmp_path, monkeypatch, remote):
    checkout, _, _ = wire_ci_case(tmp_path, monkeypatch)
    dispatch = Mock(return_value="77")
    monkeypatch.setattr(lane, "dispatch_workflow", dispatch)
    monkeypatch.setattr(lane, "await_workflow", lambda **k: (0, "success"))
    assert (
        qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)["verdict"]
        == "pass"
    )
    remote.assert_not_called()
    dispatch.assert_called_once()


def test_repository_input_precedes_companions(monkeypatch):
    read = Mock(side_effect=AssertionError("must not infer another repository"))
    monkeypatch.setattr(publication, "_read", read)
    assert publication.producer_repository({}, {"product_repo": REPO}) == REPO
    read.assert_not_called()


def companion_reader(monkeypatch, projects):
    refs = [f"LIB-{i + 1}" for i in range(len(projects))]

    def read(function, *, target=None, payload=None):
        if function == "items.dependency.list":
            return {
                "dependencies": [
                    {"direction": "depends-on", "other_item": ref} for ref in refs
                ]
            }
        if function == "items.detail.get":
            return {
                "item": {"project": {"slug": projects[refs.index(target.public_ref)]}}
            }
        assert function == "projects.github_binding.status"
        return {"binding": {"github_repo": REPO}}

    monkeypatch.setattr(publication, "_read", read)


def test_unique_cross_project_companion_supplies_repository(monkeypatch):
    companion_reader(monkeypatch, ["consumer", "library", "library"])
    assert (
        publication.producer_repository(
            {"public_ref": "APP-1", "project": "consumer"},
            {},
        )
        == REPO
    )


@pytest.mark.parametrize(
    "projects,reason",
    [
        ([], "missing"),
        (["consumer"], "missing"),
        (["one", "two"], "ambiguous"),
    ],
)
def test_missing_or_ambiguous_companions_refuse(monkeypatch, projects, reason):
    companion_reader(monkeypatch, projects)
    with pytest.raises(QaCaseExecutionError, match=f"product_ref_repository_{reason}"):
        publication.require_published_product(
            {"public_ref": "APP-1", "project": "consumer"},
            {"product_ref": SHA},
        )


def test_short_or_moving_product_ref_refuses_before_github(remote):
    with pytest.raises(QaCaseExecutionError, match="product_ref_invalid"):
        publication.require_published_product({}, {"product_ref": "main"})
    remote.assert_not_called()


def test_transport_failure_preserves_unverified_reason(remote):
    from yoke_core.domain.gh_rest_transport_errors import RestTransportError

    remote.side_effect = RestTransportError("network unavailable")
    with pytest.raises(QaCaseExecutionError, match="product_ref_unverified"):
        publication.require_published_product(
            {},
            {"product_ref": SHA, "product_repo": REPO},
        )


def test_standalone_case_inputs_require_publication(monkeypatch, remote):
    remote.return_value = None
    case = candidate_case()
    case["standalone_execution_id"] = 1
    with pytest.raises(QaCaseExecutionError, match="product_ref_unpublished"):
        inputs.case_inputs(case, project="consumer")
