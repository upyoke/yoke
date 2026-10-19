"""Consumer-owned declarations of producer contracts and their CI proof."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

from yoke_contracts.github_workflow_dispatch import WORKFLOW_DISPATCH_CORRELATION_INPUT
from yoke_core.domain import json_helper

CAPABILITY_TYPE = "consumer-proof"


class ProducerProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_paths: list[str] = Field(min_length=1)
    workflow: str = Field(min_length=1)
    candidate_input: str = Field(default="product_ref", min_length=1)
    inputs: dict[str, str] = Field(default_factory=dict)

    @field_validator("contract_paths")
    @classmethod
    def valid_paths(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or value.startswith("/") or ".." in PurePosixPath(value).parts:
                raise ValueError(
                    "contract_paths must be nonempty repository-relative globs"
                )
        return values

    @field_validator("candidate_input")
    @classmethod
    def candidate_is_not_correlation(cls, value: str) -> str:
        if value == WORKFLOW_DISPATCH_CORRELATION_INPUT:
            raise ValueError("candidate_input must not replace the correlation input")
        return value

    def touches(self, paths: list[str]) -> bool:
        return any(
            fnmatch.fnmatchcase(path, pattern)
            for path in paths
            for pattern in self.contract_paths
        )


class ConsumerProofPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    producers: dict[str, ProducerProof]

    @field_validator("producers")
    @classmethod
    def valid_producers(
        cls, values: dict[str, ProducerProof]
    ) -> dict[str, ProducerProof]:
        for producer, proof in values.items():
            if not producer.strip():
                raise ValueError("producer project must be named")
            reserved = {proof.candidate_input, WORKFLOW_DISPATCH_CORRELATION_INPUT}
            if reserved.intersection(proof.inputs) or any(
                not value.strip() for value in proof.inputs.values()
            ):
                raise ValueError(
                    "inputs must be nonempty and must not set candidate or correlation inputs"
                )
        return values


def parse_settings(raw: str) -> ConsumerProofPolicy:
    return ConsumerProofPolicy.model_validate(json_helper.loads_text(raw))


def validate_json_string(raw: str) -> str:
    return json_helper.dumps_compact(parse_settings(raw).model_dump())
