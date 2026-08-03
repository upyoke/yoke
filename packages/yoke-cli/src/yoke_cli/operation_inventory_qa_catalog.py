"""Operation inventory rows for QA methods, plans, and evidence reads."""

from yoke_cli.operation_inventory_model import _Row, _w


WRAPPED_ROWS: tuple[_Row, ...] = (
    _w("yoke qa method list", "qa.method"),
    _w("yoke qa method get", "qa.method"),
    _w("yoke qa project-method register", "qa.project_method"),
    _w("yoke qa plan list", "qa.plan"),
    _w("yoke qa plan get", "qa.plan"),
    _w("yoke qa activity list", "qa.activity"),
    _w("yoke qa plan create", "qa.plan"),
    _w("yoke qa plan edit", "qa.plan"),
    _w("yoke qa plan-cases replace", "qa.plan_cases"),
    _w("yoke qa project-default set", "qa.project_default"),
    _w("yoke qa project-default unset", "qa.project_default"),
    _w("yoke qa item-plan attach", "qa.item_plan"),
    _w("yoke qa plan materialize", "qa.plan"),
    _w("yoke qa plan rematerialize", "qa.plan"),
    _w("yoke qa artifact read", "qa.artifact"),
)


__all__ = ["WRAPPED_ROWS"]
