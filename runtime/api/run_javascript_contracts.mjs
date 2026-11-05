// Run files sequentially with fresh module instances and restored globals.
import { readFileSync } from 'node:fs';
import { isBuiltin } from 'node:module';
import * as nodeTest from 'node:test';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';

const sources = new Map();
const builtins = new Map();
// Node's web globals install a permanent dispatcher symbol on first access.
void globalThis.Response;
function isolateGlobals(t) {
  const globals = Object.getOwnPropertyDescriptors(globalThis);
  const handles = [];
  for (const [start, stop] of [
    ['setTimeout', 'clearTimeout'], ['setInterval', 'clearInterval'],
    ['setImmediate', 'clearImmediate'],
  ]) {
    const schedule = globalThis[start];
    const clear = globalThis[stop];
    globalThis[start] = (...args) => {
      const handle = schedule(...args);
      handles.push(() => clear(handle));
      return handle;
    };
  }
  t.after(() => {
    for (const clear of handles) clear();
    nodeTest.mock.reset();
    for (const name of Reflect.ownKeys(globalThis)) {
      if (!Object.hasOwn(globals, name)) delete globalThis[name];
    }
    Object.defineProperties(globalThis, globals);
  });
}

function testExports(pending) {
  const exports = { ...nodeTest };
  const remember = (fn, args) => {
    const promise = fn(...args);
    pending.push(promise);
    return promise;
  };
  for (const name of ['default', 'test', 'it', 'describe', 'suite']) {
    const original = nodeTest[name];
    const wrapped = (...args) => remember(original, args);
    Object.assign(wrapped, original);
    for (const mode of ['skip', 'todo', 'only']) {
      wrapped[mode] = (...args) => remember(original[mode], args);
    }
    exports[name] = wrapped;
  }
  Object.assign(exports.default, exports);
  return exports;
}

function loaderFor(pending) {
  const modules = new Map();
  async function load(specifier, parent) {
    const builtin = isBuiltin(specifier);
    const identifier = builtin ? specifier : new URL(specifier, parent).href;
    if (!modules.has(identifier)) {
      modules.set(identifier, (async () => {
        if (builtin) {
          if (!builtins.has(identifier)) builtins.set(identifier, import(identifier));
          const exports = identifier === 'node:test' ? testExports(pending) : await builtins.get(identifier);
          return new vm.SyntheticModule(Object.keys(exports), function () {
            for (const [name, value] of Object.entries(exports)) this.setExport(name, value);
          }, { identifier });
        }
        const url = new URL(identifier);
        const filename = url.pathname;
        if (!sources.has(filename)) sources.set(filename, { text: readFileSync(url, 'utf8') });
        const source = sources.get(filename);
        // Reuse compiled code, never a module's evaluated state.
        const module = new vm.SourceTextModule(source.text, {
          identifier, cachedData: source.cachedData,
          initializeImportMeta(meta) { meta.url = identifier; },
          importModuleDynamically: evaluate,
        });
        source.cachedData ??= module.createCachedData();
        return module;
      })());
    }
    return modules.get(identifier);
  }
  async function evaluate(specifier, referencing) {
    const module = await load(specifier, referencing?.identifier);
    if (module.status === 'unlinked') {
      await module.link((name, parent) => load(name, parent.identifier));
    }
    await module.evaluate();
    return module;
  }
  return evaluate;
}

const files = process.argv.slice(2);
if (!files.length) throw new Error('javascript_modules_missing: pass test files');
for (const filename of files) {
  await nodeTest.test(filename, async (t) => {
    const pending = [];
    isolateGlobals(t);
    const evaluate = loaderFor(pending);
    await evaluate(pathToFileURL(filename).href);
    // Await every registered test before its file's parent can finish.
    for (let next = 0; next < pending.length; next++) await pending[next];
  });
}
