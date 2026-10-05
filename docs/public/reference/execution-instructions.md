# Execution-instruction delivery

Operator instructions combine workflow/project scope with delivery settings.
`workflow.execution_instruction.create`, `.update`, and `.set_scope` accept
`before_creation`, `on_every_read`, `when_entering_stage` booleans and a
`stage_buckets` list. Omitted fields retain stored settings on edits; creation
and existing rows default to Before creation + On every read, with no stage targets.

At least one delivery point must be selected. When entering stage requires
at least one bucket: `idea`, `planning`, `refined`, `implementing`, `reviewing`,
`implemented`, or `release`. Invalid selections refuse with `delivery_invalid`
and name the selection to correct; invalid bucket names refuse as `payload_invalid`.
Targets come from the item's pinned workflow definition's `board_bucket`,
so custom stage ids work without being added to a separate instruction map.

In the dashboard's Workflows page, the Execution instructions panel shows each
instruction's delivery points and selected stage buckets beneath its scope.
Choose New instruction or Edit to change the three delivery checkboxes and
stage-bucket checkboxes. New instructions select Before creation + On every
read. Bucket controls are disabled until When entering stage is selected;
toggling it off keeps the draft's bucket choices. Saving requires at least one
delivery point and, for stage delivery, at least one bucket. An invalid draft
shows the required correction in the editor before any write is sent.

Before filing, read `yoke workflow execution-instruction resolve --workflow W
--project P --full`. Its default delivery point is `before_creation`; the
`--execution-instructions-considered` attestation covers only those instructions.
Creation receipts describe that same set. The web form uses the same resolver.

Individual item field, body, section-projection, and detail reads always attach
On every read instructions plus stage-entry instructions targeting the live
bucket, independent of whether narrative content was requested. A successful
`lifecycle.transition.execute` returns `execution_instructions` containing
stage-entry instructions for its entered bucket. Failed transitions return none.
Instructions remain separate from item content and never round-trip into it.

The resolve function also accepts `delivery_point` and `stage_bucket`. To inspect
stage delivery directly, run `yoke workflow execution-instruction resolve
--workflow W --project P --delivery-point when_entering_stage --stage-bucket
reviewing --full`; stage-entry resolution requires a bucket. `on_every_read`
includes stage targets when a bucket is supplied. Summary descriptors retain
the selection in their full-read command.

CLI writes expose `--before-creation` / `--no-before-creation`, `--on-every-read`
/ `--no-on-every-read`, and `--when-entering-stage` / `--no-when-entering-stage`.
Repeat `--stage-bucket BUCKET` to replace the target list; `--clear-stage-buckets`
clears it. Disable stage delivery in the same edit when clearing an enabled target.

```text
yoke workflow execution-instruction create --content "Run implementation checks." --no-before-creation --no-on-every-read --when-entering-stage --stage-bucket implementing
yoke workflow execution-instruction set-scope ID --all-workflows --all-projects
yoke workflow execution-instruction update ID --content "Run review checks." --stage-bucket reviewing
```

Read each operation's `--help` before changing scope or delivery. Delivery and
scope edits are validated together before replacing bindings; prose-only and
scope-only edits preserve the instruction's delivery settings.

The delivery columns converge additively on boot. Existing instruction rows
retain their prose and scope and acquire defaults; no data rewrite or separate
migration entry is required.
