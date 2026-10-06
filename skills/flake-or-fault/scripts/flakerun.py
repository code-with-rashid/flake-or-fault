#!/usr/bin/env python3
"""Rerun tests, record per-test outcomes, and say whether a failure is flaky,
pre-existing, order-dependent, or caused by the change under test.

Standard library only; Python 3.8+. Works with any test runner that writes
JUnit XML (pytest, Jest, Vitest, node:test, Maven, Gradle, .NET, PHPUnit, RSpec,
cargo-nextest, ...) or with `go test -json` output.

    flakerun.py run       --cmd CMD --results GLOB --runs N --out FILE
    flakerun.py classify  --head FILE [--base FILE] [--isolated FILE] [--json]
    flakerun.py polluter  --victim ID --candidates FILE --cmd-template CMD --results GLOB
    flakerun.py runs-needed --rate P [--confidence C]

Run `flakerun.py <command> --help` for every option.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PASS, FAIL, SKIP = "pass", "fail", "skip"


# ---------------------------------------------------------------- parsing

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _rel(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def parse_junit(text: str, root: Path) -> dict:
    """Map test id -> outcome for one JUnit XML document."""
    out: dict = {}
    tree = ET.fromstring(text)

    def walk(node, suites):
        for child in node:
            tag = _local(child.tag)
            if tag == "testsuite":
                walk(child, suites + [child.get("name", "")])
            elif tag == "testsuites":
                walk(child, suites)
            elif tag == "testcase":
                name = child.get("name", "")
                file_attr = child.get("file")
                if file_attr:
                    chain = [s for s in suites if s] + [name]
                    tid = f"{_rel(file_attr, root)}::{' > '.join(chain)}"
                else:
                    cls = child.get("classname", "")
                    tid = f"{cls}::{name}" if cls else name
                kinds = {_local(c.tag) for c in child}
                if child.get("failure") is not None or kinds & {"failure", "error"}:
                    outcome = FAIL
                elif kinds & {"skipped"}:
                    outcome = SKIP
                else:
                    outcome = PASS
                _put(out, tid, outcome)

    walk([tree], [])
    return out


def parse_go_json(text: str) -> dict:
    """Map test id -> outcome from `go test -json` output."""
    out: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        action, test = ev.get("Action"), ev.get("Test")
        if not test or action not in ("pass", "fail", "skip"):
            continue
        tid = f"{ev.get('Package', '')}::{test}"
        out[tid] = {"pass": PASS, "fail": FAIL, "skip": SKIP}[action]
    return out


def _put(out: dict, tid: str, outcome: str) -> None:
    if tid not in out:
        out[tid] = outcome
        return
    n = 2
    while f"{tid}#{n}" in out:
        n += 1
    out[f"{tid}#{n}"] = outcome


def _native(pattern: str) -> str:
    """On Windows, turn a Git Bash/MSYS path (/c/Users/...) into C:/Users/..."""
    if os.name == "nt" and len(pattern) > 2 and pattern[0] == "/" and pattern[2] == "/"             and pattern[1].isalpha():
        return f"{pattern[1].upper()}:{pattern[2:]}"
    return pattern


def collect(patterns, cwd: Path, stdout: str, fmt: str, since: float = 0.0) -> dict:
    """Parse results written at or after `since` (wall clock), so a report left
    over from an earlier run is never counted and nothing has to be deleted."""
    tests: dict = {}
    if fmt == "go-json":
        return parse_go_json(stdout)
    for pattern in patterns:
        for f in sorted(glob.glob(str(cwd / _native(pattern)), recursive=True)):
            if not os.path.isfile(f) or os.path.getmtime(f) < since:
                continue
            text = Path(f).read_text(encoding="utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                for tid, outcome in parse_junit(text, cwd).items():
                    _put(tests, tid, outcome)
            except ET.ParseError as e:
                print(f"warning: could not parse {f}: {e}", file=sys.stderr)
    return tests


def _prepare(patterns, cwd: Path) -> None:
    """Create the literal directory part of each results glob: some reporters
    (node:test, for one) silently write nothing if the directory is missing."""
    for pattern in patterns:
        parts = []
        for part in Path(_native(pattern)).parent.parts:
            if any(c in part for c in "*?["):
                break
            parts.append(part)
        if parts:
            (cwd.joinpath(*parts)).mkdir(parents=True, exist_ok=True)


def _git(cwd: Path, *args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def execute(cmd: str, cwd: Path, patterns, fmt: str, timeout, env) -> dict:
    since = time.time()
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
        code, stdout, tail = proc.returncode, proc.stdout, (proc.stdout + proc.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        code, stdout, tail = None, "", f"timed out after {timeout}s"
    seconds = round(time.monotonic() - start, 2)
    tests = collect(patterns, cwd, stdout, fmt, since)
    return {"exit": code, "seconds": seconds, "tests": tests, "tail": tail}


# ---------------------------------------------------------------- run

def cmd_run(a) -> int:
    cwd = Path(a.cwd).resolve()
    if not a.results and a.format != "go-json":
        sys.exit("error: give --results GLOB for JUnit XML, or --format go-json")
    env = dict(os.environ)
    for kv in a.env or []:
        k, _, v = kv.partition("=")
        env[k] = v
    record = {
        "label": a.label, "cmd": a.cmd, "cwd": str(cwd),
        "commit": _git(cwd, "rev-parse", "HEAD"),
        "dirty": bool(_git(cwd, "status", "--porcelain")),
        "runs": [],
    }
    if a.out and a.append and Path(a.out).exists():
        prev = json.loads(Path(a.out).read_text(encoding="utf-8"))
        record["runs"] = prev.get("runs", [])
    _prepare(a.results or [], cwd)
    for i in range(1, a.runs + 1):
        r = execute(a.cmd, cwd, a.results or [], a.format, a.timeout, env)
        if not r["tests"]:
            r["tests"] = {"<command>": PASS if r["exit"] == 0 else FAIL}
            r["no_results"] = True
            print(f"warning: run {i} produced no test results; recording its exit code "
                  "instead. If every run says this, check --results points at the "
                  "JUnit file the command writes; if only some do, those runs crashed "
                  "or timed out, which is evidence too.", file=sys.stderr)
        tail = r.pop("tail")
        if a.keep_output:
            r["tail"] = tail
        record["runs"].append(r)
        fails = sum(1 for o in r["tests"].values() if o == FAIL)
        print(f"run {i}/{a.runs}: exit={r['exit']} tests={len(r['tests'])} "
              f"failed={fails} ({r['seconds']}s)", file=sys.stderr)
        if a.out:  # write as we go so an interrupted session keeps its evidence
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(json.dumps(record, indent=1), encoding="utf-8")
    if all(r.get("no_results") for r in record["runs"]):
        hint = ("note: no run wrote results matching --results.")
        if os.name == "nt":
            hint += (" On Windows the command runs under cmd.exe: use Windows paths "
                     "(C:/...) for programs in --cmd, not Git Bash paths (/c/...).")
        print(hint, file=sys.stderr)
    if not a.out:
        print(json.dumps(record, indent=1))
    return 0


# ---------------------------------------------------------------- classify

def tally(record) -> dict:
    """Per-test outcome counts. Runs that produced no per-test results are left
    out when other runs did produce them (they are counted by `crashed_runs`)."""
    t: dict = {}
    runs = (record or {}).get("runs", [])
    if any(not r.get("no_results") for r in runs):
        runs = [r for r in runs if not r.get("no_results")]
    for run in runs:
        for tid, outcome in run["tests"].items():
            t.setdefault(tid, {PASS: 0, FAIL: 0, SKIP: 0})[outcome] += 1
    return t


def upper_bound(fails: int, n: int, conf: float = 0.95) -> float:
    """One-sided upper confidence bound on the failure rate when fails == 0."""
    if n == 0:
        return 1.0
    if fails == 0:
        return 1 - (1 - conf) ** (1 / n)
    return fails / n


def verdict(h, b, iso) -> tuple:
    """Return (verdict, explanation) for one test's tallies."""
    hp, hf = h[PASS], h[FAIL]
    if hp + hf == 0:
        return "skipped", "never ran (skipped in every run)"
    if hf == 0:
        if b and b[FAIL] and not b[PASS]:
            return "fixed-by-change", "fails on base, passes on head"
        return "pass", f"passed {hp}/{hp}"
    if hp and hf:
        note = f"failed {hf} of {hp + hf} runs on the same code"
        if b and b[FAIL]:
            note += f"; also failed {b[FAIL]}/{b[PASS] + b[FAIL]} on base"
        return "flaky", note
    # failed every head run from here on
    if iso and (iso[PASS] or iso[FAIL]):
        if iso[PASS] and not iso[FAIL]:
            return "order-dependent", (f"fails in every full run ({hf}/{hf}) but passes "
                                       f"alone ({iso[PASS]}/{iso[PASS]}): another test "
                                       "leaks state into it")
        if iso[PASS] and iso[FAIL]:
            return "flaky", f"fails every full run, {iso[FAIL]}/{iso[PASS] + iso[FAIL]} alone"
    if b is None:
        return "consistent-failure", (f"failed {hf}/{hf}; rerun on the base commit "
                                      "(--base) to attribute it")
    if b[PASS] + b[FAIL] == 0:
        return "broken-by-change", "only exists on head (new or renamed test) and fails"
    if b[FAIL] and not b[PASS]:
        return "pre-existing", f"fails on base too ({b[FAIL]}/{b[FAIL]})"
    if b[PASS] and not b[FAIL]:
        return "broken-by-change", f"failed {hf}/{hf} on head, passed {b[PASS]}/{b[PASS]} on base"
    return "inconclusive", (f"always fails on head but is flaky on base "
                            f"({b[FAIL]}/{b[PASS] + b[FAIL]}); add runs to both")


ORDER = ["broken-by-change", "order-dependent", "consistent-failure", "flaky",
         "inconclusive", "pre-existing", "fixed-by-change", "skipped", "pass"]


def crashed_runs(record) -> int:
    runs = (record or {}).get("runs", [])
    if all(r.get("no_results") for r in runs):
        return 0
    return sum(1 for r in runs if r.get("no_results"))


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def cmd_classify(a) -> int:
    head, base, iso = _load(a.head), _load(a.base), _load(a.isolated)
    th, tb, ti = tally(head), tally(base) if base else None, tally(iso) if iso else None
    rows = []
    for tid, h in th.items():
        b = (tb.get(tid, {PASS: 0, FAIL: 0, SKIP: 0}) if tb is not None else None)
        i = ti.get(tid) if ti is not None else None
        if i is None and ti is not None and len(ti) == 1 and "<command>" in ti:
            i = ti["<command>"]  # isolated run of a single test without per-test results
        v, why = verdict(h, b, i)
        n = h[PASS] + h[FAIL]
        rows.append({"test": tid, "verdict": v, "why": why,
                     "head": {"pass": h[PASS], "fail": h[FAIL], "skip": h[SKIP]},
                     "base": None if b is None else {"pass": b[PASS], "fail": b[FAIL]},
                     "isolated": None if i is None else {"pass": i[PASS], "fail": i[FAIL]},
                     "fail_rate": round(h[FAIL] / n, 3) if n else None,
                     "fail_rate_upper_95": round(upper_bound(h[FAIL], n), 3) if n else None})
    rows.sort(key=lambda r: (ORDER.index(r["verdict"]), r["test"]))
    runs = len(head.get("runs", []))
    summary = {}
    for r in rows:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
    result = {"head_runs": runs, "base_runs": len(base["runs"]) if base else 0,
              "isolated_runs": len(iso["runs"]) if iso else 0,
              "head_commit": head.get("commit"), "base_commit": (base or {}).get("commit"),
              "runs_without_results": {"head": crashed_runs(head), "base": crashed_runs(base),
                                       "isolated": crashed_runs(iso)},
              "summary": summary, "tests": rows}
    if a.json:
        print(json.dumps(result, indent=1))
        return 0
    print(f"head runs: {runs}" + (f" | base runs: {result['base_runs']}" if base else "")
          + (f" | isolated runs: {result['isolated_runs']}" if iso else ""))
    if runs < 3:
        print("note: fewer than 3 head runs - too few to call anything flaky or stable")
    for side, n in result["runs_without_results"].items():
        if n:
            print(f"note: {n} {side} run(s) wrote no test results (crash, timeout, or "
                  "reporter failure) and are left out of the counts; rerun with "
                  "--keep-output to see why")
    shown = [r for r in rows if a.all or r["verdict"] not in ("pass", "skipped")]
    for r in shown:
        print(f"{r['verdict']:<19} {r['test']}\n{'':<19} {r['why']}")
    passing = summary.get("pass", 0)
    if passing:
        worst = max((r["fail_rate_upper_95"] for r in rows if r["verdict"] == "pass"), default=0)
        print(f"{passing} test(s) passed every run (each could still fail up to "
              f"{worst:.0%} of the time at 95% confidence with only {runs} runs)")
    print("summary: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return 0


# ---------------------------------------------------------------- polluter

def _quote(s: str) -> str:
    if os.name == "nt":
        return f'"{s}"' if any(c in s for c in ' &|<>^"') else s
    import shlex
    return shlex.quote(s)


def cmd_polluter(a) -> int:
    cwd = Path(a.cwd).resolve()
    cands = [l.strip() for l in Path(a.candidates).read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    victim_sel = a.victim_selector or a.victim
    cands = [c for c in cands if c != victim_sel]
    env = dict(os.environ)

    def victim_fails(subset) -> bool:
        tests = " ".join(_quote(s) for s in list(subset) + [victim_sel])
        for _ in range(a.repeat):
            r = execute(a.cmd_template.replace("{tests}", tests), cwd, a.results or [],
                        a.format, a.timeout, env)
            hits = [o for tid, o in r["tests"].items() if a.victim in tid]
            if not hits:
                failed = r["exit"] != 0
            else:
                failed = FAIL in hits
            if failed:
                return True
        return False

    print(f"{len(cands)} candidate(s) before the victim", file=sys.stderr)
    if victim_fails([]):
        print(json.dumps({"result": "victim-fails-alone",
                          "detail": "the victim fails even when run alone, so it is not "
                                    "order-dependent - or the selector is wrong. --victim "
                                    "matches result ids (e.g. tests.test_x::test_y); the "
                                    "command line may need another form, given with "
                                    "--victim-selector (e.g. tests/test_x.py::test_y)."},
                         indent=1))
        return 1
    if not victim_fails(cands):
        print(json.dumps({"result": "not-reproduced",
                          "detail": "victim passed after all candidates; check the order, "
                                    "or raise --repeat if the pollution is itself flaky"},
                         indent=1))
        return 1
    steps, current = 0, cands
    while len(current) > 1:
        half = len(current) // 2
        first, second = current[:half], current[half:]
        steps += 1
        print(f"step {steps}: {len(current)} suspects", file=sys.stderr)
        if victim_fails(first):
            current = first
        elif victim_fails(second):
            current = second
        else:
            print(json.dumps({"result": "needs-combination", "suspects": current,
                              "steps": steps,
                              "detail": "neither half alone pollutes the victim; the "
                                        "pollution needs tests from both halves"}, indent=1))
            return 0
    print(json.dumps({"result": "found", "polluter": current[0], "victim": victim_sel,
                      "steps": steps,
                      "reproduce": a.cmd_template.replace(
                          "{tests}", f"{_quote(current[0])} {_quote(victim_sel)}")}, indent=1))
    return 0


# ---------------------------------------------------------------- runs-needed

def runs_needed(rate: float, confidence: float) -> int:
    if not 0 < rate < 1 or not 0 < confidence < 1:
        raise ValueError("rate and confidence must be between 0 and 1")
    return math.ceil(math.log(1 - confidence) / math.log(1 - rate))


def cmd_runs_needed(a) -> int:
    n = runs_needed(a.rate, a.confidence)
    print(f"{n} consecutive clean runs show the failure rate is now below {a.rate:.1%} "
          f"with {a.confidence:.0%} confidence")
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--results", action="append",
                        help="glob (relative to --cwd, or absolute) of JUnit XML files the "
                             "command writes; repeatable. Only files written during a run "
                             "are read; nothing is deleted.")
        sp.add_argument("--format", choices=["junit", "go-json"], default="junit",
                        help="go-json parses `go test -json` from stdout instead of files")
        sp.add_argument("--cwd", default=".", help="directory to run in (e.g. a git worktree)")
        sp.add_argument("--timeout", type=float, default=None, help="seconds per run")

    r = sub.add_parser("run", help="run a test command N times and record per-test outcomes")
    r.add_argument("--cmd", required=True, help="shell command that runs the tests")
    r.add_argument("--runs", type=int, default=10)
    r.add_argument("--out", help="JSON file to write (stdout if omitted)")
    r.add_argument("--append", action="store_true", help="add runs to an existing --out file")
    r.add_argument("--label", default="head")
    r.add_argument("--env", action="append", metavar="K=V", help="extra environment variable")
    r.add_argument("--keep-output", action="store_true", help="store each run's output tail")
    common(r)
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("classify", help="compare recorded runs and give each test a verdict")
    c.add_argument("--head", required=True, help="runs on the code under test")
    c.add_argument("--base", help="runs on the base commit (e.g. merge-base with main)")
    c.add_argument("--isolated", help="runs of the failing test(s) on their own")
    c.add_argument("--json", action="store_true")
    c.add_argument("--all", action="store_true", help="also list passing tests")
    c.set_defaults(fn=cmd_classify)

    q = sub.add_parser("polluter", help="bisect which earlier test pollutes an order-dependent victim")
    q.add_argument("--victim", required=True, help="substring that identifies the victim's result id")
    q.add_argument("--victim-selector", help="how to name the victim on the command line "
                                             "(defaults to --victim)")
    q.add_argument("--candidates", required=True,
                   help="file listing test selectors that run before the victim, in order")
    q.add_argument("--cmd-template", required=True,
                   help="command with {tests} where the selectors go, run in the given order")
    q.add_argument("--repeat", type=int, default=1, help="tries per probe (for flaky pollution)")
    common(q)
    q.set_defaults(fn=cmd_polluter)

    n = sub.add_parser("runs-needed", help="clean runs needed to claim a flake is fixed")
    n.add_argument("--rate", type=float, required=True, help="observed failure rate, e.g. 0.1")
    n.add_argument("--confidence", type=float, default=0.95)
    n.set_defaults(fn=cmd_runs_needed)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    raise SystemExit(main())
