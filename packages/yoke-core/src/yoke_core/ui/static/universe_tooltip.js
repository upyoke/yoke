/**
 * One explanation surface for a fact already drawn on screen.
 *
 * A `title` attribute reaches a desktop pointer and nothing else: a phone
 * never shows it, a keyboard never lands on it, its wording cannot be
 * styled, and it disappears while it is being read. Every explanation the
 * product attaches to a rendered fact goes through this primitive instead,
 * so the same sentence answers a hover, a tap and a focus on every surface.
 *
 * The trigger is whatever already names the fact — a state pill, a badge, a
 * relative timestamp, a control that is refusing. `infoTooltip` is the one
 * exception, minting the small (i) for the case where nothing visible
 * carries the explanation at all.
 *
 * The bubble itself lives in one shared layer per document rather than
 * inside each trigger. A bubble parked inside its trigger joins that
 * trigger's text: a button reading "Message" would answer `textContent`
 * with its own explanation appended, and would be announced by that whole
 * string. The trigger therefore carries only `data-tooltip` — the durable
 * record of what it explains — and the layer renders whichever one is open.
 */

import { el } from "./universe_view_support.js";

const LAYER_ID = "tooltip-layer";
const layers = new WeakMap();
let openTooltip = null;
let dismissBinding = null;

function tooltipLayer(documentNode) {
  const existing = layers.get(documentNode);
  if (existing) return existing;
  const bubble = el(documentNode, "span", "tooltip-bubble");
  bubble.setAttribute("id", LAYER_ID);
  bubble.setAttribute("role", "tooltip");
  bubble.hidden = true;
  documentNode.body?.appendChild(bubble);
  layers.set(documentNode, bubble);
  return bubble;
}

function closeOpenTooltip() {
  if (!openTooltip) return;
  const closing = openTooltip;
  openTooltip = null;
  closing.hide();
}

/**
 * Dismissal listens on the window only while something is open.
 *
 * A roster draws hundreds of these, so a listener per trigger is out; a
 * standing listener per window is also out, because it would outlive the
 * app that mounted it and the shell's unmount contract counts what is left
 * behind. One binding, taken when a bubble opens and given back when it
 * closes, is both.
 */
function bindDismissal(windowNode) {
  if (!windowNode || dismissBinding) return;
  const onKeyDown = (event) => {
    if (event.key === "Escape") closeOpenTooltip();
  };
  // A tap anywhere else dismisses: on a touch screen there is no pointer to
  // move away, so without this the bubble would stay until the next tap on
  // another trigger.
  const onPointerDown = (event) => {
    if (!openTooltip) return;
    if (!openTooltip.trigger.contains?.(event.target)) closeOpenTooltip();
  };
  const onScroll = () => closeOpenTooltip();
  windowNode.addEventListener("keydown", onKeyDown);
  windowNode.addEventListener("pointerdown", onPointerDown);
  windowNode.addEventListener("scroll", onScroll, true);
  dismissBinding = { windowNode, onKeyDown, onPointerDown, onScroll };
}

function releaseDismissal() {
  if (!dismissBinding) return;
  const { windowNode, onKeyDown, onPointerDown, onScroll } = dismissBinding;
  dismissBinding = null;
  windowNode.removeEventListener("keydown", onKeyDown);
  windowNode.removeEventListener("pointerdown", onPointerDown);
  windowNode.removeEventListener("scroll", onScroll, true);
}

// Fixed rather than absolute: the bubble routinely hangs off a pill inside a
// clipping row, and a fixed box is positioned against the viewport instead of
// being cut off by an ancestor's overflow.
function placeBubble(bubble, trigger, windowNode) {
  const rect = trigger.getBoundingClientRect?.();
  if (!rect) return;
  const viewport = Number(windowNode?.innerWidth) || 0;
  const width = Number(bubble.offsetWidth) || 0;
  const left = viewport && width
    ? Math.max(8, Math.min(rect.left, viewport - width - 8))
    : Math.max(8, rect.left);
  bubble.style.left = `${Math.round(left)}px`;
  bubble.style.top = `${Math.round(rect.bottom + 6)}px`;
}

/**
 * Make `trigger` explain itself with `text`.
 *
 * Returns a controller so a caller whose sentence changes as state changes
 * — a control that is refusing for a different reason now — updates the one
 * tooltip instead of attaching another. Empty text detaches: a fact with
 * nothing left to explain shows no affordance at all.
 *
 * `pinOnClick` is false for a trigger that already does something when
 * clicked, so a tap runs that action rather than opening prose over it.
 */
export function attachTooltip(
  documentNode, trigger, text, { pinOnClick = true } = {},
) {
  const windowNode = documentNode.defaultView;
  let content = "";
  let pinned = false;

  const hide = () => {
    pinned = false;
    if (openTooltip === controller) openTooltip = null;
    if (!openTooltip) releaseDismissal();
    trigger.classList.remove("tooltip-open");
    trigger.removeAttribute("aria-describedby");
    const bubble = layers.get(documentNode);
    if (bubble) bubble.hidden = true;
  };
  const show = () => {
    if (!content) return;
    if (openTooltip && openTooltip.trigger !== trigger) closeOpenTooltip();
    openTooltip = controller;
    bindDismissal(windowNode);
    const bubble = tooltipLayer(documentNode);
    bubble.textContent = content;
    bubble.hidden = false;
    trigger.classList.add("tooltip-open");
    trigger.setAttribute("aria-describedby", LAYER_ID);
    placeBubble(bubble, trigger, windowNode);
  };
  const controller = {
    hide,
    show,
    trigger,
    text: () => content,
    set(next) {
      content = String(next ?? "").trim();
      if (content) {
        trigger.classList.add("has-tooltip");
        trigger.setAttribute("data-tooltip", content);
      } else {
        trigger.classList.remove("has-tooltip");
        trigger.removeAttribute("data-tooltip");
        if (openTooltip === controller) closeOpenTooltip();
        else hide();
      }
      // The native tooltip would otherwise draw a second, unstyled copy of
      // the same sentence over this one.
      trigger.removeAttribute("title");
      return controller;
    },
  };

  // Focusable so a keyboard reaches the explanation. A trigger that already
  // takes focus on its own keeps its place in the tab order.
  if (!["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "SUMMARY"].includes(
    String(trigger.tagName || "").toUpperCase(),
  ) && trigger.getAttribute("tabindex") === null) {
    trigger.setAttribute("tabindex", "0");
  }

  trigger.addEventListener("mouseenter", () => { if (!pinned) show(); });
  trigger.addEventListener("mouseleave", () => { if (!pinned) hide(); });
  trigger.addEventListener("focus", show);
  trigger.addEventListener("blur", () => { if (!pinned) hide(); });
  // A tap pins the bubble open so it survives the synthetic mouseleave that
  // follows a touch, and a second tap dismisses it.
  if (pinOnClick) {
    trigger.addEventListener("click", () => {
      if (!content) return;
      if (pinned) {
        hide();
        return;
      }
      show();
      pinned = true;
    });
  }

  return controller.set(text);
}

/**
 * The small (i) for an explanation nothing on screen already carries.
 *
 * A button rather than a styled span: it is a real control, so it is
 * focusable, announced, and reachable by tap without any of this module
 * having to simulate that.
 */
export function infoTooltip(documentNode, text, label = "Why") {
  const content = String(text ?? "").trim();
  if (!content) return null;
  const button = el(documentNode, "button", "tooltip-info", "i");
  button.type = "button";
  button.setAttribute("aria-label", label);
  button.tooltip = attachTooltip(documentNode, button, content);
  return button;
}

/**
 * Wrap a control so its explanation survives the control being disabled.
 *
 * A disabled form control fires no pointer or focus events at all, so a
 * tooltip bound directly to one is unreachable exactly when its sentence —
 * why this button will not do anything — matters most. The host span takes
 * the events the control cannot, and is also the only place an input can
 * carry one, a void element having no inside to attach to.
 */
export function tooltipHost(documentNode, control, text) {
  const host = el(documentNode, "span", "tooltip-host");
  host.appendChild(control);
  host.tooltip = attachTooltip(documentNode, host, text);
  return host;
}
