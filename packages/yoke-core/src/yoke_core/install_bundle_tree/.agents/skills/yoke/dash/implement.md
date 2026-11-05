# Dash — implement

Make the smallest complete change. No change needed: survey `--no-changes`, then [close-out](close-out.md#laneless). Next: [verify](verify.md).

For an operator decision, ask the live steering seat through `yoke say --steering`
with the question, context, options and recommendation. Without a live seat, file
`yoke decision-requests ask --key SLUG --question TEXT` directly. Do not wait on
a harness prompt tool; continue other in-scope work or end the turn. The answer
arrives as Fleet mail. Read `.yoke/docs/sessions/inbox.md#operator-questions`;
use `decision-requests list --mine` for history, `withdraw ID --reason TEXT` to
cancel your stale question, or `ask --replaces ID` to replace it without editing.

Use plain language, give the context needed to decide, name things in words (any id follows the name in parentheses), and keep the question very short.
