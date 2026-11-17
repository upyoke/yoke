# Session registration outcomes

Every registration attempt returns `registered`, `exists`, `skipped:<reason>`,
or `refused:<code>`. The relay response exposes `registration_outcome`.
A refusal adds `session_registration_refused:<code>` to `degraded`, prints
recovery on client stderr, and emits `SessionRegistrationRefused` with the
code, reason and recovery. Registration stays fail-open: it never changes
the policy decision or hook exit code. A duplicate is `exists` only when
the row exists; other integrity failures name the violated constraint.

The authoritative registration transaction stamps `first_user_prompt_at`
on `UserPromptSubmit`, including an existing row and a retry after orientation
has already been delivered. The filesystem orientation marker and telemetry
are independent of this durable fact. A short answer without tools is still
a conversation. Roster reads hide startup probes; `yoke sessions get SESSION`
returns their audit row with `probe: true` and the first-prompt stamp.
Codex's transcript manifest declares `session_start: transcript_required`;
a start without its transcript reports `skipped:unsaved_transcript`.
A prompt is proof of a conversation even before that transcript is saved.

