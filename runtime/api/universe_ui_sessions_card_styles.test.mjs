// Style contracts the session card and its grid row depend on.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Sessions lease keys share the mono typeface of item refs", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(css, /\.session-lease-key,/);
});

function sessionCss(name) {
  return readFileSync(new URL(
    `../../packages/yoke-core/src/yoke_core/ui/static/${name}`,
    import.meta.url,
  ), "utf8");
}

test("Session cards contain variable text and stretch to their grid row", () => {
  const css = sessionCss("universe_sessions.css");
  // A row of peers reads as a row only when the cards end on one line, which
  // is the grid's own default: the card must not opt back out of it.
  assert.match(
    sessionCss("universe_secondary_activity.css"),
    /\.session-grid \{[^}]*display: grid;/,
  );
  assert.ok(
    !/\.session-card \{[^}]*align-self/.test(css),
    "cards must inherit the grid's per-row stretch, not align to start",
  );
  assert.match(css, /\.session-work > \* \{[^}]*overflow-wrap: anywhere;/);
  assert.match(css, /\.session-relay-machine \{[^}]*text-overflow: ellipsis;/);
});

test("The relay pill is sized by its machine name and capped, never grown", () => {
  const css = sessionCss("universe_sessions.css");
  const pill = css.match(/\.session-relay-pill \{([^}]*)\}/)[1];
  // Growing is what made a four-character name render as a full-width bar; the
  // cap is what keeps the long name truncating instead of overflowing.
  assert.ok(!/flex/.test(pill), "the pill must not claim spare row width");
  assert.match(pill, /max-width: \d+ch;/);
  assert.match(pill, /min-width: 0;/);
});
