"""Unit and integration tests for flakerun.py. Standard library only:

    python -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "flake-or-fault" / "scripts" / "flakerun.py"
sys.path.insert(0, str(SCRIPT.parent))
import flakerun as fr  # noqa: E402

PY = sys.executable


def cli(*args, cwd=None):
    return subprocess.run([PY, str(SCRIPT), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


class ParseJUnit(unittest.TestCase):
    def test_pytest_style(self):
        xml = """<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="3">
          <testcase classname="tests.test_cart" name="test_total"/>
          <testcase classname="tests.test_cart" name="test_tax"><failure message="x"/></testcase>
          <testcase classname="tests.test_cart" name="test_skip"><skipped/></testcase>
          <testcase classname="tests.test_cart" name="test_err"><error message="boom"/></testcase>
        </testsuite></testsuites>"""
        got = fr.parse_junit(xml, Path("."))
        self.assertEqual(got, {"tests.test_cart::test_total": "pass",
                               "tests.test_cart::test_tax": "fail",
                               "tests.test_cart::test_skip": "skip",
                               "tests.test_cart::test_err": "fail"})

    def test_node_test_style_uses_file_and_describe_chain(self):
        root = Path(tempfile.gettempdir()).resolve()
        f = root / "proj" / "test" / "a.test.mjs"
        xml = f"""<testsuites>
          <testcase name="adds" classname="test" file="{f}"/>
          <testsuite name="cart"><testcase name="total" classname="test" file="{f}" failure="2 == 3">
            <failure message="2 == 3"/></testcase></testsuite></testsuites>"""
        got = fr.parse_junit(xml, root / "proj")
        self.assertEqual(got, {"test/a.test.mjs::adds": "pass",
                               "test/a.test.mjs::cart > total": "fail"})

    def test_single_testsuite_root_and_namespace(self):
        xml = """<testsuite xmlns="urn:x" name="com.acme.CartTest">
          <testcase classname="com.acme.CartTest" name="total"/></testsuite>"""
        self.assertEqual(fr.parse_junit(xml, Path(".")), {"com.acme.CartTest::total": "pass"})

    def test_duplicate_ids_are_kept_apart(self):
        xml = """<testsuite><testcase classname="a" name="t"/>
                 <testcase classname="a" name="t"><failure/></testcase></testsuite>"""
        self.assertEqual(fr.parse_junit(xml, Path(".")), {"a::t": "pass", "a::t#2": "fail"})


class ParseGoJson(unittest.TestCase):
    def test_events(self):
        lines = [
            {"Action": "run", "Package": "acme/cart", "Test": "TestTotal"},
            {"Action": "pass", "Package": "acme/cart", "Test": "TestTotal"},
            {"Action": "fail", "Package": "acme/cart", "Test": "TestTax"},
            {"Action": "skip", "Package": "acme/cart", "Test": "TestSkip"},
            {"Action": "fail", "Package": "acme/cart"},  # package-level, no Test
        ]
        text = "\n".join(json.dumps(l) for l in lines) + "\nnot json\n"
        self.assertEqual(fr.parse_go_json(text), {"acme/cart::TestTotal": "pass",
                                                  "acme/cart::TestTax": "fail",
                                                  "acme/cart::TestSkip": "skip"})


def T(p=0, f=0, s=0):
    return {"pass": p, "fail": f, "skip": s}


class Verdicts(unittest.TestCase):
    def v(self, h, b=None, i=None):
        return fr.verdict(h, b, i)[0]

    def test_matrix(self):
        self.assertEqual(self.v(T(10)), "pass")
        self.assertEqual(self.v(T(s=10)), "skipped")
        self.assertEqual(self.v(T(7, 3)), "flaky")
        self.assertEqual(self.v(T(0, 10)), "consistent-failure")
        self.assertEqual(self.v(T(0, 10), T(10)), "broken-by-change")
        self.assertEqual(self.v(T(0, 10), T(0, 10)), "pre-existing")
        self.assertEqual(self.v(T(0, 10), T(0, 0)), "broken-by-change")  # new test
        self.assertEqual(self.v(T(0, 10), T(8, 2)), "inconclusive")
        self.assertEqual(self.v(T(10), T(0, 5)), "fixed-by-change")
        self.assertEqual(self.v(T(0, 10), T(10), T(5)), "order-dependent")
        self.assertEqual(self.v(T(0, 10), None, T(3, 2)), "flaky")
        self.assertEqual(self.v(T(0, 10), T(0, 10), T(0, 5)), "pre-existing")

    def test_flaky_mentions_base(self):
        self.assertIn("also failed 1/5 on base", fr.verdict(T(7, 3), T(4, 1), None)[1])


class Paths(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Git Bash paths only exist on Windows")
    def test_git_bash_paths_become_windows_paths(self):
        self.assertEqual(fr._native("/c/work/out/*.xml"), "C:/work/out/*.xml")

    def test_relative_patterns_are_untouched(self):
        self.assertEqual(fr._native(".flake/*.xml"), ".flake/*.xml")


class Maths(unittest.TestCase):
    def test_runs_needed(self):
        self.assertEqual(fr.runs_needed(0.1, 0.95), 29)
        self.assertEqual(fr.runs_needed(0.5, 0.95), 5)
        self.assertEqual(fr.runs_needed(0.01, 0.95), 299)
        with self.assertRaises(ValueError):
            fr.runs_needed(0, 0.95)

    def test_upper_bound_rule_of_three(self):
        self.assertAlmostEqual(fr.upper_bound(0, 100), 0.0295, places=3)
        self.assertEqual(fr.upper_bound(2, 10), 0.2)


# A fake test runner: writes JUnit XML for a few tests whose outcome is scripted
# by a counter file, so "flaky" behaviour is deterministic in tests.
FAKE_RUNNER = textwrap.dedent('''
    import sys, pathlib
    here = pathlib.Path(".")
    counter = here / "count.txt"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    mode = sys.argv[1]
    flaky_fail = n % 3 == 0            # fails runs 3, 6, 9 ...
    broken = mode == "head"            # passes on base, fails on head
    cases = [("stable", False), ("flaky", flaky_fail), ("changed", broken), ("old", True)]
    body = "".join(
        f'<testcase classname="suite" name="{name}">' + ("<failure/>" if bad else "") + "</testcase>"
        for name, bad in cases)
    (here / "out").mkdir(exist_ok=True)
    (here / "out" / "junit.xml").write_text(f"<testsuite>{body}</testsuite>")
    sys.exit(1 if any(bad for _, bad in cases) else 0)
''')

# A fake runner for order dependence: the victim fails if "polluter" ran before it.
ORDER_RUNNER = textwrap.dedent('''
    import sys, pathlib
    tests = sys.argv[1:]
    polluted, body = False, ""
    for t in tests:
        bad = t == "victim" and polluted
        if t == "polluter":
            polluted = True
        body += f'<testcase classname="s" name="{t}">' + ("<failure/>" if bad else "") + "</testcase>"
    pathlib.Path("r.xml").write_text(f"<testsuite>{body}</testsuite>")
    sys.exit(1 if "<failure/>" in body else 0)
''')


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "runner.py").write_text(FAKE_RUNNER)
        (self.dir / "order.py").write_text(ORDER_RUNNER)

    def run_mode(self, mode, runs, out):
        counter = self.dir / "count.txt"
        if counter.exists():
            counter.unlink()
        r = cli("run", "--cmd", f'"{PY}" runner.py {mode}', "--results", "out/*.xml",
                "--runs", str(runs), "--out", out, "--label", mode, "--cwd", str(self.dir))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(Path(out).read_text())

    def test_run_and_classify(self):
        head = self.run_mode("head", 6, str(self.dir / "head.json"))
        self.assertEqual(len(head["runs"]), 6)
        self.assertEqual(head["runs"][2]["tests"]["suite::flaky"], "fail")
        self.run_mode("base", 6, str(self.dir / "base.json"))
        r = cli("classify", "--head", str(self.dir / "head.json"),
                "--base", str(self.dir / "base.json"), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = {t["test"]: t["verdict"] for t in json.loads(r.stdout)["tests"]}
        self.assertEqual(got, {"suite::stable": "pass", "suite::flaky": "flaky",
                               "suite::changed": "broken-by-change", "suite::old": "pre-existing"})
        text = cli("classify", "--head", str(self.dir / "head.json"),
                   "--base", str(self.dir / "base.json")).stdout
        self.assertTrue(text.index("broken-by-change") < text.index("pre-existing"))

    def test_stale_results_are_cleared_between_runs(self):
        (self.dir / "out").mkdir()
        (self.dir / "out" / "stale.xml").write_text(
            '<testsuite><testcase classname="ghost" name="t"/></testsuite>')
        head = self.run_mode("head", 1, str(self.dir / "h.json"))
        self.assertNotIn("ghost::t", head["runs"][0]["tests"])

    def test_exit_code_fallback_when_no_results(self):
        r = cli("run", "--cmd", f'"{PY}" -c "import sys; sys.exit(3)"', "--results", "none/*.xml",
                "--runs", "2", "--cwd", str(self.dir))
        self.assertEqual(r.returncode, 0)
        self.assertIn("produced no test results", r.stderr)
        rec = json.loads(r.stdout)
        self.assertEqual([x["tests"] for x in rec["runs"]], [{"<command>": "fail"}] * 2)

    def test_results_directory_is_created_before_the_first_run(self):
        # Like node:test's junit reporter: writes nothing if the directory is missing.
        (self.dir / "picky.py").write_text(textwrap.dedent('''
            import os
            if os.path.isdir("deep/out"):
                open("deep/out/r.xml", "w").write('<testsuite><testcase classname="s" name="t"/></testsuite>')
        '''))
        r = cli("run", "--cmd", f'"{PY}" picky.py', "--results", "deep/out/*.xml", "--runs", "1",
                "--cwd", str(self.dir))
        self.assertEqual(json.loads(r.stdout)["runs"][0]["tests"], {"s::t": "pass"})

    def test_runs_without_results_are_left_out_of_counts(self):
        rec = {"runs": [{"tests": {"s::t": "pass"}}, {"tests": {"s::t": "fail"}},
                        {"tests": {"<command>": "fail"}, "no_results": True}]}
        self.assertEqual(fr.tally(rec), {"s::t": {"pass": 1, "fail": 1, "skip": 0}})
        self.assertEqual(fr.crashed_runs(rec), 1)
        only_exit = {"runs": [{"tests": {"<command>": "fail"}, "no_results": True}]}
        self.assertEqual(fr.tally(only_exit), {"<command>": {"pass": 0, "fail": 1, "skip": 0}})
        self.assertEqual(fr.crashed_runs(only_exit), 0)

    def test_polluter_bisection(self):
        cands = ["a", "b", "c", "polluter", "d", "e", "f"]
        (self.dir / "cands.txt").write_text("\n".join(cands) + "\n")
        r = cli("polluter", "--victim", "victim", "--candidates", str(self.dir / "cands.txt"),
                "--cmd-template", f'"{PY}" order.py {{tests}}', "--results", "r.xml",
                "--cwd", str(self.dir))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["result"], "found")
        self.assertEqual(out["polluter"], "polluter")
        self.assertLessEqual(out["steps"], 3)

    def test_polluter_not_reproduced(self):
        (self.dir / "cands.txt").write_text("a\nb\n")
        r = cli("polluter", "--victim", "victim", "--candidates", str(self.dir / "cands.txt"),
                "--cmd-template", f'"{PY}" order.py {{tests}}', "--results", "r.xml",
                "--cwd", str(self.dir))
        self.assertEqual(json.loads(r.stdout)["result"], "not-reproduced")

    def test_runs_needed_cli(self):
        r = cli("runs-needed", "--rate", "0.1")
        self.assertIn("29 consecutive clean runs", r.stdout)


if __name__ == "__main__":
    unittest.main()
