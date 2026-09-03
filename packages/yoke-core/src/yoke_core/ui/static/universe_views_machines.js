// The Machines destination: the registered machines of this universe, the
// native surfaces each can serve, and the launches they have run.
//
// It absorbs what were the Sessions view's Launches and Relays facets. Both
// answered questions about a MACHINE rather than about a session, and reaching
// them through Sessions meant the operator had to already suspect a machine
// before they could look at one.
//
// Capacity and health are deliberately NOT here. A machine's quota, headroom
// and free lanes are read before staffing work, which happens on Sessions, so
// they live at the top of that view instead. This destination is the durable
// registration record: which machines exist, what they serve, what they ran.

import { el } from "./universe_view_support.js";
import { renderSessionLaunchesView } from "./universe_session_launches.js";
import { renderSessionRelaysView } from "./universe_session_relays.js";

export function renderMachinesView(context, main, scope, chromeArg) {
  // A default parameter only fires on `undefined`, and this position carries
  // `null` on some render paths — so the guard is explicit.
  const chrome = (chromeArg && typeof chromeArg === "object") ? chromeArg : {};
  const documentNode = context.document;
  const relays = el(documentNode, "section", "machines-section");
  const launches = el(documentNode, "section", "machines-section");
  main.replaceChildren(relays, launches);

  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({
      title: "Machines",
      summary:
        "Connected machines, the native surfaces they serve, and the launches "
        + "they have run.",
    });
  }

  // Each composed view owns its own loading, refresh and error states, so this
  // destination passes an inert chrome rather than letting either of them
  // rewrite the page head it does not own.
  const composed = { ...chrome, setPageHead: undefined };
  renderSessionRelaysView(context, relays, scope, composed);
  renderSessionLaunchesView(context, launches, scope, composed);
}
