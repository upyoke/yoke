// The Overview's pinned activation-module stack: four getting-started
// modules rendered from one overview.activation.get read. The engine owns
// every fact — module states, submodule signals, harness targets, per-actor
// dismissals — and this module owns only the drawn chrome: number/✓
// medallions, waits / next up / activated pills, the wizard checklist, the
// harness target row, hover dismiss, and the restore line. Honesty rules
// hold throughout: an unresolved read renders a pending line (never
// fabricated module states), a pending submodule stays ○, and the day-zero
// ghost panels replace a section only when its read served nothing AND its
// backing module is not yet activated. Which signal derives a state is a
// fact about the model, not something a member acts on, so it stays out of
// the rendered card.

import {
  callFunction,
  el,
  portabilityMode,
  statePill,
} from "./universe_view_support.js";
import {
  DISMISS_HINT,
  GHOST_HINTS,
  GHOST_MODULES,
  INSTALL_COMMAND,
  MODULE_COPY,
  MODULE_TITLES,
  RUN_ONBOARD_TITLE_HINT,
  STATE_PILL_TEXT,
  WIZARD_MACHINE_ROWS,
  WIZARD_ROWS,
  WIZARD_TAIL_KEYS,
  hookTrustRemediation,
} from "./universe_views_overview_activation_copy.js";

// Minimal relative formatter for "connected <x> ago": the app has no shared
// clock helper yet and this copy needs only a coarse honest magnitude.
function relativeTime(iso) {
  const then = Date.parse(String(iso || ""));
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

// The host-supplied machine fact rides the capability bag into the read's
// payload verbatim; absent or non-boolean shapes forward nothing, so the
// engine derives from its own signals and the submodule stays pending.
function activationPayload(capabilities) {
  const onboarding = capabilities?.data?.onboarding;
  const machineConnected =
    onboarding && typeof onboarding.machineConnected === "boolean"
      ? onboarding.machineConnected : undefined;
  return machineConnected === undefined
    ? {} : { host_facts: { machine_connected: machineConnected } };
}

async function readActivation(context) {
  let callResult;
  try {
    callResult = await callFunction(
      context.client, "overview.activation.get",
      activationPayload(context.capabilities),
    );
  } catch (fetchError) {
    return null;
  }
  const ok = callResult.status === 200 && callResult.envelope.success;
  return ok ? (callResult.envelope.result || null) : null;
}

async function setDismissed(context, module, dismissed, draw) {
  const functionId = dismissed
    ? "overview.module.dismiss" : "overview.module.restore";
  let callResult;
  try {
    callResult = await callFunction(
      context.client, functionId, { module_key: module.key },
    );
  } catch (fetchError) {
    return;
  }
  if (!(callResult.status === 200 && callResult.envelope.success)) return;
  if (!context.isMounted()) return;
  module.dismissed = dismissed;
  draw();
}

function wizardChecklist(documentNode, module, mode) {
  const list = el(documentNode, "ul", "activation-checklist");
  for (const submodule of module.submodules || []) {
    const label = submodule.key === "machine_universe"
      ? (WIZARD_MACHINE_ROWS[mode] || WIZARD_MACHINE_ROWS.local)
      : (WIZARD_ROWS[submodule.key] || submodule.key);
    const row = el(documentNode, "li", "activation-check");
    row.setAttribute("data-sub", submodule.key);
    row.setAttribute("data-done", String(Boolean(submodule.done)));
    row.appendChild(el(
      documentNode, "span", "activation-check-mark",
      submodule.done ? "✓" : "○",
    ));
    row.appendChild(el(documentNode, "span", "activation-check-label", label));
    if (!submodule.done && WIZARD_TAIL_KEYS.has(submodule.key)) {
      row.appendChild(el(
        documentNode, "span", "activation-check-optional", "· finish any time",
      ));
    }
    list.appendChild(row);
  }
  return list;
}

// Module 1's two in-flight copy states: machine connected reads
// return-to-terminal; hosted with the machine still pending reads web-first.
function wizardBody(documentNode, module, mode, body) {
  const machine = (module.submodules || []).find(
    (submodule) => submodule.key === "machine_universe",
  );
  if (module.state === "in_progress" && machine && machine.done) {
    body.appendChild(el(
      documentNode, "p", "activation-copy",
      "Your machine is connected to your Yoke identity.",
    ));
    const cta = el(
      documentNode, "p", "activation-cta",
      "Return to your terminal and finish ",
    );
    cta.appendChild(el(documentNode, "code", null, "yoke onboard"));
    body.appendChild(cta);
  } else if (module.state === "in_progress" && mode === "hosted") {
    const webFirst = el(documentNode, "p", "activation-copy web-first");
    webFirst.appendChild(el(
      documentNode, "strong", null, "Install Yoke on your machine",
    ));
    webFirst.appendChild(documentNode.createElement("span")).textContent =
      " — ";
    webFirst.appendChild(el(documentNode, "code", null, INSTALL_COMMAND));
    webFirst.appendChild(documentNode.createElement("span")).textContent =
      " — the wizard connects this machine, then GitHub · Project · " +
      "Hosting fold in here.";
    body.appendChild(webFirst);
  }
  body.appendChild(wizardChecklist(documentNode, module, mode));
}

// The engine's hook-health state for "registered, but its hooks never fire".
const HOOKS_SILENT = "hooks_silent";

// One remediation line per approval surface, not per target: a harness's
// family and surface chips share one approval, so two silent chips must not
// repeat the same instruction.
function silentTrustSurfaces(targets) {
  const surfaces = [];
  for (const target of targets || []) {
    if (target.hook_health !== HOOKS_SILENT || !target.trust_surface) continue;
    if (!surfaces.includes(target.trust_surface)) {
      surfaces.push(target.trust_surface);
    }
  }
  return surfaces;
}

function harnessBody(documentNode, module, body) {
  if (module.state === "activated" && module.connected) {
    const relative = relativeTime(module.connected.at);
    body.appendChild(el(
      documentNode, "p", "activation-copy",
      relative === null
        ? `${module.connected.executor} connected.`
        : `${module.connected.executor} connected ${relative} ago.`,
    ));
  }
  if (module.state === "in_progress") {
    body.appendChild(el(
      documentNode, "p", "activation-copy", MODULE_COPY.connect_harness.in_progress,
    ));
    for (const project of module.projects || []) {
      const row = el(documentNode, "p", "activation-project");
      row.appendChild(el(documentNode, "span", "mono", project.slug));
      if (project.workspace) {
        row.appendChild(el(documentNode, "span", null, ` · ${project.workspace} · `));
        row.appendChild(el(
          documentNode, "code", null, `cd ${project.workspace}`,
        ));
      }
      body.appendChild(row);
    }
  }
  const targets = el(documentNode, "p", "activation-targets");
  (module.targets || []).forEach((target, index) => {
    if (index) {
      targets.appendChild(el(documentNode, "span", "activation-target-sep", " · "));
    }
    const silent = target.hook_health === HOOKS_SILENT;
    const chip = el(
      documentNode, "span", "activation-target",
      target.hit ? `${target.label} ${silent ? "⚠" : "✓"}` : target.label,
    );
    chip.setAttribute("data-hit", String(Boolean(target.hit)));
    if (target.hook_health) {
      chip.setAttribute("data-hook-health", target.hook_health);
    }
    targets.appendChild(chip);
  });
  body.appendChild(targets);
  for (const trustSurface of silentTrustSurfaces(module.targets)) {
    body.appendChild(el(
      documentNode, "p", "activation-remediation",
      hookTrustRemediation(trustSurface),
    ));
  }
}

function renderModule(context, module, position, result, draw, viewState) {
  const documentNode = context.document;
  const card = el(documentNode, "section", "activation-module");
  card.setAttribute("data-module", module.key);
  card.setAttribute("data-state", module.state);
  if (module.dismissed) card.classList.add("dismissed");
  const head = el(documentNode, "div", "activation-head");
  head.appendChild(el(
    documentNode, "span", "activation-medallion",
    module.state === "activated" ? "✓" : String(position),
  ));
  const title = el(
    documentNode, "h3", "activation-title",
    MODULE_TITLES[module.key] || module.key,
  );
  if (module.key === "run_onboard") {
    title.classList.add("cmd");
    title.setAttribute("title", RUN_ONBOARD_TITLE_HINT);
  }
  head.appendChild(title);
  const pill = statePill(
    documentNode, STATE_PILL_TEXT[module.state] || module.state,
  );
  if (pill) head.appendChild(pill);
  if (module.dismissed) {
    const restore = el(documentNode, "button", "activation-restore", "restore");
    restore.type = "button";
    restore.addEventListener(
      "click", () => setDismissed(context, module, false, draw),
    );
    head.appendChild(restore);
  } else if (result.dismiss_available && module.state === "activated") {
    const dismiss = el(documentNode, "button", "activation-dismiss", "✕");
    dismiss.type = "button";
    dismiss.setAttribute("title", DISMISS_HINT);
    dismiss.addEventListener(
      "click", () => setDismissed(context, module, true, draw),
    );
    head.appendChild(dismiss);
  }
  card.appendChild(head);
  const body = el(documentNode, "div", "activation-body");
  if (module.key === "finish_installation_wizard") {
    wizardBody(documentNode, module, viewState.mode, body);
  } else if (module.key === "connect_harness") {
    harnessBody(documentNode, module, body);
  } else {
    const copy = (MODULE_COPY[module.key] || {})[module.state];
    if (copy) body.appendChild(el(documentNode, "p", "activation-copy", copy));
  }
  card.appendChild(body);
  return card;
}

function renderStack(context, host, result) {
  const documentNode = context.document;
  if (!result || !Array.isArray(result.modules)) {
    host.replaceChildren(el(
      documentNode, "p", "activation-unresolved",
      "activation signals unresolved",
    ));
    return;
  }
  const viewState = {
    mode: portabilityMode(context.capabilities),
    showDismissed: false,
  };
  const draw = () => {
    const stack = el(documentNode, "div", "activation-stack");
    result.modules.forEach((module, index) => {
      if (module.dismissed && !viewState.showDismissed) return;
      stack.appendChild(renderModule(
        context, module, index + 1, result, draw, viewState,
      ));
    });
    const dismissedCount = result.modules.filter(
      (module) => module.dismissed,
    ).length;
    if (dismissedCount && !viewState.showDismissed) {
      const line = el(
        documentNode, "p", "activation-restore-line",
        `${dismissedCount} dismissed module(s) · `,
      );
      const show = el(documentNode, "button", "activation-show", "show");
      show.type = "button";
      show.addEventListener("click", () => {
        viewState.showDismissed = true;
        draw();
      });
      line.appendChild(show);
      stack.appendChild(line);
    }
    host.replaceChildren(stack);
  };
  draw();
}

// The one Overview entry point: render the stack into `host` from a single
// activation read, and hand back a promise of the module-facts lookup that
// the ghost-panel rule consumes (null when the read did not resolve).
export function loadActivationModules(context, host) {
  const read = readActivation(context);
  read.then((result) => {
    if (!context.isMounted()) return;
    renderStack(context, host, result);
  });
  return read.then((result) => (
    result && Array.isArray(result.modules)
      ? new Map(result.modules.map((module) => [module.key, module]))
      : null
  ));
}

// A section whose read served nothing AND whose backing module is not yet
// activated collapses to the drawn ghost hint; any resolved activation or a
// non-empty read keeps the live panel.
export function ghostWhenInactive(context, activationFacts, view, panel) {
  // Capture the panel's render generation now; if a later paint (a rescope
  // that found data) supersedes this empty paint before the activation read
  // resolves, the deferred collapse is stale and must not fire.
  const scheduledGeneration = typeof panel.renderGeneration === "function"
    ? panel.renderGeneration() : null;
  activationFacts.then((facts) => {
    if (!context.isMounted() || !facts) return;
    if (scheduledGeneration !== null
      && panel.renderGeneration() !== scheduledGeneration) return;
    const module = facts.get(GHOST_MODULES[view]);
    if (!module || module.state === "activated") return;
    // Delegate the collapse to the panel owner so a later re-scope with data
    // can restore the panel's chrome (including its "Open X ->" link).
    panel.ghost(el(
      context.document, "p", "overview-ghost-hint", GHOST_HINTS[view],
    ));
  });
}
