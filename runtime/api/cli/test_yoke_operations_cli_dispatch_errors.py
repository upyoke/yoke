"""CLI refusals validate selectors before reaching the dispatcher."""

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _reset_captured as _reset_captured,
    _run_with_dispatch,
    _stub_dispatch_ok,
    _stub_dispatch_fail,
)


class TestErrorShapes:
    def test_missing_required_flag_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims",
            "work",
            "release",
            "--claim-id",
            "42",  # missing --reason
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_bad_ref_is_rejected_before_dispatch(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items",
            "get",
            "not-a-sun-id",
        )
        assert rc == 1
        assert _CAPTURED_REQUESTS == []

    def test_bad_integer_flag_returns_two(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims",
            "work",
            "release",
            "--claim-id",
            "not-int",
            "--reason",
            "x",
        )
        assert rc == 2

    def test_claims_work_acquire_requires_target_selector(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims",
            "work",
            "acquire",
            "--reason",
            "no target",
        )
        assert rc == 2

    def test_dispatch_failure_returns_one(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_fail,
            "items",
            "get",
            "YOK-1819",
        )
        assert rc == 1
