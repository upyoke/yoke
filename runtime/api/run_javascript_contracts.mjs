// Each worker owns its globals and module cache while Node starts only once.
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import { run } from 'node:test';
import { inspect } from 'node:util';

async function runWorker() {
  const results = run({ files: [workerData], isolation: 'none' });
  let failed = true;
  let output = '';
  for await (const { type, data } of results) {
    if (type === 'test:summary') failed = !data.success;
    if (type === 'test:fail' || type === 'test:diagnostic') {
      output += `${inspect(data, { depth: 6, colors: false })}\n`;
    }
  }
  parentPort.postMessage({ failed, output });
}

async function runModule(filename) {
  await new Promise((resolve) => {
    const worker = new Worker(new URL(import.meta.url), {
      workerData: filename,
      stdout: true,
      stderr: true,
    });
    let output = '';
    let completed = false;
    worker.on('message', (result) => {
      completed = true;
      if (result.failed) {
        process.exitCode = 1;
        console.error(`JavaScript module failed: ${filename}\n${output}${result.output}`);
      } else {
        console.log(`Passed JavaScript module: ${filename}`);
      }
      void worker.terminate();
    });
    worker.stdout.on('data', (data) => { output += data; });
    worker.stderr.on('data', (data) => { output += data; });
    worker.on('error', (error) => { output += `${error.stack}\n`; });
    worker.on('exit', () => {
      if (!completed) {
        process.exitCode = 1;
        console.error(`JavaScript module failed: ${filename}\n${output}`);
      }
      resolve();
    });
  });
}

async function runSuite() {
  const modules = process.argv.slice(2);
  if (!modules.length) throw new Error('javascript_modules_missing: pass test files');
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(16, modules.length) }, async () => {
    while (next < modules.length) await runModule(modules[next++]);
  }));
  console.log(`Executed ${modules.length} JavaScript test modules`);
}

if (isMainThread) await runSuite();
else await runWorker();
