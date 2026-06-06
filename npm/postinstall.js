#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const packageRoot = path.resolve(__dirname, "..");
const venvDir = path.join(packageRoot, ".npm-python");

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

function findPython() {
  for (const candidate of candidates()) {
    const result = spawnSync(candidate.command, [...candidate.args, "--version"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"]
    });
    if (result.status === 0) {
      return candidate;
    }
  }
  return null;
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
  const python = findPython();
  if (!python) {
    console.error("FinCLI requires Python 3.11+ during npm install.");
    console.error("Install Python, then rerun: npm install -g fincli");
    process.exit(1);
  }

  if (!fs.existsSync(venvPython())) {
    run(python.command, [...python.args, "-m", "venv", venvDir]);
  }

  run(venvPython(), ["-m", "pip", "install", "--upgrade", "pip"]);
  run(venvPython(), ["-m", "pip", "install", "."]);
}

main();
