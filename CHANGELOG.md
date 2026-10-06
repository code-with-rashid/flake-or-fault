# Changelog

## 0.1.0 — 2026-10-06

First release.

- `flake-or-fault` skill: rerun-based verdicts (`broken-by-change`, `pre-existing`,
  `flaky`, `order-dependent`, `consistent-failure`, `inconclusive`) and a procedure
  for acting on each without retries, sleeps, or skips.
- `scripts/flakerun.py` (stdlib Python): `run` (repeat a command, parse JUnit XML or
  `go test -json`), `classify` (head vs base vs isolated), `polluter` (bisect an
  order-dependent victim's polluter), `runs-needed` (clean runs needed to claim a fix).
- References: per-runner recipes (pytest, Vitest, Jest, node:test, Playwright, Go,
  Maven, Gradle, .NET, cargo-nextest, RSpec, PHPUnit) and a root-cause catalogue.
- Unit tests and end-to-end evals with two reproducible scenarios.
