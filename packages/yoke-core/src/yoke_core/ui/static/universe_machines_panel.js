// The Machines panel above the Sessions roster: what can run, before what is
// running.
//
// A session card answers "what is this doing". Only the machine answers "why
// did that not start", and reading the second from the first is how a surface
// that was refusing every launch looked like a quiet fleet.
//
// The light is DERIVED, never stored. `derive_launch_eligibility` recomputes it
// server-side on every launch and can refuse for six reasons; four of them are
// answerable from the relay projection alone — no relay, a silent one, a
// surface the machine does not advertise, and an operator's disable mark — so
// each light names which. The remaining two (a version below the create floor,
// a project the relay does not serve) are settled at launch, and the panel says
// nothing about them rather than guessing.

import { el } from "./universe_view_support.js";
import {
  renderSessionControlFailure,
  sessionControlCall,
} from "./universe_session_control_data.js";

// The three surfaces a launch can create. A desktop surface is present on most
// machines and declares `create: none`, so a light for one would offer an
// answer about something no launch can use.
const LAUNCHABLE_SURFACES = ["claude-cli", "codex-cli", "cursor-cli"];

// Green passes what this panel can check. The two non-green states are separate
// facts with separate recoveries and never share a colour: SILENT is the relay's
// own condition and clears when it checks in; DISABLED is the operator's mark
// and only the operator clears it. Grey is a surface the machine does not have.
const LIGHTS = {
  ok: ["machine-light-ok", "ready"],
  silent: ["machine-light-warn", "relay silent"],
  disabled: ["machine-light-crit", "disabled"],
  absent: ["machine-light-off", "not installed"],
};

function surfaceState(relay, surface) {
  const mark = (relay.surface_policies || []).find(
    (entry) => entry.surface === surface,
  );
  if (mark) return ["disabled", mark.reason || "disabled by an operator"];
  const version = (relay.surface_versions || {})[surface];
  if (!version) return ["absent", "surface_absent — not installed on this machine"];
  if (String(relay.liveness) !== "connected") {
    return ["silent", "the relay has not checked in; a launch cannot reach it"];
  }
  return ["ok", ""];
}

function surfaceRow(documentNode, relay, surface) {
  const [state, reason] = surfaceState(relay, surface);
  const [lightClass, label] = LIGHTS[state];
  const row = el(documentNode, "div", `machine-surface machine-surface-${state}`);
  const head = el(documentNode, "div", "machine-surface-head");
  const light = el(documentNode, "span", `machine-light ${lightClass}`);
  light.title = label;
  head.appendChild(light);
  head.appendChild(el(documentNode, "span", "machine-surface-name", surface));
  const version = (relay.surface_versions || {})[surface];
  if (version) {
    head.appendChild(el(documentNode, "span", "machine-surface-version", version));
  }
  head.appendChild(el(documentNode, "span", "machine-surface-state", label));
  row.appendChild(head);
  // Every non-green light names its reason. A light that only changes colour
  // tells an operator that something is wrong and nothing about what.
  if (reason) {
    row.appendChild(el(documentNode, "p", "machine-surface-reason", reason));
  }
  return row;
}

// Quota, headroom and machine capacity are not drawn as numbers, because
// nothing measures them here yet: the readings sit on the relay row and reach
// no browser, and headroom is being recomputed against observed burn rather
// than a window average. An unmeasured meter drawn as a number is worse than an
// absent one — it is a number an operator would act on.
function pendingMeasures(documentNode) {
  const node = el(documentNode, "div", "machine-pending");
  node.appendChild(el(
    documentNode, "span", "machine-pending-label", "not measured here yet",
  ));
  node.appendChild(el(
    documentNode,
    "span",
    "machine-pending-detail",
    "plan quota, headroom, and free memory, load and lanes",
  ));
  return node;
}

function machineCard(documentNode, relay) {
  const card = el(documentNode, "article", "machine-card");
  const head = el(documentNode, "div", "machine-head");
  const live = String(relay.liveness) === "connected";
  head.appendChild(el(
    documentNode,
    "span",
    `machine-light ${live ? "machine-light-ok" : "machine-light-warn"}`,
  ));
  head.appendChild(el(
    documentNode, "span", "machine-host", relay.hostname || relay.machine_id,
  ));
  head.appendChild(el(
    documentNode, "span", "machine-meta", live ? relay.state : "silent",
  ));
  card.appendChild(head);
  card.appendChild(pendingMeasures(documentNode));
  for (const surface of LAUNCHABLE_SURFACES) {
    card.appendChild(surfaceRow(documentNode, relay, surface));
  }
  return card;
}

export function renderMachinesPanel(context, host, relays) {
  const documentNode = context.document;
  const panel = el(documentNode, "section", "machines-panel");
  panel.appendChild(el(documentNode, "h2", "machines-panel-head", "Machines"));
  if (!relays.length) {
    // No relay is the first of the six refusals, and the honest one to draw:
    // nothing can be launched anywhere from here.
    panel.appendChild(el(
      documentNode,
      "p",
      "machines-empty",
      "No relay is connected, so no session can be launched onto this universe.",
    ));
    host.appendChild(panel);
    return;
  }
  const grid = el(documentNode, "div", "machines-grid");
  for (const relay of relays) grid.appendChild(machineCard(documentNode, relay));
  panel.appendChild(grid);
  host.appendChild(panel);
}

// The relay roster is universe-wide and small, so the panel reads it once and
// does not re-read on a scope change: a machine does not belong to a project,
// and filtering it by one would hide the machine a launch would land on.
//
// A failed read SAYS SO. Hiding the panel would have been the quiet option and
// the wrong one: an absent panel is indistinguishable from a universe with no
// machines, so the one state that means "you cannot trust what you are looking
// at" would render as the state that means "there is nothing to look at". The
// failure keeps the heading, names itself, and offers the retry.
export async function loadMachinesPanel(context, host) {
  const documentNode = context.document;
  const run = async () => {
    let relays;
    try {
      const result = await sessionControlCall(
        context, "session_control.relay.list", { limit: 500 },
      );
      relays = result.relays || [];
    } catch (error) {
      if (!context.isMounted()) return;
      host.replaceChildren();
      const panel = el(documentNode, "section", "machines-panel");
      panel.appendChild(el(
        documentNode, "h2", "machines-panel-head", "Machines",
      ));
      const failure = el(documentNode, "div", "machines-failure");
      renderSessionControlFailure(
        failure,
        error,
        "The relay roster could not be read, so what can run is unknown.",
      );
      const retry = el(documentNode, "button", "machines-retry", "Try again");
      retry.type = "button";
      retry.addEventListener("click", () => { run(); });
      failure.appendChild(retry);
      panel.appendChild(failure);
      host.appendChild(panel);
      return;
    }
    if (!context.isMounted()) return;
    host.replaceChildren();
    renderMachinesPanel(context, host, relays);
  };
  await run();
}
