"""Bounded, pure semantic checks for literal QA teaching examples.

Only literal steps and explicitly marked machine capability code spans are
checked. Project policy, provisioned hosts and dynamic/file/stdin payloads
remain unverifiable here; this module never resolves live configuration.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from typing import Callable

from yoke_contracts.browser_step_schema import step_schema_violation
from yoke_contracts.machine_config.capability_secrets import TEST_MACHINE_CAPABILITY
from yoke_contracts.machine_config.test_machine import is_test_machine_capability_type


@dataclass(frozen=True)
class SemanticProbe:
    status: str
    detail: str | None = None


def _normalize_values(value, normalize: Callable[[str], str]):
    if isinstance(value, str):
        # CSS attribute selectors are data, not optional command grammar.
        return (
            normalize(value)
            if re.search(r"<[^<>]+>|\$[\w{]|\{[\w-]+\}", value)
            else value
        )
    if isinstance(value, list):
        return [_normalize_values(child, normalize) for child in value]
    if isinstance(value, dict):
        return {
            key: _normalize_values(child, normalize) for key, child in value.items()
        }
    return value


def probe_recipe(recipe: str, normalize: Callable[[str], str]) -> SemanticProbe:
    """Validate original JSON before parser placeholder normalization loses it."""
    if not any(flag in recipe for flag in ("--method-config", "--success-policy")):
        return SemanticProbe("not_applicable")
    try:
        argv = shlex.split(re.sub(r"\\{1,2}\s+", " ", recipe))
    except ValueError:
        return SemanticProbe(
            "unverifiable", "incomplete quoted payload; supply a complete literal"
        )
    payloads = []
    for index, token in enumerate(argv):
        if token in {"--method-config", "--success-policy"}:
            payloads.append(argv[index + 1] if index + 1 < len(argv) else "")
        elif token.startswith(("--method-config=", "--success-policy=")):
            payloads.append(token.split("=", 1)[1])
    checked = False
    for raw in payloads:
        if not raw.startswith(("{", "[")):
            return SemanticProbe(
                "unverifiable",
                "dynamic or policy payload; requires live authoring validation",
            )
        try:
            value = json.loads(raw)
        except ValueError as exc:
            return SemanticProbe(
                "invalid", f"qa_example_json_invalid: {exc}; repair the literal JSON"
            )
        steps = value.get("steps") if isinstance(value, dict) else value
        if steps is None:
            continue
        if not isinstance(steps, list):
            return SemanticProbe(
                "invalid", "qa_example_steps_invalid: steps must be an array"
            )
        for index, step in enumerate(_normalize_values(steps, normalize)):
            if not isinstance(step, dict):
                return SemanticProbe(
                    "invalid",
                    f"qa_example_steps_invalid: step {index} must be an object",
                )
            violation = step_schema_violation(index, step)
            if violation:
                return SemanticProbe(
                    "invalid", f"{violation.code}: {violation.message}"
                )
        checked = True
    if checked:
        return SemanticProbe(
            "validated",
            "step schema only; project policy and method admission remain unverifiable",
        )
    return SemanticProbe(
        "unverifiable",
        "no literal browser steps; configuration requires its authoring contract",
    )


_CAPABILITY_EXAMPLE = re.compile(r"<!-- qa:test-machine-capability -->\s*`([^`]+)`")


def capability_example_errors(text: str, normalize: Callable[[str], str]) -> list[str]:
    """Read marked code values, never infer capability types from English prose."""
    errors = []
    for match in _CAPABILITY_EXAMPLE.finditer(text):
        value = normalize(match[1])
        if value != TEST_MACHINE_CAPABILITY and not is_test_machine_capability_type(
            value
        ):
            line = text[: match.start()].count("\n") + 1
            errors.append(
                f"{line}: qa_example_capability_invalid: {match[1]!r}; use the declared test machine capability type"
            )
    return errors
