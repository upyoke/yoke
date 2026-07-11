"""Fail-closed product-source requirements for item-less deploys."""

from __future__ import annotations

import pytest

from yoke_core.tools import watch_deploy


@pytest.mark.parametrize(
    "image_tag_args",
    (["--image-tag", "abc123"], ["--image-tag=abc123"]),
)
def test_itemless_deploy_without_product_src_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    image_tag_args: list[str],
) -> None:
    monkeypatch.setattr(
        watch_deploy._watch_runner,
        "run_watcher",
        lambda **kwargs: pytest.fail("run_watcher should not run"),
    )

    rc = watch_deploy.main(["--", "run-1", *image_tag_args])

    assert rc == 3
    err = capsys.readouterr().err
    assert "item-less environment deploys" in err
    assert "require --product-src" in err


def test_itemless_streaming_pair_without_product_src_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = watch_deploy.main(
        [
            "--print-streaming-pair",
            "--",
            "run-1",
            "--image-tag",
            "abc123",
        ]
    )

    assert rc == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "require --product-src" in captured.err
