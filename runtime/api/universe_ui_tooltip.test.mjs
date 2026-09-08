import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  attachTooltip,
  infoTooltip,
  tooltipHost,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_tooltip.js";
import { FakeDocument, byClass } from "./universe_ui_dom_test_support.mjs";

// `target` is read-only on a real Event, and the dismiss listener reads it
// to decide whether the tap landed inside the open trigger.
function fire(node, type, detail = {}) {
  const event = new Event(type);
  for (const [key, value] of Object.entries(detail)) {
    Object.defineProperty(event, key, { value, configurable: true });
  }
  node.dispatchEvent(event);
}

function layer(documentNode) {
  return byClass(documentNode.body, "tooltip-bubble")[0] || null;
}

test("hover, tap and focus each reach the same explanation", () => {
  const documentNode = new FakeDocument();
  const trigger = documentNode.createElement("span");
  attachTooltip(documentNode, trigger, "why this reads the way it does");

  assert.equal(trigger.getAttribute("data-tooltip"), "why this reads the way it does");
  assert.equal(trigger.classList.contains("has-tooltip"), true);
  // A plain span is not focusable on its own, so it is made so; the
  // explanation is otherwise unreachable without a pointer.
  assert.equal(trigger.getAttribute("tabindex"), "0");
  assert.equal(layer(documentNode), null, "nothing renders until it is asked for");

  fire(trigger, "mouseenter");
  assert.equal(layer(documentNode).textContent, "why this reads the way it does");
  assert.equal(layer(documentNode).hidden, false);
  assert.equal(trigger.getAttribute("aria-describedby"), "tooltip-layer");
  fire(trigger, "mouseleave");
  assert.equal(layer(documentNode).hidden, true);
  assert.equal(trigger.getAttribute("aria-describedby"), null);

  fire(trigger, "focus");
  assert.equal(layer(documentNode).hidden, false);
  fire(trigger, "blur");
  assert.equal(layer(documentNode).hidden, true);

  // A tap pins it open past the synthetic mouseleave a touch produces, and
  // the next tap dismisses it.
  fire(trigger, "click");
  assert.equal(layer(documentNode).hidden, false);
  fire(trigger, "mouseleave");
  assert.equal(layer(documentNode).hidden, false);
  fire(trigger, "click");
  assert.equal(layer(documentNode).hidden, true);
});

test("Escape and a tap elsewhere dismiss whatever is open", () => {
  const documentNode = new FakeDocument();
  const first = documentNode.createElement("span");
  const second = documentNode.createElement("span");
  attachTooltip(documentNode, first, "first");
  attachTooltip(documentNode, second, "second");

  fire(first, "click");
  assert.equal(layer(documentNode).textContent, "first");
  fire(documentNode.defaultView, "keydown", { key: "Escape" });
  assert.equal(layer(documentNode).hidden, true);

  fire(first, "click");
  fire(documentNode.defaultView, "pointerdown", { target: second });
  assert.equal(layer(documentNode).hidden, true);

  // One at a time: opening the second closes the first rather than leaving
  // two explanations stacked over each other.
  fire(first, "click");
  fire(second, "click");
  assert.equal(layer(documentNode).textContent, "second");
  assert.equal(first.classList.contains("tooltip-open"), false);
  assert.equal(second.classList.contains("tooltip-open"), true);
});

test("the explanation never joins the trigger's own text or name", () => {
  const documentNode = new FakeDocument();
  const button = documentNode.createElement("button");
  button.textContent = "Message";
  attachTooltip(documentNode, button, "Message only session s-1");

  fire(button, "mouseenter");
  // A bubble parked inside the button would be read as part of it, both by
  // `textContent` and by anything computing the button's accessible name.
  assert.equal(button.textContent, "Message");
  assert.equal(button.children.length, 0);
  assert.equal(layer(documentNode).parentNode, documentNode.body);
});

test("a native title never survives beside the shared one", () => {
  const documentNode = new FakeDocument();
  const trigger = documentNode.createElement("span");
  trigger.title = "stale native copy";
  trigger.setAttribute("title", "stale native copy");
  attachTooltip(documentNode, trigger, "the real explanation");
  assert.equal(trigger.getAttribute("title"), null);
});

test("a changed sentence updates in place, and an empty one detaches", () => {
  const documentNode = new FakeDocument();
  const trigger = documentNode.createElement("span");
  const tooltip = attachTooltip(documentNode, trigger, "no open sessions match");

  tooltip.set("Message all 3 open sessions");
  assert.equal(trigger.getAttribute("data-tooltip"), "Message all 3 open sessions");
  assert.equal(tooltip.text(), "Message all 3 open sessions");

  fire(trigger, "click");
  assert.equal(layer(documentNode).hidden, false);
  tooltip.set("");
  assert.equal(trigger.getAttribute("data-tooltip"), null);
  assert.equal(trigger.classList.contains("has-tooltip"), false);
  assert.equal(layer(documentNode).hidden, true, "an open bubble closes with its content");
  fire(trigger, "mouseenter");
  assert.equal(layer(documentNode).hidden, true);
});

test("a trigger with its own action keeps the click", () => {
  const documentNode = new FakeDocument();
  const button = documentNode.createElement("button");
  let clicks = 0;
  button.addEventListener("click", () => { clicks += 1; });
  attachTooltip(documentNode, button, "opens the compose dialog", { pinOnClick: false });

  fire(button, "click");
  assert.equal(clicks, 1);
  assert.equal(layer(documentNode), null, "a tap runs the action rather than opening prose");
  // Hover and focus still reach the sentence.
  fire(button, "focus");
  assert.equal(layer(documentNode).textContent, "opens the compose dialog");
  // A button is already in the tab order and is not given a second tabindex.
  assert.equal(button.getAttribute("tabindex"), null);
});

test("the (i) is minted only where nothing visible carries the explanation", () => {
  const documentNode = new FakeDocument();
  assert.equal(infoTooltip(documentNode, "   "), null);
  assert.equal(infoTooltip(documentNode, null), null);
  const info = infoTooltip(documentNode, "quiet past the staleness window", "Why stale");
  assert.equal(info.tagName, "BUTTON");
  assert.equal(info.type, "button");
  assert.equal(info.className, "tooltip-info has-tooltip");
  assert.equal(info.getAttribute("aria-label"), "Why stale");
  assert.equal(info.getAttribute("data-tooltip"), "quiet past the staleness window");
});

test("a disabled control explains itself through its host", () => {
  const documentNode = new FakeDocument();
  const control = documentNode.createElement("button");
  control.disabled = true;
  const host = tooltipHost(documentNode, control, "No stale sessions in this scope");

  assert.equal(host.className, "tooltip-host has-tooltip");
  assert.equal(host.children[0], control);
  // The events land on the host, which is exactly why it exists: a disabled
  // control fires none of them.
  fire(host, "mouseenter");
  assert.equal(layer(documentNode).textContent, "No stale sessions in this scope");
  host.tooltip.set("Recheck and reclaim 2 stale sessions");
  assert.equal(host.getAttribute("data-tooltip"), "Recheck and reclaim 2 stale sessions");
});

test("the bubble escapes clipping rows and stays inside the viewport", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_tooltip.css",
    import.meta.url,
  ), "utf8");
  // Fixed, not absolute: these hang off pills inside rows that clip.
  assert.match(css, /\.tooltip-bubble \{[^}]*position: fixed;/s);
  // Unscoped on purpose: the bubble is parked in `body`, so a rule written
  // under `.universe-app-root` would not reach it and it would render with
  // no styling at all.
  assert.doesNotMatch(css, /\.universe-app-root \.tooltip-bubble/);
  assert.match(css, /\.tooltip-bubble \{[^}]*max-width: min\(280px, calc\(100vw - 16px\)\);/s);
  assert.match(css, /\.tooltip-bubble\[hidden\] \{\s*display: none;\s*\}/);
  assert.match(css, /\.has-tooltip:focus-visible \{[^}]*outline: 2px solid var\(--yoke-accent\);/s);
});

test("one shared sheet, loaded app-wide rather than per view", () => {
  const appCss = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/app.css",
    import.meta.url,
  ), "utf8");
  assert.match(appCss, /@import url\("\.\/universe_tooltip\.css"\);/);
  const roster = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/asset_roster.py",
    import.meta.url,
  ), "utf8");
  for (const asset of ["universe_tooltip.js", "universe_tooltip.css"]) {
    assert.ok(roster.includes(`"${asset}"`), `${asset} is servable`);
  }
});
