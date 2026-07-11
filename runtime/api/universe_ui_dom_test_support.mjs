export class FakeClassList {
  constructor(node) {
    this.node = node;
  }

  contains(name) {
    return this.node.className.split(/\s+/).filter(Boolean).includes(name);
  }

  add(name) {
    this.toggle(name, true);
  }

  remove(name) {
    this.toggle(name, false);
  }

  toggle(name, force) {
    const names = new Set(this.node.className.split(/\s+/).filter(Boolean));
    const enabled = force === undefined ? !names.has(name) : Boolean(force);
    if (enabled) names.add(name);
    else names.delete(name);
    this.node.className = [...names].join(" ");
    return enabled;
  }
}

export class FakeNode extends EventTarget {
  constructor(ownerDocument, tagName, nodeType = 1) {
    super();
    this.ownerDocument = ownerDocument;
    this.tagName = tagName.toUpperCase();
    this.nodeType = nodeType;
    this.namespaceURI = "http://www.w3.org/1999/xhtml";
    this.parentNode = null;
    this.children = [];
    this.className = "";
    this.classList = new FakeClassList(this);
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this.selected = false;
    this.value = "";
    this.attributes = new Map();
    this._textContent = "";
    this._innerHTML = "";
  }

  get textContent() {
    return this._textContent;
  }

  set textContent(value) {
    this.replaceChildren();
    this._textContent = String(value ?? "");
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set innerHTML(value) {
    this.replaceChildren();
    this._innerHTML = String(value ?? "");
  }

  appendChild(node) {
    if (node.parentNode) {
      node.parentNode.children = node.parentNode.children.filter(
        (child) => child !== node,
      );
    }
    node.parentNode = this;
    this.children.push(node);
    return node;
  }

  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index < 0) throw new Error("node is not a child");
    this.children.splice(index, 1);
    node.parentNode = null;
    return node;
  }

  contains(node) {
    return this === node || this.children.some((child) => child.contains(node));
  }

  replaceChildren(...nodes) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this._textContent = "";
    this._innerHTML = "";
    for (const node of nodes) this.appendChild(node);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
}

class FakeWindow extends EventTarget {
  constructor() {
    super();
    this.location = { hash: "#/items" };
    this.listenerCounts = new Map();
  }

  addEventListener(type, callback, options) {
    super.addEventListener(type, callback, options);
    this.listenerCounts.set(type, (this.listenerCounts.get(type) || 0) + 1);
  }

  removeEventListener(type, callback, options) {
    super.removeEventListener(type, callback, options);
    this.listenerCounts.set(
      type, Math.max(0, (this.listenerCounts.get(type) || 0) - 1),
    );
  }
}

export class FakeDocument {
  constructor() {
    this.defaultView = new FakeWindow();
  }

  createElement(tagName) {
    return new FakeNode(this, tagName);
  }
}

export function allNodes(root) {
  return [root, ...root.children.flatMap(allNodes)];
}

export function byClass(root, name) {
  return allNodes(root).filter((node) => node.classList.contains(name));
}

function okResult(result) {
  return { status: 200, envelope: { success: true, result } };
}

export function injectedClient(label) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okResult({ name: `${label} org` });
      }
      if (request.function === "projects.list") {
        return okResult({ rows: [{ id: label, name: `${label} project` }] });
      }
      if (request.function === "items.list.run") {
        return okResult({ rows: [] });
      }
      if (request.function === "strategy.doc.list") {
        return okResult({ docs: [] });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

export async function settle() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
}

export function response(status, payload) {
  return { status, async text() { return JSON.stringify(payload); } };
}
