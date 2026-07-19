"""Remote-transport probes for the product-wheel no-checkout smoke."""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.tools.checkout_clean_room_smoke_helpers import CommandResult, tail


STEP_NETWORK_UNREACHABLE = "network_unreachable_failure"
STEP_PACKS_LIST_PRODUCT = "packs_list_product_client"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"

ENV_OFFLINE = "offline"
UNREACHABLE_API_URL = "https://127.0.0.1:1"
TRANSPORT_FAILED_CODE = "https_transport_failed"

StepRunner = Callable[[list, str], CommandResult]


def step_network_unreachable(ctx: Any, run: StepRunner) -> dict[str, Any]:
    failures: list[str] = []
    connection = run(
        [str(ctx.yoke), "connection", "set", ENV_OFFLINE,
         "--transport", "https", "--api-url", UNREACHABLE_API_URL,
         "--token-file", str(ctx.token_path)],
        STEP_NETWORK_UNREACHABLE,
    )
    if connection.returncode != 0:
        failures.append(
            f"connection set failed with {connection.returncode}: "
            f"{tail(connection.stderr)}"
        )
    query = run(
        [str(ctx.yoke), "--env", ENV_OFFLINE,
         "events", "query", "--limit", "1", "--json"],
        STEP_NETWORK_UNREACHABLE,
    )
    failures.extend(_expect_nonzero(query))
    if TRANSPORT_FAILED_CODE not in _combined_output(query):
        failures.append(
            f"output did not carry the typed {TRANSPORT_FAILED_CODE!r} envelope"
        )
    return _step_entry(STEP_NETWORK_UNREACHABLE, failures, {
        "returncode": query.returncode,
        "stdout_tail": tail(query.stdout),
        "stderr_tail": tail(query.stderr),
    })


def step_packs_list_product_client(
    ctx: Any, run: StepRunner
) -> dict[str, Any]:
    result = run(
        [str(ctx.yoke), "--env", ENV_OFFLINE,
         "packs", "list", "--project", "1", "--json"],
        STEP_PACKS_LIST_PRODUCT,
    )
    failures = _expect_nonzero(result)
    output = _combined_output(result)
    if TRANSPORT_FAILED_CODE not in output:
        failures.append(
            f"packs list output did not carry {TRANSPORT_FAILED_CODE!r}"
        )
    for forbidden in ("ModuleNotFoundError", "No module named", "Traceback"):
        if forbidden in output:
            failures.append(
                f"packs list leaked an import/runtime traceback: {forbidden}"
            )
    return _step_entry(STEP_PACKS_LIST_PRODUCT, failures, {
        "returncode": result.returncode,
        "stdout_tail": tail(result.stdout),
        "stderr_tail": tail(result.stderr),
    })


def _step_entry(
    step: str,
    failures: list[str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {"step": step, "status": STATUS_FAIL if failures else STATUS_PASS,
            "failures": list(failures), "evidence": evidence}


def _expect_nonzero(result: CommandResult) -> list[str]:
    if result.returncode == 0:
        return [f"{result.step}: expected a non-zero exit, got 0"]
    return []


def _combined_output(result: CommandResult) -> str:
    return f"{result.stdout}\n{result.stderr}"
