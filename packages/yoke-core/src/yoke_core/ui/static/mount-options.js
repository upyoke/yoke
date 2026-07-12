// Host-neutral rendering for the optional mount seam. This stays separate
// from the workbench views so the one-argument local mount remains small.

function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const MOUNT_ROOT_CLASS = "universe-app-root";
const HTML_NAMESPACE = "http://www.w3.org/1999/xhtml";
const SLOT_NAMES = [
  "topbarStart",
  "topbarEnd",
  "navigationStart",
  "navigationEnd",
  "contentBefore",
  "contentAfter",
];

export function attachMountRootClass(rootNode) {
  const alreadyPresent = rootNode.classList.contains(MOUNT_ROOT_CLASS);
  rootNode.classList.add(MOUNT_ROOT_CLASS);
  return () => {
    if (!alreadyPresent) rootNode.classList.remove(MOUNT_ROOT_CLASS);
  };
}

export function validateMountRoot(rootNode) {
  if (!rootNode || rootNode.namespaceURI !== HTML_NAMESPACE ||
      typeof rootNode.replaceChildren !== "function") {
    throw new TypeError("mountUniverseApp requires an HTML element root");
  }
}

export function createUnmountHandle(contractVersion, cleanup) {
  let pendingCleanup = cleanup;
  return {
    contractVersion,
    unmount() {
      if (pendingCleanup === null) return;
      const release = pendingCleanup;
      pendingCleanup = null;
      release();
    },
  };
}

export function materializeSlots(slots, rootNode) {
  const resolved = {};
  const seen = new Set();
  for (const name of SLOT_NAMES) {
    const slot = slots[name];
    const content = typeof slot === "function" ? slot() : slot;
    if (content === undefined || content === null) continue;
    if (content.nodeType !== 1) {
      throw new TypeError("universe app slot content must be an Element");
    }
    if (content === rootNode || content.contains(rootNode)) {
      throw new TypeError("slot content cannot be the mount root or its ancestor");
    }
    if (seen.has(content)) {
      throw new TypeError("one Element cannot occupy two universe app slots");
    }
    seen.add(content);
    resolved[name] = content;
  }
  return resolved;
}

function invokeAction(action, option) {
  // Invoke during the originating DOM event so host actions that require
  // transient user activation (for example a file picker) retain it. Surface
  // both synchronous throws and rejected async handlers without coupling the
  // workbench to host-specific error concepts.
  let result;
  try {
    result = action.onInvoke(option);
  } catch (error) {
    globalThis.console.error("universe capability action failed", error);
    return;
  }
  Promise.resolve(result).catch((error) => {
    globalThis.console.error("universe capability action failed", error);
  });
}

export function renderCapabilityActions(documentNode, capabilities) {
  const actions = Array.isArray(capabilities.actions)
    ? capabilities.actions : [];
  if (actions.length === 0) return null;

  const strip = el(documentNode, "div", "capability-actions");
  for (const action of actions) {
    if (!action || typeof action.onInvoke !== "function") continue;
    const options = Array.isArray(action.options) ? action.options : [];
    if (options.length === 0) {
      const button = el(
        documentNode, "button", "capability-action", String(action.label || ""),
      );
      button.type = "button";
      button.addEventListener("click", () => invokeAction(action));
      strip.appendChild(button);
      continue;
    }

    const select = el(documentNode, "select", "capability-action");
    select.setAttribute("aria-label", String(action.label || "action"));
    const prompt = el(
      documentNode, "option", null, String(action.label || "Choose"),
    );
    prompt.value = "";
    prompt.disabled = true;
    prompt.selected = true;
    select.appendChild(prompt);
    for (const [index, option] of options.entries()) {
      const optionNode = el(
        documentNode, "option", null, String(option.label || option.id || ""),
      );
      optionNode.value = String(index);
      select.appendChild(optionNode);
    }
    select.addEventListener("change", () => {
      if (select.value === "") return;
      const selected = options[Number(select.value)];
      select.value = "";
      if (selected !== undefined) invokeAction(action, selected);
    });
    strip.appendChild(select);
  }
  return strip.children.length > 0 ? strip : null;
}

export function appendSlot(container, slot, mountedSlotNodes) {
  if (slot === undefined || slot === null) return;
  container.appendChild(slot);
  mountedSlotNodes.push(slot);
}

function isInsideRoot(rootNode, candidate) {
  for (let node = candidate; node; node = node.parentNode) {
    if (node === rootNode) return true;
  }
  return false;
}

export function detachMountedSlots(rootNode, mountedSlotNodes) {
  for (const slotNode of mountedSlotNodes) {
    if (isInsideRoot(rootNode, slotNode) && slotNode.parentNode) {
      slotNode.parentNode.removeChild(slotNode);
    }
  }
}
