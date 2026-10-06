# flake-or-fault

> A portable [Agent Skill](https://agentskills.io) that makes a coding agent prove why a test is failing before it changes anything: broken by the current change, already broken on main, flaky, or order-dependent. Then it fixes the real cause instead of adding retries, sleeps, or skips. Works in Claude Code, Codex CLI, Cursor, Gemini CLI, GitHub Copilot, and any other Agent-Skills-compatible tool.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Part of the [Agent Skills catalog](https://github.com/code-with-rashid/agent-skills).

## The problem

Coding agents treat every red test as ground truth. When the test is flaky, the
agent "fixes" code that was fine, reverts a correct change, or burns its budget
until a lucky green run convinces it that its edit was the cure. When a test was
already broken on main, the agent drags an unrelated fix into your change. When a
test only fails after another test leaks state into it, the agent fiddles with the
victim. The usual escape hatches (a retry, a longer sleep, `skip`) hide the
problem instead of fixing it.

## What this does

- **Reruns instead of guessing.** A bundled, dependency-free script runs the test
  command many times, reads the JUnit XML it writes (or `go test -json`), and keeps
  per-test pass/fail counts.
- **Attributes every failure.** It compares your code with the base commit in a
  separate git worktree (your working tree is never touched) and with the test run
  on its own, and gives each test a verdict:

  | Verdict | Meaning |
  |---|---|
  | `broken-by-change` | fails every run on your code, passes on base: your bug |
  | `pre-existing` | fails on base too: not yours, reported, not silently "fixed" |
  | `flaky` | passes and fails on the same code |
  | `order-dependent` | fails in the suite, passes alone: another test leaks state |

- **Finds the polluter.** For order-dependent tests it bisects the tests that run
  before the victim and prints a two-test command that reproduces the failure.
- **Fixes the cause.** A root-cause catalogue (shared state, waiting on time, real
  races, clocks, randomness, network, parallel resources, leaks, CI-only
  differences) maps each symptom to the fix that holds and the tempting non-fix.
- **Verifies with numbers.** "Fixed" means enough consecutive clean runs for the
  failure rate that was measured (`runs-needed --rate 0.3` says 9), not one green run.

## Quick demo

```text
$ python flakerun.py run --cmd "python -m pytest -q --junitxml=.flake/junit.xml" --results ".flake/junit.xml" --runs 10 --out .flake/head.json
$ python flakerun.py run --cwd ../base-worktree ... --runs 5 --out .flake/base.json
$ python flakerun.py run --cmd "python -m pytest tests/test_b_label.py --junitxml=.flake/iso.xml" --results ".flake/iso.xml" --runs 5 --out .flake/iso.json
$ python flakerun.py classify --head .flake/head.json --base .flake/base.json --isolated .flake/iso.json
head runs: 10 | base runs: 5 | isolated runs: 5
broken-by-change    tests.test_cart::test_total_with_discount
                    failed 10/10 on head, passed 5/5 on base
order-dependent     tests.test_b_label::test_price_label
                    fails in every full run (10/10) but passes alone (5/5): another test leaks state into it
flaky               tests.test_ids::test_order_ids_are_unique
                    failed 3 of 10 runs on the same code
pre-existing        tests.test_tax::test_tax_rounding
                    fails on base too (5/5)
```

You don't type these yourself: ask your agent "the suite is red after my change,
get it green" or "this test fails randomly in CI, fix it" and the skill drives it.

## Install

### Claude Code

```
/plugin marketplace add code-with-rashid/agent-skills
/plugin install flake-or-fault@codewithrashid-skills
```

Then `/reload-plugins` (or start a new session). Typing `/flake-or-fault` always
invokes it directly.

### Codex CLI, Cursor, Gemini CLI, GitHub Copilot, and other tools

Copy the `skills/flake-or-fault` folder (not the whole repo) into a skills
directory your tool reads. `~/.agents/skills/` is read by Codex CLI, Cursor,
Gemini CLI, and GitHub Copilot:

```bash
git clone https://github.com/code-with-rashid/flake-or-fault /tmp/flake-or-fault
mkdir -p ~/.agents/skills
cp -r /tmp/flake-or-fault/skills/flake-or-fault ~/.agents/skills/
```

| Tool | Personal | Project |
|---|---|---|
| Codex CLI | `~/.agents/skills/` | `.agents/skills/` |
| Cursor | `~/.cursor/skills/` or `~/.agents/skills/` | `.cursor/skills/` or `.agents/skills/` |
| Gemini CLI | `~/.gemini/skills/` or `~/.agents/skills/` | `.gemini/skills/` or `.agents/skills/` |
| GitHub Copilot | `~/.copilot/skills/` or `~/.agents/skills/` | `.github/skills/` or `.agents/skills/` |
| Claude Code (manual) | `~/.claude/skills/` | `.claude/skills/` |

Gemini CLI can also install it directly:
`gemini skills install https://github.com/code-with-rashid/flake-or-fault.git --path skills/flake-or-fault`.

Requirements: Python 3.8+ and git. Nothing to `pip install`.

## Usage examples

- "I switched the discount to per-item and now the suite is red. Get it green."
- "`test_order_ids_are_unique` fails randomly in CI. Fix it properly."
- "This test passes on its own but fails in the full suite. Why?"
- "Is this CI failure from my PR or was main already broken?"
- "Find and deflake the flaky tests in this repo."

Supported runners (via JUnit XML): pytest, Vitest, Jest (with `jest-junit`),
node:test, Playwright, Maven, Gradle, .NET (with `JunitXml.TestLogger`),
cargo-nextest, RSpec, PHPUnit; Go via `go test -json`. Anything else works at
exit-code granularity. See [references/runners.md](skills/flake-or-fault/references/runners.md).

## Limitations

- Reruns cost time. The skill narrows to the failing tests first, but a slow
  suite still limits how many runs are practical, and a rare flake (1 in 200)
  needs many runs to see or to rule out. Verdicts state how many runs they rest on.
- Attribution needs the base commit to build and run in a worktree; projects that
  keep dependencies in the tree (`node_modules`) need an install there.
- Order bisection needs a runner that runs tests in the order given (pytest does;
  for others, see runners.md). It finds single polluters; it reports when pollution
  needs several tests together.
- It works best with frontier-tier models. In evals, smaller models (Claude Haiku)
  sometimes skipped steps or loosened an assertion despite the rules; see
  [evals/RESULTS.md](evals/RESULTS.md).
- It cannot see CI-only causes it cannot reproduce locally; it lists the
  environment differences to check instead.

## Evals and tests

- `python -m unittest discover -s tests` runs the script's unit and integration
  tests (stdlib only).
- [`evals/`](evals/) holds two reproducible scenarios (`make_shop.py`,
  `make_queue.py`), the eval prompts and expectations (`evals.json`), and the
  latest results ([`evals/RESULTS.md`](evals/RESULTS.md)).

## Contributing

Issues and pull requests are welcome, especially runner recipes you have verified
and root causes the catalogue misses. Please run the tests before opening a PR, and
keep `scripts/` standard-library only.

## License

[MIT](LICENSE)
