"""Path claim CLI writes carry public item selectors."""

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _reset_captured as _reset_captured,
    _run_with_dispatch,
    _stub_dispatch_ok,
)


class TestPathDispatch:
    def test_claims_path_register_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims",
            "path",
            "register",
            "--item",
            "YOK-1819",
            "--paths",
            "runtime/api/cli/foo.py,runtime/api/cli/bar.py",
            "--allow-planned",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.path.register"
        assert req.target.public_ref == "YOK-1819"
        assert req.payload["paths"] == [
            "runtime/api/cli/foo.py",
            "runtime/api/cli/bar.py",
        ]
        assert req.payload["allow_planned"] is True
        assert req.payload["mode"] == "exclusive"

    def test_claims_path_widen_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims",
            "path",
            "widen",
            "--claim-id",
            "273",
            "--add-paths",
            "runtime/api/cli/new.py",
            "--reason",
            "extend coverage",
            "--item",
            "YOK-1819",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.path.widen"
        assert req.target.public_ref == "YOK-1819"
        assert req.payload == {
            "claim_id": 273,
            "add_paths": ["runtime/api/cli/new.py"],
            "reason": "extend coverage",
            "allow_planned": False,
        }

    def test_claims_path_widen_allow_planned_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims",
            "path",
            "widen",
            "--claim-id",
            "273",
            "--add-paths",
            "runtime/api/domain/new.py,runtime/api/domain/dir/",
            "--reason",
            "widen with planned coverage",
            "--item",
            "YOK-1819",
            "--allow-planned",
            "--directory-paths",
            "runtime/api/domain/dir/",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.path.widen"
        assert req.target.public_ref == "YOK-1819"
        assert req.payload == {
            "claim_id": 273,
            "add_paths": [
                "runtime/api/domain/new.py",
                "runtime/api/domain/dir/",
            ],
            "reason": "widen with planned coverage",
            "allow_planned": True,
            "directory_paths": ["runtime/api/domain/dir/"],
        }
