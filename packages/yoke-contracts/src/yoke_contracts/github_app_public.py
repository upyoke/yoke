"""Public, nonsecret GitHub App advertisement wire contract."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from yoke_contracts.github_origin import validate_github_endpoint_pair


GITHUB_APP_CLIENT_ID_ENV = "YOKE_GITHUB_APP_CLIENT_ID"
GITHUB_APP_SLUG_ENV = "YOKE_GITHUB_APP_SLUG"
GITHUB_APP_ID_ENV = "YOKE_GITHUB_APP_ID"
GITHUB_APP_API_URL_ENV = "YOKE_GITHUB_APP_API_URL"
GITHUB_APP_WEB_URL_ENV = "YOKE_GITHUB_APP_WEB_URL"


class GitHubAppUnavailable(BaseModel):
    """Detail-free response when this control plane advertises no product App."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: Literal[False] = False


class GitHubAppPublicProfile(BaseModel):
    """Complete public identity needed for browser/device authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: Literal[True] = True
    client_id: str
    app_slug: str
    app_id: int = Field(gt=0)
    api_url: str
    web_url: str

    @field_validator("client_id")
    @classmethod
    def _safe_client_id(cls, value: str) -> str:
        selected = str(value or "").strip()
        if not selected or any(
            character.isspace() or ord(character) < 0x20 for character in selected
        ):
            raise ValueError("client_id must be a nonempty public identifier")
        return selected

    @field_validator("app_slug")
    @classmethod
    def _safe_app_slug(cls, value: str) -> str:
        selected = str(value or "").strip()
        if not selected:
            raise ValueError("app_slug must be nonempty")
        return selected

    @field_validator("app_id", mode="before")
    @classmethod
    def _non_boolean_app_id(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("app_id must be a positive integer")
        return value

    @model_validator(mode="after")
    def _canonical_deployment(self) -> "GitHubAppPublicProfile":
        pair = validate_github_endpoint_pair(self.api_url, self.web_url)
        pair.app_install_url(self.app_slug)
        object.__setattr__(self, "api_url", pair.api.base_url)
        object.__setattr__(self, "web_url", pair.web.base_url)
        return self


GitHubAppAdvertisement = Annotated[
    Union[GitHubAppUnavailable, GitHubAppPublicProfile],
    Field(discriminator="available"),
]

_ADVERTISEMENT_ADAPTER = TypeAdapter(GitHubAppAdvertisement)


def parse_github_app_advertisement(
    value: object,
) -> GitHubAppUnavailable | GitHubAppPublicProfile:
    """Validate one exact health-wire advertisement variant."""
    return _ADVERTISEMENT_ADAPTER.validate_python(value)


__all__ = [
    "GITHUB_APP_API_URL_ENV",
    "GITHUB_APP_CLIENT_ID_ENV",
    "GITHUB_APP_ID_ENV",
    "GITHUB_APP_SLUG_ENV",
    "GITHUB_APP_WEB_URL_ENV",
    "GitHubAppAdvertisement",
    "GitHubAppPublicProfile",
    "GitHubAppUnavailable",
    "parse_github_app_advertisement",
]
