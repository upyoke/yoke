"""Shared project-owned deployment-flow declaration constants."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DECLARATION_SCHEMA = 3
DECLARATION_RELATIVE_PATH = ".yoke/deployment-flows.json"
EMPTY_DECLARATION_TEXT = """{
  "schema": 3,
  "flows": []
}
"""

#: Closed vocabulary for what kind of target a flow deploys to.
#: ``persistent`` names a registered environment row and requires
#: ``target_environment_id``; ``ephemeral`` deploys per-run preview
#: substrate from unmerged branches; ``None`` marks merge-only flows
#: with no deploy target.
TARGET_TIER_PERSISTENT = "persistent"
TARGET_TIER_EPHEMERAL = "ephemeral"
VALID_TARGET_TIERS = (TARGET_TIER_PERSISTENT, TARGET_TIER_EPHEMERAL)


class DeploymentFlowDeclaration(BaseModel):
    """Locally verifiable shape for one desired deployment flow."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    description: str = ""
    stages: list[dict[str, Any]] = Field(min_length=1)
    on_failure: str = "halt"
    target_tier: Literal["persistent", "ephemeral"] | None = None
    target_environment_id: str | None = None
    done_description: str | None = None
    status: Literal["active", "disabled"] = "active"

    @model_validator(mode="after")
    def _tier_matches_environment(self) -> "DeploymentFlowDeclaration":
        if (self.target_tier == TARGET_TIER_PERSISTENT) != bool(
            self.target_environment_id
        ):
            raise ValueError(
                "target_environment_id is required exactly when "
                "target_tier='persistent'"
            )
        return self


class DeploymentFlowDeclarationDocument(BaseModel):
    """Repository declaration shape validated before checkout mutation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[3] = Field(alias="schema")
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
    "TARGET_TIER_EPHEMERAL",
    "TARGET_TIER_PERSISTENT",
    "VALID_TARGET_TIERS",
    "validate_declaration_shape",
]
