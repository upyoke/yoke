// The one condition an item card leads with — ready, blocked, frozen, waiting
// on another item — as a pill that reveals the whole reason. The caller names
// the condition: a dependency pill's label already says which items it waits
// on, from the edges themselves, never from the reason's prose.
//
// The reason is never shortened to fit: a dependency that says which item it
// waits on, a block that says why, and a freeze that says what parked it are
// the only useful part, and a card-width excerpt of any of them is a sentence
// with its answer cut off. So the pill carries the condition and the panel
// carries the reason, in full, reachable by pointer, touch and keyboard.

import {
  attachRevealPanel,
  revealCloseButton,
} from "./universe_reveal_panel.js";
import { el } from "./universe_view_support.js";

let statusPanelSequence = 0;

export function itemStatusDisclosure(documentNode, flag) {
  const tone = String(flag.tone || "neutral");
  const host = el(documentNode, "div", "item-status reveal-host");
  const pill = el(documentNode, "button", `item-status-pill is-${tone}`);
  pill.type = "button";
  pill.appendChild(el(documentNode, "span", "item-status-dot"));
  pill.appendChild(el(documentNode, "span", null, flag.label));
  const panel = el(documentNode, "div", "item-status-detail");
  statusPanelSequence += 1;
  panel.id = `item-status-detail-${statusPanelSequence}`;
  panel.setAttribute("role", "tooltip");
  panel.appendChild(el(
    documentNode, "span", "item-status-detail-label", flag.label,
  ));
  panel.appendChild(el(
    documentNode, "span", "item-status-detail-copy", flag.text,
  ));
  const controls = attachRevealPanel({
    documentNode, trigger: pill, panel, container: host,
  });
  panel.appendChild(revealCloseButton(documentNode, "Close ×", controls.close));
  pill.setAttribute("aria-describedby", panel.id);
  host.appendChild(pill);
  host.appendChild(panel);
  return host;
}
