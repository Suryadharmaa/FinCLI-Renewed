#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

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

  // Handle setup command
  if (args.includes("setup") || args.includes("--setup")) {
    runSetup();
    return;
  }

  // Check if venv exists
  if (!fs.existsSync(pythonBin)) {
    console.error("FinCLI Python runtime not found.");
    console.error("Run: fincli setup");
    console.error("Or: node npm/setup.js");
    process.exit(1);
  }

  ensurePythonRuntime();

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

function runSetup() {
  const setupScript = path.join(__dirname, "..", "setup.js");
  if (!fs.existsSync(setupScript)) {
    console.error("Setup script not found: npm/setup.js");
    process.exit(1);
  }
  const result = spawnSync(process.execPath, [setupScript], {
    cwd: packageRoot,
    stdio: "inherit"
  });
  process.exit(result.status ?? 0);
}

function ensurePythonRuntime() {
  const probe = spawnSync(pythonBin, ["-c", "import textual, rich, httpx, pydantic, yfinance, pandas, numpy"], {
    cwd: packageRoot,
    stdio: "ignore"
  });
  if (probe.status === 0) {
    return;
  }

  console.error("FinCLI Python dependencies are incomplete. Repairing local npm runtime...");
  const repair = spawnSync(pythonBin, ["-m", "pip", "install", "."], {
    cwd: packageRoot,
    stdio: "inherit"
  });
  if (repair.status !== 0) {
    console.error("FinCLI runtime repair failed.");
    console.error("Try: fincli setup");
    process.exit(repair.status ?? 1);
  }
}

run();
