# FinCLI Next Major — Provider System v3 + Research Engine v4

## Summary
Build the next major FinCLI update after v1.8.5 by activating dormant Polygon/IEX providers and upgrading `/research --report` into a structured, citation-aware Research Engine v4 report.

## Scope
- Wire Polygon and IEX into provider manager, config, TUI selector, router key handling, and symbol intelligence.
- Complete provider contract methods for Polygon/IEX: `news()`, `capabilities()`, and realtime metadata.
- Upgrade report mode with facts, inferences, missing-data severity, scenario matrix, source scoring, and citation IDs.
- Preserve deterministic snapshot mode and existing v1.8.5 TUI cockpit behavior.
- Do not add broad router refactors or new dependencies.

## Implementation Checklist
- [x] Provider contract tests for Polygon/IEX
- [x] Provider manager/config wiring
- [x] TUI selector and router secret mappings
- [x] Symbol matrix/provider intelligence updates
- [x] Research model schema extension
- [x] Research report assembly upgrade
- [x] Prompt builder structured report contract
- [x] Formatter/exporter structured output
- [x] Targeted provider tests passing
- [x] Targeted research tests passing
- [x] Full validation passing

## Verification Commands
| Check | Command | Result |
|---|---|---|
| Ruff | `python -m ruff check fincli tests scripts` | PASS — All checks passed |
| Compile | `python -m compileall fincli -q` | PASS |
| Provider subset | `python -m pytest tests/test_provider_system_v2.py tests/test_phase23_market_provider_selector.py tests/test_phase9_provider_settings.py tests/test_phase29_provider_intelligence.py -q` | PASS — 38 passed in 7.54s |
| Research subset | `python -m pytest tests/test_phase64_research_engine_v3_v060.py tests/test_phase57_data_trust_gate_v040.py tests/test_phase63_provider_data_reliability_v050.py tests/test_phase27_web_research.py tests/test_phase47_research_v2_v030.py -q` | PASS — 23 passed in 4.73s |
| Full pytest | `python -m pytest` | PASS — 792 passed in 137.73s |
| npm wrapper | `npm.cmd run check` | PASS |
| Prepublish | `python scripts/prepublish_check.py` | PASS — safety check passed |
| npm pack | `npm pack --dry-run` | PASS — drico2008-fincli-1.8.5.tgz dry-run ok |

## Known Blockers
- None.

## Final Release Status
Provider System v3 + Research Engine v4 implementation is verified and validation passed.
