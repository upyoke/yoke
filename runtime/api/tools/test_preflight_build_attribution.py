"""The fleet kernel hands release source identity to boot convergence."""

import os

import pytest

from yoke_core.tools import preflight_fleet_migrations as preflight


@pytest.mark.parametrize("existing", [None, "existing-build", ""])
def test_product_sha_seeds_build_identity_before_execution(monkeypatch, existing):
    commit = "b" * 40
    if existing is None:
        monkeypatch.delenv("YOKE_BUILD_SHA", raising=False)
    else:
        monkeypatch.setenv("YOKE_BUILD_SHA", existing)
    monkeypatch.setattr(preflight, "_activate_engine_artifact", lambda _: object())

    def execute(parsed, artifact):
        assert parsed.product_sha == commit
        assert os.environ["YOKE_BUILD_SHA"] == (commit if existing is None else existing)
        return 0

    monkeypatch.setattr(preflight, "_execute", execute)
    assert preflight.main(["--project", "example", "--product-sha", commit, "prod"]) == 0
