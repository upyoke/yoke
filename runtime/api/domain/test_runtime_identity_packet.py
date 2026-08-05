"""Canonical runtime-identity packet for status and universe hosts."""

from __future__ import annotations

import os

from yoke_contracts.install_binding import KIND_SOURCE_CHECKOUT
from yoke_contracts.runtime_identity import (
    INSTALL_KIND_HOSTED_PIN,
    PORTABILITY_HOSTED,
    PORTABILITY_LOCAL,
    SOURCE_VERSION_LABEL,
    build_runtime_identity,
    mount_fields,
)


def test_build_runtime_identity_uses_install_and_honest_source_fallback(
    monkeypatch,
) -> None:
    monkeypatch.delenv("YOKE_BUILD_SHA", raising=False)
    packet = build_runtime_identity(
        install={"kind": KIND_SOURCE_CHECKOUT, "version": ""},
        portability_mode=PORTABILITY_LOCAL,
    )
    assert packet["version"] == SOURCE_VERSION_LABEL
    assert packet["install_kind"] == KIND_SOURCE_CHECKOUT
    assert packet["build"] == ""
    assert packet["environment_label"] == "local universe"
    assert packet["portability_mode"] == PORTABILITY_LOCAL


def test_build_runtime_identity_keeps_build_sha_and_explicit_version(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_BUILD_SHA", "deadbeefcafebabe")
    packet = build_runtime_identity(
        version="v9.4.1",
        install={"kind": "packaged_wheel", "version": "v9.4.1"},
        portability_mode=PORTABILITY_HOSTED,
        environment_label="hosted universe",
    )
    assert packet == {
        "version": "v9.4.1",
        "install_kind": "packaged_wheel",
        "build": "deadbeefcafebabe",
        "environment_label": "hosted universe",
        "portability_mode": PORTABILITY_HOSTED,
    }
    fields = mount_fields(packet)
    assert fields["versionLabel"] == "v9.4.1"
    assert fields["environmentLabel"] == "hosted universe"
    assert fields["runtimeIdentity"]["installKind"] == "packaged_wheel"
    assert fields["runtimeIdentity"]["build"] == "deadbeefcafebabe"
    assert "YOKE_BUILD_SHA" in os.environ


def test_hosted_pin_install_kind_constant() -> None:
    packet = build_runtime_identity(
        version="release-pin",
        install={"kind": INSTALL_KIND_HOSTED_PIN, "version": "release-pin"},
        portability_mode=PORTABILITY_HOSTED,
    )
    assert packet["install_kind"] == INSTALL_KIND_HOSTED_PIN
