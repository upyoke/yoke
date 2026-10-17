'use strict';

// Python projects the single machine setting into every runtime process.
function executablePath() {
  return process.env.YOKE_BROWSER_EXECUTABLE_PATH || undefined;
}

function launchOptions() {
  // Setup projects YOKE_BROWSER_CHROMIUM_SANDBOX=0 when the sandbox cannot be
  // enabled without root. Unset keeps the sandbox on.
  const options = {
    chromiumSandbox: process.env.YOKE_BROWSER_CHROMIUM_SANDBOX !== '0',
  };
  const executable = executablePath();
  if (executable) options.executablePath = executable;
  return options;
}

module.exports = { executablePath, launchOptions };
