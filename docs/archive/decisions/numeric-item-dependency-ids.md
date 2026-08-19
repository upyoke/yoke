# Item dependency endpoints are integer foreign keys

`item_dependencies` stores `dependent_item_id` and `blocking_item_id` as
integer foreign keys to `items.id`. Public `PREFIX-N` remains the API and
display token.

A formatted text ref made two failures cheap: a well-formed string could
name the wrong item once `project_sequence` diverged from `items.id`, and
nothing stopped a string that named no item at all. An integer foreign key
makes both unrepresentable.

Unresolved text values (orphans) cannot become foreign keys. The cutover
reports every such row and drops it. Direction, `coordination_only`,
satisfaction, and uniqueness on `(dependent, blocking, gate_point)` are
unchanged.
