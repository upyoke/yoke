// One picture, or one block of captured text, at full size — and a way back.
//
// Evidence used to open in a new tab, which took the reviewer away from the
// decision the evidence is for. The lightbox keeps them on the page: the
// screenshot or log fills the viewport, Esc or the close control returns
// them to the card they were reading, and a full-size link stays available
// for anyone who wants the raw bytes in their own tab.

import { el } from "./universe_view_support.js";

const LIGHTBOX_CLASS = "review-lightbox";

function currentLightbox(documentNode) {
  return Array.from(documentNode.body?.children || []).find(
    (node) => node.classList?.contains(LIGHTBOX_CLASS),
  ) || null;
}

export function closeLightbox(documentNode) {
  const open = currentLightbox(documentNode);
  if (!open) return false;
  if (typeof open.dispose === "function") open.dispose();
  documentNode.body.removeChild(open);
  return true;
}

function frame(documentNode, caption, href) {
  closeLightbox(documentNode);
  const overlay = el(documentNode, "div", LIGHTBOX_CLASS);
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", caption || "Evidence");
  const bar = el(documentNode, "div", "review-lightbox-bar");
  bar.appendChild(el(documentNode, "span", "review-lightbox-caption", caption));
  if (href) {
    const open = el(documentNode, "a", "review-lightbox-open", "open in new tab ↗");
    open.href = href;
    open.target = "_blank";
    open.rel = "noopener";
    bar.appendChild(open);
  }
  const close = el(documentNode, "button", "review-lightbox-close", "Close");
  close.type = "button";
  close.setAttribute("aria-label", "Close");
  close.addEventListener("click", () => closeLightbox(documentNode));
  bar.appendChild(close);
  overlay.appendChild(bar);
  // The backdrop closes; the content does not, so a click on the picture
  // (or a drag to select log text) never dismisses it.
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeLightbox(documentNode);
  });
  const view = documentNode.defaultView;
  const onKey = (event) => {
    if (event.key === "Escape") closeLightbox(documentNode);
  };
  if (view && typeof view.addEventListener === "function") {
    view.addEventListener("keydown", onKey);
    overlay.dispose = () => view.removeEventListener("keydown", onKey);
  }
  documentNode.body.appendChild(overlay);
  return overlay;
}

export function openImageLightbox(documentNode, source, caption) {
  const overlay = frame(documentNode, caption, source);
  const image = el(documentNode, "img", "review-lightbox-image");
  image.src = source;
  image.alt = caption || "screenshot";
  overlay.appendChild(image);
  return overlay;
}

export function openTextLightbox(documentNode, caption, text, href = null) {
  const overlay = frame(documentNode, caption, href);
  overlay.appendChild(el(
    documentNode, "pre", "review-lightbox-text", String(text ?? ""),
  ));
  return overlay;
}

export const reviewLightbox = {
  closeLightbox,
  openImageLightbox,
  openTextLightbox,
};
