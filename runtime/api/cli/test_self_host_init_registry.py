"""Self-host initialization registration and published image pins."""

from yoke_cli.commands import self_host as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_contracts.server_image import (
    PUBLISHED_SERVER_IMAGE_REPOSITORY,
    pinned_server_image,
)


def test_published_image_pin_shape():
    image = pinned_server_image("0.2.0.202610140334")
    assert image == f"{PUBLISHED_SERVER_IMAGE_REPOSITORY}:0.2.0.202610140334"
    assert PUBLISHED_SERVER_IMAGE_REPOSITORY.startswith("ghcr.io/")


def test_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["self-host", "init", "--json"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is commands.self_host_init
    assert remaining == ["--json"]
