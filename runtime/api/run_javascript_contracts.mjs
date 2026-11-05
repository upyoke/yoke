// Run isolated file batches in one Node process with shared compiled sources.
import { readFileSync } from 'node:fs';
import { isBuiltin } from 'node:module';
import * as nodeTest from 'node:test';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';

const sources = new Map();
const builtins = new Map();
// Node's web globals install a permanent dispatcher symbol on first access.
void globalThis.Response;

function isolateGlobals() {
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
  return () => {
    for (const clear of handles) clear();
    nodeTest.mock.reset();
    for (const name of Reflect.ownKeys(globalThis)) {
      if (!Object.hasOwn(globals, name)) delete globalThis[name];
    }
    Object.defineProperties(globalThis, globals);
  };
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

async function runFiles(files) {
  for (const filename of files) {
    parentPort.postMessage({ filename });
    let restore;
    try {
      await nodeTest.test(filename, async () => {
        const pending = [];
        restore = isolateGlobals();
        const evaluate = loaderFor(pending);
        await evaluate(pathToFileURL(filename).href);
        // Await every registered test before its file's parent can finish.
        for (let next = 0; next < pending.length; next++) await pending[next];
      });
    } finally {
      try {
        restore?.();
      } catch (cause) {
        throw new Error(
          `javascript_globals_restore_failed: ${filename}; make test globals configurable and restore mutations in cleanup`,
          { cause },
        );
      }
    }
  }
  parentPort.postMessage({ completed: true });
}

async function runBatches(files) {
  const batches = Array.from({ length: Math.min(4, files.length) }, () => []);
  files.forEach((filename, index) => batches[index % batches.length].push(filename));
  await Promise.all(batches.map((batch) => new Promise((resolve) => {
    const worker = new Worker(new URL(import.meta.url), {
      workerData: batch, stdout: true, stderr: true,
    });
    let output = '';
    let completed = false;
    let activeFile = batch[0];
    worker.stdout.on('data', (data) => { output += data; });
    worker.stderr.on('data', (data) => { output += data; });
    worker.on('error', (error) => { output += `${error.stack}\n`; });
    worker.on('message', (message) => {
      if (message.filename) activeFile = message.filename;
      if (message.completed) completed = true;
    });
    worker.on('exit', (code) => {
      if (!completed || code !== 0) {
        process.exitCode = 1;
        if (!completed) {
          output = `javascript_worker_incomplete: ${activeFile}; let tests finish before exiting\n${output}`;
        }
        console.error(output);
      }
      resolve();
    });
  })));
}

const files = isMainThread ? process.argv.slice(2) : workerData;
if (!files.length) throw new Error('javascript_modules_missing: pass test files');
if (isMainThread) await runBatches(files);
else await runFiles(files);
