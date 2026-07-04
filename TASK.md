# FinCLI v1.8.4 Trust & Reliability Release Checklist

## Summary
v1.8.4 is a focused Trust & Reliability release. The release fixes v1.8.3 readiness blockers, adds one user-facing reliability command, and verifies that FinCLI can explain provider trust before users rely on market or AI output.

## Scope
- Fix release blockers from the prior checklist before feature work.
- Add `/provider trust` as the only new public command.
- Keep the release small: no database migration, no new dependencies, and no provider API contract changes.
- Preserve existing dirty user work unless directly related to release readiness.

## Implemented Changes
- [x] Cleaned `ruff check fincli tests scripts`.
- [x] Fixed command smoke failures for `/news_model use`, `/news_model priority`, and `/yahoo` by isolating test config/database state.
- [x] Added `/provider trust` to command routing and command registry.
- [x] `/provider trust` reports provider chain, latest provider result, cache state, recent errors, runtime metrics, fallback/circuit state, trust label, AI confidence limit, and suggested action.
- [x] Trust labels use the release vocabulary: `Strong`, `Usable`, `Limited`, `Blocked`.
- [x] Added focused tests for healthy, degraded, missing-price, and no-data provider trust states.
- [x] Fixed pytest-anyio/Textual release blocker by forcing anyio tests to the asyncio backend.
- [x] Bumped release metadata to `1.8.4` in `pyproject.toml`, `package.json`, and `fincli/__init__.py`.
- [x] Updated README changelog and provider command reference.
- [x] Updated docs command reference for `/provider trust` and v1.8.4.

## Verification Results
| Check | Result | Notes |
|---|---:|---|
| Ruff | PASS | `python -m ruff check fincli tests scripts` -> `All checks passed!` |
| Smoke group 1 | PASS | `python -m pytest tests/test_command_smoke.py tests/test_config.py tests/test_security.py tests/test_phase184_provider_trust.py` -> `183 passed` |
| Smoke group 2 | PASS | `python -m pytest tests/test_provider_system_v2.py tests/test_phase19_npm_wrapper.py` -> `21 passed` |
| AnyIO/TUI blocker check | PASS | `python -m pytest tests/test_phase15_tui_palette.py tests/test_phase20_ai_model_selector.py tests/test_phase21_ai_chat_tui.py tests/test_phase22_system_commands.py tests/test_phase23_market_provider_selector.py tests/test_phase24_tui_nonblocking.py tests/test_phase29_provider_intelligence.py` -> `19 passed` |
| Full pytest | PASS | `python -m pytest` -> `780 passed` |
| npm wrapper check | PASS | `npm.cmd run check` validated `npm/bin/fincli.js` and `npm/setup.js` |
| Prepublish safety | PASS | `python scripts/prepublish_check.py` -> package safety check passed |
| Version alignment | PASS | Core release metadata and user-facing docs now claim `1.8.4` |

## Known Blockers
- None observed in the final verification run.

## Known Non-Blockers
- Historical changelog entries still mention older releases such as `v1.8.3`.
- Some module docstrings still mention old feature phase labels such as `v0.8.0`; these are not current release claims or command-reference entries.

## Final Release Status
`v1.8.4` is release-ready from the local verification performed here. Next action: review the diff, then package/publish using the normal release process.
