import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { sessionRosterFilters } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_roster_filters.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

const staticFile = (name) => readFileSync(new URL(
  `../../packages/yoke-core/src/yoke_core/ui/static/${name}`, import.meta.url,
), "utf8");

test("the Sessions toolbar is a search, four filters, and actions led by Clear", () => {
  const filters = sessionRosterFilters(new FakeDocument(), () => {});
  assert.deepEqual(
    filters.host.className.split(" "),
    ["session-roster-filters", "sessions-toolbar"],
  );
  // Clear rides with the roster actions, so no loose button sits between the
  // filters and the actions for the grid to place on its own.
  assert.deepEqual(
    filters.host.children.map((node) => node.className),
    [
      "session-roster-filter session-filter-search",
      "session-roster-filter", "session-roster-filter",
      "session-roster-filter", "session-roster-filter",
      "session-filter-actions",
    ],
  );
  assert.equal(filters.actions.children[0], byClass(filters.host, "session-filter-clear")[0]);
});

test("the toolbar grid fills every row edge to edge at each width", () => {
  assert.match(
    staticFile("universe_sessions.css"),
    /@import url\("\.\/universe_sessions_toolbar\.css"\);/,
  );
  const css = staticFile("universe_sessions_toolbar.css");
  // The page is the container: a grid cannot query its own width.
  assert.match(css, /\.sessions-view \{\s*container: sessions-view \/ inline-size;/);
  assert.match(
    css,
    /\.sessions-toolbar \{[^}]*display: grid;[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/,
  );
  // A select stops sizing to its longest option.
  assert.match(css, /\.sessions-toolbar \.session-filter-control \{[^}]*flex: 1 1 0;[^}]*min-width: 0;/);
  for (const tier of ["(max-width: 319px)", "(max-width: 479px)", "(min-width: 760px)", "(min-width: 900px)"]) {
    assert.ok(css.includes(`@container sessions-view ${tier}`), tier);
  }
  const wide = css.split("@container sessions-view (min-width: 760px)")[1];
  assert.match(wide, /grid-template-columns: repeat\(4, minmax\(0, 1fr\)\);/);
  assert.match(wide, /\.session-filter-actions \{[^}]*grid-row: 1;[^}]*justify-self: end;/);
});
