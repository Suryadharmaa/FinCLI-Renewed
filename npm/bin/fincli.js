#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const https = require("https");
const { spawn, spawnSync } = require("child_process");

const packageRoot = path.resolve(__dirname, "..", "..");
const packageJson = require(path.join(packageRoot, "package.json"));
const venvDir = path.join(packageRoot, ".npm-python");
const pythonBin = process.platform === "win32"
  ? path.join(venvDir, "Scripts", "python.exe")
  : path.join(venvDir, "bin", "python");

// ── Update notifier ──────────────────────────────────────────────────────────

const UPDATE_CHECK_TTL = 86400000; // 24 hours
const REGISTRY_URL = `https://registry.npmjs.org/${packageJson.name}/latest`;
const REQUEST_TIMEOUT_MS = 3000;

function getUpdateCachePath() {
  const fincliDir = path.join(require("os").homedir(), ".fincli");
  if (!fs.existsSync(fincliDir)) {
    fs.mkdirSync(fincliDir, { recursive: true });
  }
  return path.join(fincliDir, ".update-check");
}

function readUpdateCache() {
  try {
    const raw = fs.readFileSync(getUpdateCachePath(), "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeUpdateCache(latestVersion) {
  try {
    fs.writeFileSync(getUpdateCachePath(), JSON.stringify({
      lastCheck: Date.now(),
      latestVersion,
    }), "utf8");
  } catch {
    // ignore write errors
  }
}

function parseSemver(str) {
  const match = str.match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function isNewer(current, latest) {
  for (let i = 0; i < 3; i++) {
    if (latest[i] > current[i]) return true;
    if (latest[i] < current[i]) return false;
  }
  return false;
}

function showUpdateBanner(currentVersion, latestVersion) {
  const msg = `Update available: ${currentVersion} → ${latestVersion}`;
  const cmd = `npm i -g ${packageJson.name}`;
  const line = "═".repeat(msg.length + 4);
  process.stderr.write(
    `\n╔${line}╗\n║  ${msg}  ║\n║  Run: ${cmd}${" ".repeat(Math.max(0, msg.length - cmd.length - 6))}  ║\n╚${line}╝\n\n`
  );
}

function fetchLatestVersion() {
  return new Promise((resolve) => {
    const req = https.get(REGISTRY_URL, { timeout: REQUEST_TIMEOUT_MS }, (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        return resolve(null);
      }
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        try {
          const data = JSON.parse(body);
          resolve(typeof data.version === "string" ? data.version : null);
        } catch {
          resolve(null);
        }
      });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => { req.destroy(); resolve(null); });
  });
}

async function checkForUpdate() {
  // Skip in CI environments
  if (process.env.CI || process.env.GITHUB_ACTIONS) return;

  const currentVersion = packageJson.version;
  const currentParsed = parseSemver(currentVersion);
  if (!currentParsed) return;

  const cache = readUpdateCache();

  // If cache is fresh and version hasn't changed, just show banner if needed
  if (cache && cache.lastCheck && (Date.now() - cache.lastCheck) < UPDATE_CHECK_TTL) {
    const cachedParsed = parseSemver(cache.latestVersion);
    if (cachedParsed && isNewer(currentParsed, cachedParsed)) {
      showUpdateBanner(currentVersion, cache.latestVersion);
    }
    return;
  }

  // Fetch from registry
  const latestVersion = await fetchLatestVersion();
  if (!latestVersion) return;

  writeUpdateCache(latestVersion);

  const latestParsed = parseSemver(latestVersion);
  if (latestParsed && isNewer(currentParsed, latestParsed)) {
    showUpdateBanner(currentVersion, latestVersion);
  }
}

// ── Main ─────────────────────────────────────────────────────────────────────

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

  // Check for updates (non-blocking, result shown before app renders)
  checkForUpdate().catch(() => {});

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
