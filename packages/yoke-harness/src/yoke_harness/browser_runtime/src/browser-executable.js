'use strict';

// Python projects the single machine setting into every runtime process.
function executablePath() {
  return process.env.YOKE_BROWSER_EXECUTABLE_PATH || undefined;
}

function launchOptions() {
  const executable = executablePath();
  return executable ? { executablePath: executable } : {};
}

module.exports = { executablePath, launchOptions };
