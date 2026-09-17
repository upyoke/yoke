// Getting started, as a progress control in the navigation rather than a
// block at the top of a page.
//
// Onboarding matters intensely for about a day and then never again, so it
// reports itself the way an unfinished thing should: a single
// completed-of-total marker that is there while there is something left to
// do and gone once there is not. Hovering or focusing it says which step is
// next; opening it gives the whole module stack, with every action those
// modules carry, unchanged.
//
// Progress is read from the same activation record the modules render from —
// never counted from how many cards happen to be drawn — and a module the
// operator dismissed leaves the reckoning entirely, exactly as it leaves the
// stack. Nothing is drawn until that record resolves, so the control never
// flashes "complete" on the way to saying something else.

import {
  attachRevealPanel,
  revealCloseButton,
} from "./universe_reveal_panel.js";
import { MODULE_TITLES } from "./universe_onboarding_copy.js";
import { loadActivationModules } from "./universe_onboarding_modules.js";
import { el } from "./universe_view_support.js";

function visibleModules(result) {
  return (result?.modules || []).filter((module) => !module.dismissed);
}

export function onboardingProgress(result) {
  const modules = visibleModules(result);
  return {
    completed: modules.filter((module) => module.state === "activated").length,
    total: modules.length,
    modules,
  };
}

function summaryLines(documentNode, panel, progress) {
  panel.replaceChildren();
  for (const module of progress.modules) {
    panel.appendChild(el(
      documentNode,
      "div",
      "onboarding-summary-step",
      `${module.state === "activated" ? "✓" : "○"} `
        + `${MODULE_TITLES[module.key] || module.key}`,
    ));
  }
}

function createDialog(documentNode, body, onClosed) {
  const dialog = el(documentNode, "dialog", "onboarding-dialog");
  dialog.setAttribute("aria-label", "Onboarding");
  const close = el(documentNode, "button", "item-button onboarding-close", "Close ×");
  close.type = "button";
  dialog.appendChild(close);
  dialog.appendChild(el(documentNode, "h2", "onboarding-dialog-title", "Onboarding"));
  dialog.appendChild(body);
  let open = false;
  const hide = () => {
    if (!open) return;
    open = false;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.hidden = true;
    onClosed();
  };
  close.addEventListener("click", hide);
  // A native dialog answers Escape itself; the fallback shape needs telling.
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (typeof dialog.close !== "function") event.preventDefault?.();
      hide();
    }
  });
  dialog.addEventListener("close", () => {
    if (!open) return;
    open = false;
    onClosed();
  });
  dialog.hidden = true;
  return {
    node: dialog,
    show() {
      open = true;
      dialog.hidden = false;
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("aria-modal", "true");
      close.focus?.();
    },
    hide,
  };
}

/**
 * Build the control, its hover summary, and its dialog.
 *
 * Returns the sidebar host, a second trigger for the narrow-width header, and
 * the dialog node the caller places inside the app root.
 */
export function createOnboardingControl(context) {
  const documentNode = context.document;
  const host = el(documentNode, "div", "onboarding-control reveal-host");
  host.hidden = true;
  const trigger = el(documentNode, "button", "onboarding-trigger");
  trigger.type = "button";
  trigger.setAttribute("aria-haspopup", "dialog");
  const summary = el(documentNode, "div", "onboarding-summary");
  summary.id = "onboarding-summary";
  const controls = attachRevealPanel({
    documentNode, trigger, panel: summary, container: host,
  });
  summary.appendChild(revealCloseButton(documentNode, "Close ×", controls.close));
  host.appendChild(trigger);
  host.appendChild(summary);

  // The narrow-width copy sits beside the navigation toggle, where the
  // sidebar it would otherwise live in is a closed drawer.
  const compactTrigger = el(documentNode, "button", "onboarding-trigger is-compact");
  compactTrigger.type = "button";
  compactTrigger.setAttribute("aria-haspopup", "dialog");
  compactTrigger.hidden = true;

  const stackHost = el(documentNode, "div", "activation-host");
  const dialog = createDialog(documentNode, stackHost, () => {
    controls.close();
    trigger.focus?.();
  });
  const openDialog = (event) => {
    event.stopPropagation?.();
    dialog.show();
  };
  trigger.addEventListener("click", openDialog);
  compactTrigger.addEventListener("click", openDialog);

  let activation = null;
  const paint = () => {
    const progress = onboardingProgress(activation);
    const finished = progress.total === 0 || progress.completed === progress.total;
    host.hidden = finished;
    compactTrigger.hidden = finished;
    if (finished) return;
    const label = `Setup · ${progress.completed}/${progress.total}`;
    trigger.textContent = label;
    compactTrigger.textContent = label;
    trigger.setAttribute(
      "aria-label", `Onboarding: ${progress.completed} of ${progress.total} complete`,
    );
    summaryLines(documentNode, summary, progress);
    summary.appendChild(revealCloseButton(
      documentNode, "Close ×", controls.close,
    ));
  };

  loadActivationModules(context, stackHost, {
    // Fired on the first draw and after every dismissal, so the marker and
    // the stack always agree about what is left.
    onStackResolved: () => paint(),
  }).then((result) => {
    if (!context.isMounted()) return;
    activation = result;
    paint();
  });

  return { host, compactTrigger, dialog: dialog.node };
}
