"""Recovery recipes printed by env-override teaching must be executable.

Assembling a recipe by echoing caller argv reprints the mistake: db_router
takes the first positional as a domain, so ``--env`` becomes ``unknown
domain``, and on ``yoke`` an echoed ``--env`` outranks the ``YOKE_ENV=``
prefix the teaching just added.
"""

from __future__ import annotations

import io
import re
import shlex
from contextlib import redirect_stderr, redirect_stdout

from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config import schema_connections
from yoke_core.cli import db_router


def _payload_with_prod_admin() -> dict:
    payload = contract.canonical_example_payload()
    payload["connections"]["prod-db-admin"] = {
        "transport": "local-postgres",
        contract.PROD_FLAG_KEY: True,
        "credential_source": {"kind": "env", "name": "YOKE_PROD_DSN"},
    }
    payload["active_env"] = "prod"
    return payload


def _run_router(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = db_router.main(argv)
    return rc, err.getvalue()


def test_db_router_rejects_env_flag_as_a_domain(monkeypatch) -> None:
    monkeypatch.setattr(db_router, "_auto_init", lambda *_a, **_k: None)
    monkeypatch.setattr(db_router, "_probe_schema_or_remediate", lambda _argv: None)

    rc, err = _run_router(["--env", "prod-db-admin", "query", "SELECT 1"])

    assert rc == 2
    assert "unknown domain" in err
    assert "--env" in err


def test_invocation_recipe_strips_env_flag_from_accepted_shapes() -> None:
    module_form = schema_connections._invocation_recipe(
        argv=["/x/db_router.py", "--env", "prod-db-admin", "query", "SELECT 1"],
        main_spec_name="yoke_core.cli.db_router",
        interpreter="/venv/bin/python3",
    )
    assert module_form == (
        "/venv/bin/python3 -m yoke_core.cli.db_router query 'SELECT 1'"
    )

    equals_form = schema_connections._invocation_recipe(
        argv=["/x/db_router.py", "--env=prod-db-admin", "query", "SELECT 1"],
        main_spec_name="yoke_core.cli.db_router",
        interpreter="/venv/bin/python3",
    )
    assert "--env" not in equals_form
    assert equals_form.endswith("query 'SELECT 1'")

    yoke_form = schema_connections._invocation_recipe(
        argv=["/usr/local/bin/yoke", "--env", "prod", "status"],
        main_spec_name="",
    )
    assert yoke_form == "yoke status"


def test_printed_recovery_recipe_executes_as_db_router_argv(monkeypatch) -> None:
    recipe = schema_connections._invocation_recipe(
        argv=["/x/db_router.py", "--env", "prod-db-admin", "query", "SELECT 1"],
        main_spec_name="yoke_core.cli.db_router",
        interpreter="/venv/bin/python3",
    )
    text = contract.env_override_teaching(
        _payload_with_prod_admin(),
        selected_env="prod",
        transport="https",
        command=recipe,
    )
    match = re.search(r"Run: YOKE_ENV=(\S+) (.+?) \(", text)
    assert match is not None
    assert match.group(1) == "prod-db-admin"
    tokens = shlex.split(match.group(2))
    module_idx = tokens.index("-m")
    assert tokens[module_idx + 1] == "yoke_core.cli.db_router"
    router_argv = tokens[module_idx + 2 :]
    assert router_argv == ["query", "SELECT 1"]

    captured: list[list[str]] = []

    def _fake_dispatch(module: str, remaining: list[str]) -> int:
        captured.append([module, *remaining])
        return 0

    monkeypatch.setattr(db_router, "_auto_init", lambda *_a, **_k: None)
    monkeypatch.setattr(db_router, "_probe_schema_or_remediate", lambda _argv: None)
    monkeypatch.setattr(db_router, "_dispatch_python_module", _fake_dispatch)

    rc, err = _run_router(router_argv)

    assert rc == 0
    assert "unknown domain" not in err
    assert captured == [["yoke_core.cli.raw_query", "SELECT 1"]]
