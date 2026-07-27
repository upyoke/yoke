from __future__ import annotations

from importlib.resources import files


def _asset(name: str) -> str:
    return files("yoke_core.ui").joinpath("static", name).read_text(encoding="utf-8")


def _assets(*names: str) -> str:
    return "\n".join(_asset(name) for name in names)


def test_shared_content_styles_only_signal_interactive_rows() -> None:
    source = _asset("universe_content.css")

    assert ".panel:hover" not in source
    assert ".panel-body:has(> table.items)" in source
    assert "overflow-x: auto" in source
    assert "tr:has(a.row-link):hover" in source
    assert "tr:has(td):hover" not in source
    assert ".mono {" in source
    assert ".ago {" in source


def test_item_breakpoints_keep_issue_and_generic_geometry_distinct() -> None:
    source = _assets(
        "item_foundations.css",
        "item_roster.css",
        "item_details.css",
        "item_intake.css",
    )

    assert ("grid-template-columns: minmax(0, 1.55fr) minmax(260px, 0.75fr)") in source
    assert "grid-template-columns: minmax(0, 0.445fr) minmax(0, 1fr)" in source
    assert "@media (max-width: 1080px)" in source
    assert ".issue-detail .item-detail-grid" in source
    assert "@media (max-width: 860px)" in source
    assert "textarea.item-form-control" in source
    assert "min-height: 64px" in source
    assert "repeat(auto-fit, minmax(145px, 1fr))" in source


def test_workflow_and_intake_styles_keep_prototype_geometry() -> None:
    workflow = _assets(
        "workflows.css",
        "workflow_controls.css",
        "workflow_mechanics.css",
    )
    for fragment in (
        "margin: -2px 0 0",
        "padding: 7px 13px",
        "grid-template-columns: repeat(auto-fit, minmax(145px, 1fr))",
        "grid-template-columns: 18px minmax(0, 1fr) auto",
        "width: min(100%, 480px)",
        "width: min(100%, 460px)",
        "@media (max-width: 560px)",
    ):
        assert fragment in workflow

    intake = _asset("item_intake.css")
    for fragment in (
        "max-width: 720px",
        "gap: 18px",
        "padding: 6px 9px",
        "height: 64px",
        "width: 30px",
        "max-width: 210px",
        "min-width: 150px",
        "@media (max-width: 640px)",
    ):
        assert fragment in intake


def test_test_machine_detail_keeps_prototype_geometry() -> None:
    source = _asset("test_machine.css")

    for fragment in (
        "grid-template-columns: minmax(0, 1.55fr) minmax(260px, .75fr)",
        "grid-template-columns: repeat(auto-fit, minmax(145px, 1fr))",
        "grid-template-columns: 170px minmax(0, 1fr)",
        "height: 5px",
        "width: 58%",
        "padding: 10px 11px",
        "padding: 9px 11px",
        "width: 30px",
        ".test-machine-head .muted",
        ".test-machine-baseline-explanation",
        "max-height: calc(100vh - 18px)",
        "font-size: 15px",
        "font-size: 11.5px",
        "min-width: 220px",
        "margin-top: 14px",
        "@media (max-width: 780px)",
    ):
        assert fragment in source


def test_item_stylesheet_imports_stay_in_visual_dependency_order() -> None:
    source = _asset("items.css")
    imports = (
        "item_foundations.css",
        "item_roster.css",
        "item_details.css",
        "item_intake.css",
    )

    positions = [source.index(name) for name in imports]
    assert positions == sorted(positions)


def test_inbox_uses_the_production_theme_contract() -> None:
    source = _asset("inbox.css")

    for legacy_name in (
        "--muted",
        "--border",
        "--panel",
        "--bg",
        "--ink-2",
        "--accent",
        "--crit",
    ):
        assert f"var({legacy_name})" not in source
    assert "var(--yoke-muted)" in source
    assert ".inbox-panels" in source
    assert "gap: 14px" in source
    assert ".panel-body.inbox-stack" in source
    assert "border-bottom: 1px solid var(--yoke-border)" in source
    assert "background: var(--yoke-accent-weak)" in source


def test_strategy_document_is_bounded_for_review() -> None:
    source = _asset("strategy.css")

    assert ".strategy-document" in source
    assert "max-height: 420px" in source
    assert "overflow: auto" in source
    assert "height: 34px" in source
    assert ".strategy-spark-bar" not in source
    assert ("grid-template-columns: minmax(0, 1.55fr) minmax(260px, 0.75fr)") in source


def test_production_views_do_not_render_prototype_annotations() -> None:
    for name in (
        "universe_views_items.js",
        "item_view_details.js",
        "universe_views_blitz.js",
        "universe_views_strategy.js",
        "universe_views_inbox.js",
    ):
        source = _asset(name)
        assert "FUT(" not in source
        assert "Proposed Data Shape" not in source
