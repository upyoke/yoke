// Each file owns its globals and module cache inside one JavaScript engine.
import { readFileSync } from 'node:fs';
import { isBuiltin } from 'node:module';
import * as nodeTest from 'node:test';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';

const sources = new Map();
const builtins = new Map();
const intrinsics = new Set(vm.runInNewContext('Object.getOwnPropertyNames(globalThis)'));

function sandboxFor(t) {
  const sandbox = {};
  for (const name of Object.getOwnPropertyNames(globalThis)) {
    if (!intrinsics.has(name) && name !== 'global') {
      Object.defineProperty(sandbox, name, Object.getOwnPropertyDescriptor(globalThis, name));
    }
  }
  const handles = [];
  for (const [start, stop] of [
    ['setTimeout', 'clearTimeout'], ['setInterval', 'clearInterval'],
    ['setImmediate', 'clearImmediate'],
  ]) {
    sandbox[start] = (...args) => {
      const handle = globalThis[start](...args);
      handles.push(() => globalThis[stop](handle));
      return handle;
    };
  }
  t.after(() => { for (const clear of handles) clear(); });
  const context = vm.createContext(sandbox);
  vm.runInContext('global = globalThis', context);
  return context;
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

function loaderFor(context, pending) {
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
          }, { context, identifier });
        }
        const url = new URL(identifier);
        const filename = url.pathname;
        if (!sources.has(filename)) sources.set(filename, { text: readFileSync(url, 'utf8') });
        const source = sources.get(filename);
        const module = new vm.SourceTextModule(source.text, {
          context, identifier, cachedData: source.cachedData,
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
    const evaluate = loaderFor(sandboxFor(t), pending);
    await evaluate(pathToFileURL(filename).href);
    // Await every registered test before its file's parent can finish.
    for (let next = 0; next < pending.length; next++) await pending[next];
  });
}
