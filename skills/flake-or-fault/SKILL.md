---
name: flake-or-fault
description: >-
  Find out with reruns why tests fail before fixing anything: broken by the
  current change, already broken on the base branch, flaky, or order-dependent;
  then fix the real cause instead of adding retries, sleeps, or skips. Use when
  the test suite goes red after a change and the user wants it green, when a
  test fails intermittently or "passes locally but fails in CI", when it passes
  alone but fails in the full suite, when asked whether a CI failure was caused
  by a PR or was already broken on main, or to find, fix, deflake, or quarantine
  flaky tests. Works with any runner that writes JUnit XML, plus `go test
  -json`.
license: MIT
compatibility: Requires Python 3.8+ and git. The test runner must be able to write JUnit XML (or be Go).
metadata:
  version: "0.1.0"
  author: Rashid Mahmood
---

# Flake or fault

A red test is a claim, not a fact. Before you change code because of one, find
out which of these it is, using reruns rather than judgement:

| Verdict | Meaning | What to do |
|---|---|---|
| `broken-by-change` | fails every run on your code, passes every run on the base commit | Your bug. Fix the code, not the test. |
| `pre-existing` | fails on the base commit too | Not yours. Don't fix it inside this change; report it. |
| `flaky` | passes and fails on the same code | Don't change product code because of it. Deflake it, or report it. |
| `order-dependent` | fails in the full suite, passes on its own | Another test leaks state into it. Find the polluter. |
| `consistent-failure` | fails every run; no base runs yet | Rerun on the base commit to attribute it. |
| `inconclusive` | always fails on your code but flaky on base | Add runs on both sides before deciding. |

## Hard rules

- **Never call a test flaky without rerun evidence.** "It's probably flaky" is
  how real regressions ship. Show the pass/fail counts.
- **Never make a test green by hiding it**: no retries, longer sleeps, bumped
  timeouts, `skip`, loosened assertions, or deleting the test. These are only
  acceptable as an explicit, labelled quarantine that the user agrees to, with a
  tracking note saying how to undo it.
- **Never touch the user's working tree to test another commit**: no
  `git stash`, `git checkout`, or `git reset`. Use a separate worktree (step 3).
- **Don't fix a `pre-existing` or `flaky` failure inside an unrelated change**
  unless the user asks. Report it with its evidence instead.
- **Never say the suite is green unless the whole suite passed in every final
  run.** If you left any test failing (pre-existing, flaky, out of scope), say
  so in the first sentence of your reply and list each one in the report.
- **A fix is not verified until the failure rate is measured again.** One green
  run proves nothing about a test that failed 1 time in 10.

## The helper

`scripts/flakerun.py` (stdlib Python) runs a test command many times, reads the
JUnit XML it writes, and keeps per-test outcomes. Commands below assume you run
it from the project root as `python scripts/flakerun.py` with the path adjusted
to where this skill is installed. Put its output in a scratch directory such as
`.flake/` and keep that out of commits.

```bash
python <skill>/scripts/flakerun.py run --cmd "<test command>" --results "<junit glob>" --runs 10 --out .flake/head.json
python <skill>/scripts/flakerun.py classify --head .flake/head.json [--base .flake/base.json] [--isolated .flake/iso.json]
python <skill>/scripts/flakerun.py polluter --victim <id> --candidates .flake/before.txt --cmd-template "<cmd with {tests}>" --results "<glob>"
python <skill>/scripts/flakerun.py runs-needed --rate 0.1
```

`run` only reads result files written during each run, so a stale report is
never counted, and it never deletes anything. If a run writes no results it
records the exit code instead and says so; if every run says that, fix the
command or the `--results` glob rather than accept it. On Windows the command
runs under `cmd.exe`, so use Windows paths (`C:/...`) for programs in `--cmd`.

## Procedure

**1. Get a command that writes JUnit XML.** Find the project's own test command
(package scripts, Makefile, CI config), then add the runner's JUnit option from
[references/runners.md](references/runners.md). Narrow it to the failing tests
or their file first: ten runs of three tests beat two runs of three thousand.
Disable the runner's own retry features (they hide exactly what you're
measuring) and caching (Go needs `-count=1`).

**2. Rerun on the current code.** 10 runs for a narrowed command; 3-5 for a
slow full suite. If the test is suspected of failing rarely, use `runs-needed`
to pick a count. Then `classify --head`. Anything that passed at least once
and failed at least once is `flaky`: you are done attributing it.

**3. Attribute consistent failures to the change or not.** Run the same command
on the base commit in a separate git worktree, so the user's working tree is
never touched. Put the worktree outside the project directory, or the runner
may collect its tests twice:

```bash
git worktree add ../flake-base "$(git merge-base HEAD origin/main)"   # or the branch the change targets
# install dependencies there if they live in the tree (node_modules, vendor/, target/)
python <skill>/scripts/flakerun.py run --cwd ../flake-base --cmd "<same command>" --results "<glob>" --runs 5 --out .flake/base.json
python <skill>/scripts/flakerun.py classify --head .flake/head.json --base .flake/base.json
git worktree remove --force ../flake-base
```

If the change is uncommitted, the base is simply `HEAD`. CI history is useful
extra evidence: two runs on the same commit with different results
(`gh run list --commit <sha>`) prove flakiness without any reruns.

**4. Check order dependence.** Every test that failed in every full-suite run
must also be run on its own before you give it a verdict; a failure on base
can still be order-dependent. Run just that test (the runner's single-test selector, see
runners.md) into `.flake/iso.json` and classify with `--isolated`. For an
`order-dependent` verdict, write the tests that run before the victim to a
file, in order, and let `polluter` bisect them (`--victim` is the result id
from `classify`, `--victim-selector` the form the runner's command line takes); it prints the one test that
breaks the victim and a two-test command that reproduces it. For runners that
reorder tests themselves, see the order notes in runners.md.

**5. Act on the verdict** using the table at the top. When asked to deflake,
reproduce the failure at a higher rate first (shuffle, parallelism, `-race`,
CPU load; see runners.md), then find the cause with
[references/root-causes.md](references/root-causes.md). Fix the cause in the
test or the code, whichever is wrong; a test that is right about a real race
has found a product bug.

**6. Verify.** Rerun until `runs-needed --rate <the rate you measured>` clean
runs in a row, at the same parallelism and order settings that exposed it.
State the before and after numbers.

## Done when

Before you report, check each failing test has all of these; if not, go back:

- [ ] at least 3 runs on the current code (10 when narrowed)
- [ ] a run on its own, if it failed every full-suite run (step 4)
- [ ] base-commit runs, if it failed every run on the current code (step 3)
- [ ] the polluter named, if it is `order-dependent`
- [ ] for anything you fixed: before/after run counts at the same settings
- [ ] a final full-suite run, and every test still failing in it is in the report

## Report

Always end with this report, including the table, even when everything you
were asked to fix is fixed:

```markdown
## Flake or fault: <test or suite>
| Test | Verdict | Evidence |
|---|---|---|
| tests/test_cart.py::test_total | broken-by-change | 0/10 on head, 5/5 on base (merge-base abc123) |
| tests/test_api.py::test_retry  | flaky | failed 3 of 20 runs on the same commit |

Cause: <root cause, file:line> · Fix: <what changed> · Verified: <N clean runs, settings>
Left alone: <pre-existing or flaky tests outside this change, with evidence>
```

Say how many runs each verdict rests on. If a verdict rests on fewer than 3
runs, say it is provisional.
