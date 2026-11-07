## Path Tracing Beyond the Task

Before choosing tests, trace what the change really touches: the exports it
provides and consumes (names, argument and return types, optional fields), the
files, environment, services and working-directory assumptions it relies on,
and what downstream tasks expect of it. Record concerns under **Path Tracing**;
a concrete blocker fails the verdict, an informational warning does not.

## Prose-only changes

List the changed files with `git -C {worktree-path} diff main...HEAD
--name-only` (or the dispatched task baseline). Only when every file is
Markdown may you skip the executable suite; still check every criterion,
interface and doc, and run the contract tests that read those Markdown files.
Record the scope and the skipped suite under **Regression Analysis**. Any other
file needs test selection.

## Test commands and E2E

Prefer the dispatched test commands over guessed discovery, and record the
source of each command under **Test Commands Used**.

Run E2E only after unit and integration checks pass, and only with both a
preview URL and an E2E command; otherwise record which one is missing and skip.
Run the E2E command with `BASE_URL=<preview-url>`. A failing E2E run fails the
verdict; report failing test names, assertions and the paths of screenshots,
traces and videos.
