# Session registration outcomes

Every registration attempt returns `registered`, `exists`, `skipped:<reason>`,
or `refused:<code>`. The relay response exposes `registration_outcome`.
A refusal adds `session_registration_refused:<code>` to `degraded`, prints
recovery on client stderr, and emits `SessionRegistrationRefused` with the
code, reason and recovery. Registration stays fail-open: it never changes
the policy decision or hook exit code. A duplicate is `exists` only when
the row exists; other integrity failures name the violated constraint.
A hook from a retired project's checkout refuses as
`refused:SESSION_PROJECT_RETIRED`, naming `yoke projects unretire` as recovery.

The authoritative registration transaction stamps `first_user_prompt_at`
on `UserPromptSubmit`, including an existing row and a retry after orientation
has already been delivered. The filesystem orientation marker and telemetry
are independent of this durable fact. A short answer without tools is still
a conversation. Roster reads hide startup probes; `yoke sessions get SESSION`
returns their audit row with `probe: true` and the first-prompt stamp.
Codex's transcript manifest declares `session_start: transcript_required`;
a start without its transcript reports `skipped:unsaved_transcript`.
A prompt is proof of a conversation even before that transcript is saved.

## Terminal-hook prompt recovery

A `UserPromptSubmit` that never reaches the authority (for example a
resident timeout) leaves no stamp, so a real conversation reads as a probe.
`Stop` and `SessionEnd` recover it. On harnesses whose transcript manifest
declares `prompt_attestation: claude_user_rows`, the client reads this exact
session's transcript and ships `_yoke_client_first_user_prompt` with the
session id and the native timestamp of its first operator prompt. Prompt text
never leaves the machine. Meta, sidechain, compact-summary, local-command
output and tool-result rows do not count. The read is bounded.

The authority policy `yoke_core.hooks.session_prompt_attestation` stamps
`first_user_prompt_at` write-once on an existing row only. It never registers,
revives or ends a session, so an ended row stays ended and a true probe stays
unstamped. A fact naming another session is ignored. A missing row or bad
instant refuses as `SESSION_PROMPT_STAMP_REFUSED`: `SessionRegistrationRefused`
records it, stderr shows the `session_prompt_attestation` failure marker, and the
hook still allows. Codex and Cursor declare `prompt_attestation: deferred` with
the reason in `prompt_attestation_evidence`.

