// One disclosure behaviour, shared by every panel a card reveals: the status
// detail behind a state pill, the claiming session behind a mini card, the
// deploy-lock holder on a run card.
//
// Pointer hover opens it, a click pins it open, and focus opens it for a
// keyboard, so the same control answers a mouse, a finger and a Tab key. Only
// one panel is open at a time — two overlapping cards each showing a floating
// panel is how a reader loses track of which card they were reading — and
// Escape, an outside press, or the panel's own Close ends it. Positioning is
// clamped to the viewport and the panel scrolls internally, because the
// content is a whole session card and the trigger can sit anywhere on screen.

import { el } from "./universe_view_support.js";

const VIEWPORT_MARGIN = 12;

let openEntry = null;

function closeOpen() {
  if (!openEntry) return;
  const { trigger, panel, onClose } = openEntry;
  openEntry = null;
  panel.hidden = true;
  trigger.setAttribute("aria-expanded", "false");
  onClose?.();
}

// Exported for view teardown: a route change removes the nodes, and a panel
// still recorded as open would keep the next route's first Escape busy.
export function closeRevealPanels() {
  closeOpen();
}

function clampToViewport(documentNode, trigger, panel) {
  const root = documentNode.documentElement;
  if (
    typeof trigger.getBoundingClientRect !== "function"
    || !root
    || typeof root.clientWidth !== "number"
  ) return;
  const rect = trigger.getBoundingClientRect();
  const width = panel.offsetWidth || 0;
  const height = panel.offsetHeight || 0;
  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(rect.left, root.clientWidth - width - VIEWPORT_MARGIN),
  );
  let top = rect.bottom + 8;
  if (top + height > root.clientHeight - VIEWPORT_MARGIN) {
    top = Math.max(VIEWPORT_MARGIN, rect.top - height - 8);
  }
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
}

/**
 * Wire a trigger to the panel it reveals.
 *
 * `container` is the region a pointer may wander within without dismissing —
 * normally the wrapper holding both trigger and panel.
 */
export function attachRevealPanel({
  documentNode, trigger, panel, container, onOpen,
}) {
  panel.hidden = true;
  trigger.setAttribute("aria-expanded", "false");
  if (panel.id) {
    trigger.setAttribute("aria-controls", panel.id);
  }
  let pinned = false;
  const close = () => {
    pinned = false;
    if (openEntry?.trigger === trigger) closeOpen();
  };
  const open = () => {
    if (openEntry?.trigger === trigger) return;
    closeOpen();
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    openEntry = { trigger, panel, onClose: () => { pinned = false; } };
    onOpen?.();
    clampToViewport(documentNode, trigger, panel);
  };

  trigger.addEventListener("pointerenter", (event) => {
    if (event.pointerType && event.pointerType !== "mouse") return;
    open();
  });
  trigger.addEventListener("focus", open);
  trigger.addEventListener("click", (event) => {
    event.stopPropagation?.();
    if (pinned && openEntry?.trigger === trigger) {
      close();
      return;
    }
    open();
    pinned = true;
  });
  container.addEventListener("pointerleave", () => {
    if (pinned) return;
    if (documentNode.activeElement && container.contains(documentNode.activeElement)) {
      return;
    }
    close();
  });
  container.addEventListener("focusout", (event) => {
    if (pinned) return;
    if (event.relatedTarget && container.contains(event.relatedTarget)) return;
    close();
  });
  container.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    close();
    trigger.focus?.();
  });
  return { close, isOpen: () => openEntry?.trigger === trigger };
}

// The panel's own way out, for a pointer that opened it by tapping and has
// nowhere obvious to tap next.
export function revealCloseButton(documentNode, label, onClick) {
  const button = el(documentNode, "button", "reveal-close", label);
  button.type = "button";
  button.addEventListener("click", (event) => {
    event.stopPropagation?.();
    onClick();
  });
  return button;
}

// Document-level dismissal, armed once per mounted view: a press outside any
// open panel closes it, and so does Escape anywhere.
export function armRevealPanelDismissal(documentNode) {
  const onPointerDown = (event) => {
    if (!openEntry) return;
    const target = event.target;
    if (target && typeof target.closest === "function"
      && target.closest(".reveal-host")) return;
    closeOpen();
  };
  const onKeyDown = (event) => {
    if (event.key === "Escape") closeOpen();
  };
  documentNode.addEventListener?.("pointerdown", onPointerDown);
  documentNode.addEventListener?.("keydown", onKeyDown);
  return () => {
    documentNode.removeEventListener?.("pointerdown", onPointerDown);
    documentNode.removeEventListener?.("keydown", onKeyDown);
    closeOpen();
  };
}
