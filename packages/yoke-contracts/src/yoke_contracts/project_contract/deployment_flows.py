"""Shared project-owned deployment-flow declaration constants."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DECLARATION_SCHEMA = 1
DECLARATION_RELATIVE_PATH = ".yoke/deployment-flows.json"
EMPTY_DECLARATION_TEXT = """{
  "schema": 1,
  "flows": []
}
"""


class DeploymentFlowDeclaration(BaseModel):
    """Locally verifiable shape for one desired deployment flow."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    description: str = ""
    stages: list[dict[str, Any]] = Field(min_length=1)
    on_failure: str = "halt"
    target_env: str | None = None
    done_description: str | None = None
    status: Literal["active", "disabled"] = "active"


class DeploymentFlowDeclarationDocument(BaseModel):
    """Repository declaration shape validated before checkout mutation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schema")
    flows: list[DeploymentFlowDeclaration]
    default_flow: str | None = None
    retire_if_present: list[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
    ] = Field(default_factory=list)


def validate_declaration_shape(payload: object) -> None:
    """Fail before local writes when a repository declaration is malformed."""
    validated = DeploymentFlowDeclarationDocument.model_validate(payload)
    if "default_flow" in validated.model_fields_set and not validated.default_flow:
        raise ValueError("default_flow must be a non-empty string when present")


__all__ = [
    "DECLARATION_RELATIVE_PATH",
    "DECLARATION_SCHEMA",
    "DeploymentFlowDeclaration",
    "DeploymentFlowDeclarationDocument",
    "EMPTY_DECLARATION_TEXT",
    "validate_declaration_shape",
]
