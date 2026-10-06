# Eval results

Run on 2026-10-06 (v0.1.0) on Windows 11, Python 3.14, Node 24, pytest 9.1.
Each behaviour eval ran in a fresh sub-agent with no context other than the
installed skill, the scenario repo, and the user prompt. Prompts and the full
expectation lists are in [`evals.json`](evals.json); scenarios are rebuilt with
`scenarios/make_shop.py` and `scenarios/make_queue.py`.

## Script tests

`python -m unittest discover -s tests`: 19 tests, all passing (JUnit dialects from
pytest, node:test, Surefire-style namespaced suites, duplicate ids, `go test -json`,
the verdict matrix, confidence maths, end-to-end `run`/`classify` with a scripted
flaky runner, stale-result handling, polluter bisection, Windows path handling).

## Behaviour (Claude Code sub-agents, default model)

| Eval | Result | Notes |
|---|---|---|
| shop-red-after-change | 7/7 | 10 head + 10 base runs in a worktree; fixed `shop/cart.py`, not the tests; `test_tax_rounding` reported as pre-existing; `test_price_label` order-dependent with `test_euro_override` found by `polluter`; flaky id test reported (3/10 head, 4/10 base); no retries or skips; verdict table with run counts |
| shop-deflake-ids | 4/4 | measured 9/30 and 8/30; product bug in `shop/ids.py` fixed with `uuid4`, test unchanged; `runs-needed` = 9, verified 30/30 |
| shop-order-dependence | 3/3 | 0/5 full-suite vs 5/5 alone; polluter bisected; fixed the polluter with `monkeypatch.setitem`, 10/10 after |
| shop-red-after-change (re-run on the final SKILL.md) | 7/7 | fixed only `cart.py`; first sentence says the suite is still not green and why; all three remaining failures reported with base/isolated evidence and the polluter |
| queue-timing-flake | 4/4 | 9/20 failures measured with the node:test JUnit reporter; `enqueue` now returns a promise the test awaits; 50/50 clean, plus 20/20 under CPU load |

## Behaviour on a smaller model (Haiku), shop-red-after-change

| Skill version | Result | Notes |
|---|---|---|
| before "Done when" checklist | 4/7 | correct fix in `cart.py`, nothing hidden, but skipped the isolated run (called the order-dependent test "pre-existing"), no polluter, no run-count table |
| with checklist | 3/7 | base runs and a table this time, but said "the suite is now green" while three tests still failed and left them out |
| with checklist + "never say green unless it is" rule | 5/7 | honest and complete (polluter found, every failure accounted for), but "fixed" the flaky id test by loosening its assertion, which the skill forbids |

Smaller models follow the procedure inconsistently from run to run. The skill is
recommended with frontier-tier models; the README says so.

## Triggering (skill-router simulation, 7 neighbouring skill descriptions)

| Description version | Sonnet | Haiku |
|---|---|---|
| v1 | 11/12 (missed "suite is red after my change, get it green") | 11/12 (same miss) |
| v2 (shipped) | 13/13 decided + 1 either | 13/13 decided + 1 either |

Should-not-trigger prompts (write tests, CI setup, explain code, rename, speed up
suite, raise coverage, runtime crash) were never routed to this skill.

## Fixes made because of these evals

- `run` now pre-creates the results directory: node:test's JUnit reporter silently
  writes nothing when it is missing, which made the first run look like a crash.
- Runs that write no results are left out of per-test counts and reported
  separately, instead of polluting the tallies.
- `run` no longer deletes files matching `--results`; it reads only files written
  during the run (a broad glob could have deleted committed XML fixtures).
- Git Bash paths (`/c/...`) in `--results` are converted on Windows, with a hint
  when every run writes nothing (three of five agents hit this on their first try).
- SKILL.md: explicit "no `git stash`/`checkout`" rule (one agent stashed to check
  the base), the description rewritten to cover "suite is red after my change",
  a "Done when" checklist after a Haiku run skipped steps, and a rule against
  claiming the suite is green while tests still fail.
