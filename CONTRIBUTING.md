# Contributing to FinCLI

Thanks for helping improve FinCLI. This project is a local-first financial CLI/TUI, so contributions should prioritize reliability, safety, clear user output, and testable behavior.

## Ways to Contribute

- Fix bugs in commands, providers, storage, packaging, or tests.
- Improve documentation, command examples, and setup guidance.
- Add tests for existing behavior.
- Improve provider reliability, data quality handling, or safety warnings.
- Suggest features in small, focused issues before implementing large changes.

## Requirements

- Python 3.11 or newer
- Node.js 18 or newer
- npm
- Git

Optional but recommended:

- A virtual environment
- API keys only for manual provider testing; never required for normal unit tests

## Local Setup

```bash
git clone https://github.com/Suryadharmaa/FinCLI-Renewed.git
cd FinCLI-Renewed
python -m venv .venv
```

Activate the environment:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Check the CLI starts:

```bash
fincli --help
```

## Development Workflow

1. Create a focused branch.
2. Keep changes small and reviewable.
3. Add or update tests for behavior changes.
4. Run lint and targeted tests before opening a pull request.
5. Update docs when commands, public behavior, setup, or release claims change.

Example:

```bash
git checkout -b fix/provider-trust-output
python -m ruff check fincli tests scripts
python -m pytest tests/test_command_smoke.py
```

## Test Commands

Run these before submitting a pull request when relevant:

```bash
python -m ruff check fincli tests scripts
python -m pytest
npm run check
python scripts/prepublish_check.py
```

For packaging or npm wrapper changes, also run:

```bash
python -m pytest tests/test_phase19_npm_wrapper.py
npm run check
```

For provider or command routing changes, run:

```bash
python -m pytest tests/test_command_smoke.py tests/test_provider_system_v2.py
```

For security-sensitive changes, run:

```bash
python -m pytest tests/test_security.py
python scripts/prepublish_check.py
```

## Code Style

- Prefer clear, small functions over broad rewrites.
- Keep public command behavior stable unless the change is intentional and documented.
- Use `ruff` as the source of truth for linting.
- Avoid adding dependencies unless there is a strong reason.
- Keep terminal output readable on Windows, macOS, and Linux.
- Prefer ASCII for CLI/npm wrapper output unless Unicode is already known to render safely.

## Public Interface Rules

Treat these as public interfaces:

- Slash commands and arguments
- Config keys and environment variables
- SQLite schema and stored data formats
- Provider contracts and return objects
- npm package entrypoints
- Files included in npm/Python packaging

If a change affects a public interface, document it in the PR and update README/docs/tests.

## Financial and AI Safety

FinCLI may display market data, AI summaries, trading workflows, and broker-related actions. Contributions must preserve these safety principles:

- Do not present AI output as financial advice.
- Do not invent prices, provider status, news, or fundamentals.
- Surface missing, stale, delayed, or low-quality data clearly.
- Keep broker/trading actions explicit and confirmation-based.
- Never weaken kill switches, audit logging, or secret redaction.

## Security Guidelines

Never commit:

- `.env` files
- API keys or broker credentials
- SQLite databases
- logs containing secrets
- generated virtual environments
- npm/Python build artifacts

Before publishing or proposing packaging changes:

```bash
python scripts/prepublish_check.py
```

If you find a security issue, do not open a public issue with exploit details. Report it privately to the maintainer.

## Documentation

Update documentation when changing:

- Commands or command examples
- Installation/setup behavior
- Provider support or limitations
- Version/release claims
- Packaging behavior
- Security or data-quality behavior

Main docs:

- `README.md`
- `docs/commands.md`
- `TASK.md` for active release/readiness tracking

## Pull Request Checklist

Before opening a PR, confirm:

- The change is scoped and easy to review.
- Tests were added or updated when behavior changed.
- `python -m ruff check fincli tests scripts` passes.
- Relevant `pytest` commands pass.
- `npm run check` passes for npm wrapper changes.
- `python scripts/prepublish_check.py` passes for packaging/release changes.
- Docs are updated where needed.
- No secrets, caches, local databases, or build artifacts are included.

## Release Notes

For release-facing changes, update the changelog in `README.md` and ensure versions align across:

- `pyproject.toml`
- `package.json`
- `fincli/__init__.py`
- README/docs release claims
- relevant tests

## Questions

If you are unsure whether a change is in scope, open an issue first with:

- The user problem
- Proposed behavior
- Risks or compatibility concerns
- Suggested tests

Small, well-tested improvements are very welcome.
