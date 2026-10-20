# Shepherd — PM and Design

```bash
yoke readiness prd-validate "$_item_ref"
_pm_input_dir=$(yoke scratch dispatch-inputs "$_item_ref" "$_session_id" "$_attempt")
_pm_input_path="${_pm_input_dir}/product-manager-spec.md"
printf '%s' "$_pre_pm_spec" >"$_pm_input_path"
```
Validation exit 1 dispatches product-manager with that file; its spec needs
`## Definition of Done` with Project, Flow, Rationale. Output under 60% of a
baseline over 200 bytes sets _pm_destructive_rewrite=1: NOT_READY, no write;
else `yoke items structured-field replace` the spec and read it back.

Dispatch product-designer only for real interactive UI with no
`design_spec`, naming its input file; else persist a designer `SKIPPED`
verdict with its rationale.
```bash
printf '%s' "$_pre_designer_spec" >"${_pm_input_dir}/product-designer-spec.md"
```
