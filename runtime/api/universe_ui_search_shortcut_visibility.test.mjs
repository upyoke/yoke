// The header search shortcut hint hides only where input is touch-primary.
// Keyboard desktops can report no hover: xrdp Chromium matches both
// (hover: none) and (pointer: none), yet Ctrl+K works there.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

const STATIC = new URL(
  "../../packages/yoke-core/src/yoke_core/ui/static/",
  import.meta.url,
);

// Every top-level rule in a stylesheet with the media query wrapping it.
function rules(css) {
  const found = [];
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  let index = 0;
  while (index < source.length) {
    const open = source.indexOf("{", index);
    if (open < 0) break;
    const prelude = source.slice(index, open).trim();
    let depth = 1;
    let close = open + 1;
    for (; depth > 0 && close < source.length; close += 1) {
      if (source[close] === "{") depth += 1;
      if (source[close] === "}") depth -= 1;
    }
    const body = source.slice(open + 1, close - 1);
    if (prelude.startsWith("@media")) {
      for (const inner of rules(body)) {
        found.push({ ...inner, media: prelude.slice(6).trim() });
      }
    } else {
      found.push({ selector: prelude, body, media: null });
    }
    index = close;
  }
  return found;
}

// A media query of (feature: value) terms joined by "and" against a device.
function matches(media, device) {
  if (media === null) return true;
  assert.match(media, /^\([^()]+\)( and \([^()]+\))*$/, `unsupported query ${media}`);
  return [...media.matchAll(/\(([\w-]+):\s*([^)]+)\)/g)].every(
    ([, feature, value]) => {
      if (feature === "max-width") return device.width <= parseInt(value, 10);
      if (feature === "min-width") return device.width >= parseInt(value, 10);
      assert.ok(feature in device, `device does not declare ${feature}`);
      return device[feature] === value.trim();
    },
  );
}

function hintHidden(device) {
  return readdirSync(STATIC)
    .filter((name) => name.endsWith(".css"))
    .flatMap((name) => rules(readFileSync(new URL(name, STATIC), "utf8")))
    .some((rule) => /(^|[\s,])\.header-search-key\b/.test(rule.selector)
      && /display:\s*none/.test(rule.body)
      && matches(rule.media, device));
}

const desktop = { width: 1440, hover: "hover", pointer: "fine" };

test("the hint renders on a keyboard desktop that reports no pointer or hover", () => {
  assert.equal(hintHidden({ ...desktop, hover: "none", pointer: "none" }), false);
});

test("the hint renders on an ordinary mouse desktop", () => {
  assert.equal(hintHidden(desktop), false);
});

test("the hint is hidden on a touch-primary device", () => {
  assert.equal(hintHidden({ ...desktop, hover: "none", pointer: "coarse" }), true);
});
