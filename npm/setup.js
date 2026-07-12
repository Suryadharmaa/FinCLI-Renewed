#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const packageRoot = path.resolve(__dirname, "..");
const venvDir = path.join(packageRoot, ".npm-python");
const MIN_PYTHON = [3, 11];

function candidates() {
  if (process.env.PYTHON) {
    return [{ command: process.env.PYTHON, args: [] }];
  }
  if (process.platform === "win32") {
    return [
      { command: "py", args: ["-3"] },
      { command: "python", args: [] }
    ];
  }
  return [
    { command: "python3", args: [] },
    { command: "python", args: [] }
  ];
}

function pythonVersion(candidate) {
  const result = spawnSync(
    candidate.command,
    [...candidate.args, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  );
  if (result.status !== 0 || typeof result.stdout !== "string") {
    return null;
  }
  const match = result.stdout.trim().match(/^(\d+)\.(\d+)$/);
  if (!match) {
    return null;
  }
  return [Number(match[1]), Number(match[2])];
}

function meetsMinimum(version) {
  if (!version) {
    return false;
  }
  if (version[0] !== MIN_PYTHON[0]) {
    return version[0] > MIN_PYTHON[0];
  }
  return version[1] >= MIN_PYTHON[1];
}

function findPython() {
  let foundButTooOld = null;
  for (const candidate of candidates()) {
    const version = pythonVersion(candidate);
    if (!version) {
      continue;
    }
    if (meetsMinimum(version)) {
      return { candidate, version };
    }
    foundButTooOld = foundButTooOld || version;
  }
  return { candidate: null, version: foundButTooOld };
}

function venvPython() {
  return process.platform === "win32"
    ? path.join(venvDir, "Scripts", "python.exe")
    : path.join(venvDir, "bin", "python");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: packageRoot,
    stdio: "inherit",
    ...options
  });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed`);
  }
}

function main() {
  const minimum = MIN_PYTHON.join(".");
  const { candidate: python, version } = findPython();
  if (!python) {
    if (version) {
      console.error(
        `FinCLI requires Python ${minimum}+, but found Python ${version.join(".")}.`
      );
      console.error(`Install Python ${minimum}+ (or set PYTHON to its path), then rerun: npm install -g fincli`);
    } else {
      console.error(`FinCLI requires Python ${minimum}+ during npm install.`);
      console.error("Install Python, then rerun: npm install -g fincli");
    }
    process.exit(1);
  }

  if (!fs.existsSync(venvPython())) {
    run(python.command, [...python.args, "-m", "venv", venvDir]);
  }

  run(venvPython(), ["-m", "pip", "install", "--upgrade", "pip"]);
  run(venvPython(), ["-m", "pip", "install", ".[web]"]);
}

main();
