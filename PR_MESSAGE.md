# Summary

- Finalized checkpoint 4 CLI UX for the MVP `stedgeai` path: `arona optimize --deploy` now runs
  STM32N6 `generate -> build -> program -> validate`, while `--deployment-result` remains available
  for reusing existing validation evidence.
- Integrated deployment evidence into optimization runs as `deployment/deployment-result.json`,
  `deployment-analysis.json`, terminal output, and `report.md`.
- Expanded Markdown/terminal reports with toolchain version, model checksum, compiler before/after,
  rewrite validation, final decision, board deployment status, deployment stages, artifact checksum,
  and target observation latency summary.
- Added checkpoint 4 regression tests for live deployment orchestration, deployment-result reuse,
  and target rejection.
- Added `docs/demo.md` and updated README/TODO to match the current reproducible MVP behavior.

# Validation

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy src`
- `uv run pytest` -> 48 passed, 1 skipped
- Clean checkout smoke from a local clone: `uv sync --frozen`, `uv run arona --help`,
  `uv run arona optimize --help`, `uv run pytest` -> 48 passed, 1 skipped

# Known gaps and PR notes

- Full `arona optimize --deploy` requires ST Edge AI Core, STM32CubeIDE/CLT,
  STM32CubeProgrammer, vendor STM32N6 application checkouts, FSBL, a connected NUCLEO-N657X0-Q,
  and the operator-controlled boot-mode/power-cycle steps.
- The clean checkout smoke path is reproducible with committed fixtures and tests. Full
  optimize-to-deploy replay still requires ST toolchain installation, downloaded model binaries, vendor
  application checkouts, and a connected NUCLEO-N657X0-Q.
- `outputs/checkpoint3/` contains local hardware evidence and is intentionally gitignored. The repo
  preserves redistributable logs, metadata, checksums, and regeneration steps instead of model binaries
  or vendor build artifacts.
- Checkpoint 3 target evidence used fixed-input smoke validation. Baseline/optimized target latency
  under identical conditions has not yet been measured as a performance claim.
