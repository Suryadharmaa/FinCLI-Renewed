#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const packageRoot = path.resolve(__dirname, "..", "..");
const packageJson = require(path.join(packageRoot, "package.json"));
const venvDir = path.join(packageRoot, ".npm-python");
const pythonBin = process.platform === "win32"
  ? path.join(venvDir, "Scripts", "python.exe")
  : path.join(venvDir, "bin", "python");

function run() {
  const args = process.argv.slice(2);
  if (args.includes("--version") || args.includes("-v")) {
    console.log(packageJson.version);
    return;
  }

  if (!fs.existsSync(pythonBin)) {
    console.error("FinCLI Python runtime is missing.");
    console.error("Try reinstalling with: npm install -g @drico2008/fincli");
    console.error("Python 3.11+ must be available during npm install.");
    process.exit(1);
  }

  const child = spawn(pythonBin, ["-m", "fincli.app.main", ...args], {
    cwd: packageRoot,
    stdio: "inherit"
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 0);
  });
}

run();
