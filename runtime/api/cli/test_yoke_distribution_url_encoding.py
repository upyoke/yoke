"""Public distribution URL encoding regression tests."""

from __future__ import annotations

import hashlib

import pytest

from yoke_core.tools import distribution_publish


def _records(filename: str, *, size: int | None = None) -> list[dict[str, object]]:
    record: dict[str, object] = {
        "project": "yoke-cli",
        "name": "yoke-cli",
        "filename": filename,
        "sha256": "a" * 64,
    }
    if size is not None:
        record["size"] = size
    return [record]


def test_distribution_publish_quotes_local_version_public_urls() -> None:
    checks = distribution_publish.build_url_checks(
        base_url="https://api.upyoke.com/dist/releases/0.2.0+gabc123/",
        records=_records("yoke_cli-0.2.0+gabc123-py3-none-any.whl"),
        index_url="https://api.upyoke.com/simple/",
        include_mutable=False,
    )
    urls = [check.url for check in checks]

    assert (
        "https://api.upyoke.com/dist/releases/0.2.0%2Bgabc123/wheels/"
        "yoke_cli-0.2.0%2Bgabc123-py3-none-any.whl"
    ) in urls
    assert (
        distribution_publish.main([
            "encode-url",
            "https://api.upyoke.com/dist/releases/0.2.0+gabc123/"
            "yoke-cli/",
        ])
        == 0
    )


def test_distribution_publish_checks_only_selected_mutable_channel() -> None:
    checks = distribution_publish.build_url_checks(
        base_url="https://api.stage.upyoke.com/dist/releases/0.2.0/",
        records=_records("yoke_cli-0.2.0-py3-none-any.whl"),
        index_url="https://api.stage.upyoke.com/simple/",
        include_mutable=True,
        mutable_channel="latest",
    )
    urls = {check.url for check in checks}

    assert "https://api.stage.upyoke.com/dist/channels/latest.json" in urls
    assert "https://api.stage.upyoke.com/dist/channels/stable.json" not in urls
    wheel_check = next(check for check in checks if check.url.endswith(".whl"))
    assert wheel_check.size is None


def test_distribution_publish_indexes_simple_pages_as_mutable() -> None:
    checks = distribution_publish.build_url_checks(
        base_url="https://api.upyoke.com/dist/releases/0.2.0/",
        records=_records("yoke_cli-0.2.0-py3-none-any.whl"),
        index_url="https://api.upyoke.com/simple/",
        include_mutable=True,
        mutable_channel="stable",
    )
    urls = {check.url: check for check in checks}

    assert urls["https://api.upyoke.com/simple/"].cache_control_contains == "max-age=60"
    assert (
        urls["https://api.upyoke.com/simple/yoke-cli/"].cache_control_contains
        == "max-age=60"
    )


def test_immutable_smoke_skips_simple_index_until_mutable_phase() -> None:
    # The simple index is published in the mutable phase, so the immutable smoke
    # must not verify it — checking /simple/ before that publish step 401s.
    checks = distribution_publish.build_url_checks(
        base_url="https://api.upyoke.com/dist/releases/0.2.0/",
        records=_records("yoke_cli-0.2.0-py3-none-any.whl"),
        index_url="https://api.upyoke.com/simple/",
        include_mutable=False,
    )
    urls = {check.url for check in checks}

    assert "https://api.upyoke.com/simple/" not in urls
    assert "https://api.upyoke.com/simple/yoke-cli/" not in urls
    # immutable wheels are still verified in this phase
    assert any(url.endswith(".whl") for url in urls)


def test_distribution_publish_public_smoke_checks_manifest_sizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"wheel-bytes"
    check = distribution_publish.UrlCheck(
        "https://api.upyoke.com/dist/releases/v1/wheels/yoke_cli.whl",
        sha256=hashlib.sha256(body).hexdigest(),
        size=len(body) + 1,
    )

    monkeypatch.setattr(
        distribution_publish,
        "_get_url",
        lambda *_args, **_kwargs: ({}, body),
    )

    with pytest.raises(ValueError, match="size 11 does not match 12"):
        distribution_publish.verify_urls([check])


def test_distribution_publish_wheel_checks_include_record_size() -> None:
    checks = distribution_publish.build_url_checks(
        base_url="https://api.upyoke.com/dist/releases/0.2.0/",
        records=_records("yoke_cli-0.2.0-py3-none-any.whl", size=123),
        index_url="https://api.upyoke.com/simple/",
        include_mutable=False,
    )

    wheel_check = next(check for check in checks if check.url.endswith(".whl"))
    assert wheel_check.size == 123


def test_distribution_publish_mutable_checks_require_channel() -> None:
    try:
        distribution_publish.build_url_checks(
            base_url="https://api.upyoke.com/dist/releases/0.2.0/",
            records=_records("yoke_cli-0.2.0-py3-none-any.whl"),
            index_url="https://api.upyoke.com/simple/",
            include_mutable=True,
        )
    except ValueError as exc:
        assert "mutable_channel must be stable or latest" in str(exc)
    else:
        raise AssertionError("mutable checks should require a channel")
