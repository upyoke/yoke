import assert from "node:assert/strict";
import test from "node:test";

import {
  NAV,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import {
  NAV_ICONS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_nav_icons.js";

test("navigation is three groups, and every entry declares one", () => {
  assert.deepEqual(
    NAV.map(({ id, label, scope, group }) => [id, label, scope, group]),
    [
      // Focus follows the working day: where the universe is pointed, what is
      // moving, what is going out, what it runs on, who is running it, and
      // what is waiting on you.
      ["strategy", "Strategy", "multi", "focus"],
      ["frontier", "Frontier", "multi", "focus"],
      ["shipping", "Shipping", "multi", "focus"],
      ["machines", "Machines", "none", "focus"],
      ["sessions", "Sessions", "multi", "focus"],
      ["inbox", "Inbox", "multi", "focus"],
      // Reached from the actor menu; hidden from the sidebar.
      ["profile", "Profile", "none", "focus"],

      ["organization", "Universe", "none", "settings"],
      ["workflows", "Workflows", "none", "settings"],
      ["projects", "Projects", "none", "settings"],
      ["github", "GitHub", "multi", "settings"],
      ["actors", "Actors", "none", "settings"],
      ["members", "Members", "none", "settings"],
      ["billing", "Billing", "none", "settings"],

      ["items", "Items", "multi", "diagnostics"],
      ["deployments", "Deployments", "multi", "diagnostics"],
      ["environments", "Environments", "multi", "diagnostics"],
      ["databases", "Databases", "multi", "diagnostics"],
      ["qa-methods", "QA methods", "multi", "diagnostics"],
      ["qa-plans", "QA plans", "multi", "diagnostics"],
      ["qa-activity", "QA activity", "multi", "diagnostics"],
      ["capabilities", "Capabilities", "multi", "diagnostics"],
      ["packs", "Packs", "none", "diagnostics"],
      ["architecture", "Architecture", "single", "diagnostics"],
      ["messages", "Messages", "multi", "diagnostics"],
      ["launches", "Launches", "multi", "diagnostics"],
      ["events", "Events", "multi", "diagnostics"],
      ["doctor", "Doctor", "multi", "diagnostics"],
      ["ouroboros", "Ouroboros", "multi", "diagnostics"],
    ],
  );
});

test("every sidebar destination has an outline marking of its own", () => {
  // The markings are drawings, not glyphs, so they inherit the row's colour
  // and keep one weight across the whole rail. A destination with none would
  // render an empty slot and knock its label out of the column.
  for (const entry of NAV) {
    if (entry.hidden) continue;
    const markup = NAV_ICONS[entry.id];
    assert.ok(markup, entry.id);
    assert.match(markup, /^<svg /);
    assert.match(markup, /stroke="currentColor"/);
    assert.match(markup, /width="18" height="18"/);
    assert.match(markup, /stroke-width="1.75"/);
  }
});
