"""Generate the wheel's versioned machine sign-in JSON Schema from its models."""

from __future__ import annotations

import argparse
import json
from importlib.resources import files

from pydantic.json_schema import models_json_schema

from yoke_contracts.machine_authorization import (
    START_PATH,
    POLL_PATH,
    POLL_OUTCOMES,
    RETRYABLE_POLL_ERRORS,
    MachineAuthorizationStart,
    MachineAuthorizationPoll,
    MachineAuthorizationStarted,
    MachineAuthorizationApproved,
    MachineAuthorizationRefused,
)

SCHEMA_RESOURCE = "machine_authorization.schema.v1.json"


def generate_schema() -> dict:
    models = dict.fromkeys(
        [
            MachineAuthorizationStart,
            MachineAuthorizationPoll,
            MachineAuthorizationStarted,
            MachineAuthorizationApproved,
            MachineAuthorizationRefused,
            *(model for _, model in POLL_OUTCOMES.values()),
        ]
    )
    _, schema = models_json_schema([(model, "validation") for model in models])
    schema.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:yoke:machine-authorization:v1",
            "title": "Machine sign-in requests and responses",
            "x-http": {
                "start": {
                    "path": START_PATH,
                    "request": {
                        "self-host": "MachineAuthorizationStart",
                        "cloud": None,
                    },
                    "success": {"status": 200, "body": "MachineAuthorizationStarted"},
                    "refusal": "MachineAuthorizationRefused",
                },
                "poll": {
                    "path": POLL_PATH,
                    "request": "MachineAuthorizationPoll",
                    "success": {"status": 200, "body": "MachineAuthorizationApproved"},
                    "outcomes": {
                        error: {
                            "status": status,
                            "body": model.__name__,
                            "retryable": RETRYABLE_POLL_ERRORS.get(status) == error
                            or status == 429,
                        }
                        for error, (status, model) in POLL_OUTCOMES.items()
                    },
                    "refusal": "MachineAuthorizationRefused",
                },
                "retry-after": {
                    "status": 429,
                    "header": "Retry-After",
                    "format": "delay-seconds or HTTP-date",
                    "invalid_or_missing": "use the authorization poll interval",
                },
            },
        }
    )
    return schema


def schema_text() -> str:
    return json.dumps(generate_schema(), sort_keys=True, separators=(",", ":")) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    resource = files("yoke_contracts").joinpath(SCHEMA_RESOURCE)
    expected = schema_text()
    if args.check:
        if resource.read_text(encoding="utf-8") != expected:
            parser.exit(
                1,
                "machine_authorization_schema_drift: regenerate with python3 -m "
                "yoke_contracts.machine_authorization_schema and commit the schema\n",
            )
    else:
        resource.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
