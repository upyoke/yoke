"""Concurrency contract for cluster-global PostgreSQL role tests."""

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import threading

from runtime.api.fixtures import pg_testdb


_CLUSTER_ROLE_MUTATION = re.compile(
    r"\b(?:CREATE|ALTER|DROP)\s+ROLE\b", re.IGNORECASE,
)


def test_cluster_role_authority_is_mutually_exclusive():
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_holder():
        with pg_testdb.cluster_role_authority():
            first_entered.set()
            assert release_first.wait(timeout=5)

    def second_holder():
        assert first_entered.wait(timeout=5)
        with pg_testdb.cluster_role_authority():
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_holder)
        second = executor.submit(second_holder)
        assert first_entered.wait(timeout=5)
        assert not second_entered.wait(timeout=0.2)
        release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)

    assert second_entered.is_set()


def test_cluster_role_mutations_request_authority_fixture():
    runtime_api = Path(__file__).resolve().parents[1]
    unprotected = []
    for path in runtime_api.rglob("test_*.py"):
        module = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(module):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            mutates_roles = any(
                isinstance(candidate, ast.Constant)
                and isinstance(candidate.value, str)
                and _CLUSTER_ROLE_MUTATION.search(candidate.value)
                for candidate in ast.walk(node)
            )
            parameters = {
                argument.arg
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
            }
            if mutates_roles and "cluster_role_authority" not in parameters:
                unprotected.append(f"{path.relative_to(runtime_api)}::{node.name}")

    assert unprotected == []
