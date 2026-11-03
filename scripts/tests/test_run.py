"""Tests for scripts/tests/run.py, the parallel shard runner, driven against small synthetic test directories."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent / "run.py"

PASSING = """
import unittest

class {name}(unittest.TestCase):
    def test_one(self):
        pass

    def test_two(self):
        pass
"""


class Runner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.top = Path(self._tmp.name)
        (self.top / "synth").mkdir()
        (self.top / "synth" / "__init__.py").write_text("")

    def tearDown(self):
        self._tmp.cleanup()

    def module(self, name: str, source: str):
        (self.top / "synth" / f"{name}.py").write_text(textwrap.dedent(source))

    def classes(self, count: int, module: str = "test_many"):
        self.module(module, "".join(PASSING.format(name=f"Case{i}") for i in range(count)))

    def run_runner(self, *args, env=None):
        environ = {k: v for k, v in os.environ.items() if k != "SDLC_TEST_JOBS"}
        return subprocess.run(
            [sys.executable, str(RUN_PY), "--top", str(self.top), "--start", "synth", *args],
            cwd=self.top,
            env={**environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=120,
        )

    def summary(self, proc) -> str:
        return proc.stdout.strip().splitlines()[-1]

    def shard_lines(self, proc) -> list[str]:
        return re.findall(r"(?m)^shard \d+: .*$", proc.stdout)

    def test_all_passing(self):
        self.classes(5)
        proc = self.run_runner("--jobs", "3")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertRegex(self.summary(proc), r"^OK: ran 10 tests in 5 shards")

    def test_failing_test_fails_the_run_and_prints_its_shard(self):
        self.classes(3)
        self.module("test_bad", """
            import unittest

            class Bad(unittest.TestCase):
                def test_wrong(self):
                    self.assertEqual(1, 2)
            """)
        proc = self.run_runner("--jobs", "2")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL: test_wrong (synth.test_bad.Bad.test_wrong)", proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*failures=1")

    def test_erroring_test_fails_the_run(self):
        self.module("test_err", """
            import unittest

            class Err(unittest.TestCase):
                def test_raises(self):
                    raise RuntimeError("boom")
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("RuntimeError: boom", proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*errors=1")

    def test_import_failure_fails_the_run(self):
        self.classes(2)
        self.module("test_broken", "import no_such_module_anywhere\n")
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("synth.test_broken", proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: discovery")

    def test_shard_that_exits_early_fails_the_run(self):
        self.classes(2)
        self.module("test_exit", """
            import os
            import unittest

            class Exits(unittest.TestCase):
                def test_exit(self):
                    os._exit(0)
            """)
        proc = self.run_runner("--jobs", "3")
        self.assertEqual(proc.returncode, 1)
        self.assertRegex(self.summary(proc), r"^FAILED: .*no result")

    def test_shards_run_exactly_the_discovered_tests(self):
        """A module's load_tests selects one failing method; reloading the whole class would run a passing one instead."""
        self.module("test_selected", """
            import unittest

            class Case(unittest.TestCase):
                def check_fail(self):
                    self.fail("the discovered test ran")

                def test_ok(self):
                    pass

            def load_tests(loader, tests, pattern):
                return unittest.TestSuite([Case("check_fail")])
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("the discovered test ran", proc.stdout)

    def test_a_printed_summary_does_not_change_the_verdict(self):
        self.module("test_fake", """
            import sys
            import unittest

            class Fake(unittest.TestCase):
                def test_prints_a_summary(self):
                    sys.stderr.write("Ran 5 tests in 0.001s\\n\\nFAILED (failures=5)\\n")
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertRegex(self.summary(proc), r"^OK: ran 1 tests")

    def test_a_printed_summary_cannot_stand_in_for_a_result(self):
        self.module("test_fake", """
            import os
            import sys
            import unittest

            class Fake(unittest.TestCase):
                def test_prints_a_summary_and_exits(self):
                    sys.stderr.write("Ran 1 test in 0.001s\\n\\nOK\\n")
                    sys.stderr.flush()
                    os._exit(0)
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*no result")

    def test_test_stdout_does_not_disturb_the_summary(self):
        self.module("test_noisy", """
            import unittest

            class Noisy(unittest.TestCase):
                def test_prints(self):
                    print("Ran 9 tests in 0.1s")
                    print("FAILED (failures=3)")
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertRegex(self.summary(proc), r"^OK: ran 1 tests")

    def test_output_after_the_summary_is_allowed(self):
        """Warnings printed at interpreter shutdown follow the summary; the shard still passes on its result."""
        self.module("test_atexit", """
            import atexit
            import sys
            import unittest

            atexit.register(lambda: sys.stderr.write("ResourceWarning: printed at shutdown\\n"))

            class Late(unittest.TestCase):
                def test_ok(self):
                    pass
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertRegex(self.summary(proc), r"^OK: ran 1 tests")

    # -- the gate must not pass when test code ends a process early -------------

    FAILING = """
        import unittest

        class Fails(unittest.TestCase):
            def test_fails(self):
                self.fail("must be reported")
        """

    def test_load_tests_system_exit_fails_discovery(self):
        self.module("test_fails", self.FAILING)
        self.module("test_quits", """
            def load_tests(loader, tests, pattern):
                raise SystemExit(0)
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: discovery did not complete")

    def test_os_exit_at_import_fails_discovery(self):
        self.module("test_fails", self.FAILING)
        self.module("test_quits", "import os\nos._exit(0)\n")
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: discovery did not complete")

    def test_sys_exit_at_import_is_a_discovery_error(self):
        self.module("test_fails", self.FAILING)
        self.module("test_quits", "import sys\nsys.exit(0)\n")
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: discovery")

    def test_system_exit_in_the_last_teardown_leaves_no_result(self):
        self.module("test_teardown", """
            import sys
            import unittest

            class Quits(unittest.TestCase):
                @classmethod
                def tearDownClass(cls):
                    sys.exit(0)

                def test_a(self):
                    pass

                def test_b(self):
                    pass
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*no result")

    def test_system_exit_inside_a_test_is_an_error(self):
        self.module("test_inside", """
            import sys
            import unittest

            class Inside(unittest.TestCase):
                def test_exits(self):
                    sys.exit(0)
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*errors=1")

    def test_a_test_that_never_finishes_fails(self):
        self.module("test_unfinished", """
            import unittest

            class Unfinished(unittest.TestCase):
                def run(self, result=None):
                    result.startTest(self)

                def test_a(self):
                    pass
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*test did not finish")

    # -- fixtures and outcomes ------------------------------------------------------

    def test_set_up_class_skip_counts_the_class_as_skipped(self):
        self.classes(1)
        self.module("test_fixture", """
            import unittest

            class NoTool(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    raise unittest.SkipTest("tool missing")

                def test_a(self):
                    pass

                def test_b(self):
                    pass
            """)
        proc = self.run_runner("--jobs", "2")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertRegex(self.summary(proc), r"^OK: ran 4 tests .*skipped=2")

    def test_set_up_module_skip_covers_only_that_module(self):
        self.module("test_skipmod", """
            import unittest

            def setUpModule():
                raise unittest.SkipTest("module unavailable")

            class One(unittest.TestCase):
                def test_a(self):
                    pass

            class Two(unittest.TestCase):
                def test_b(self):
                    pass
            """)
        self.module("test_sibling", """
            import unittest

            class Sibling(unittest.TestCase):
                def test_runs(self):
                    self.fail("the sibling module ran")
            """)
        proc = self.run_runner("--jobs", "1")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("the sibling module ran", proc.stdout)
        (self.top / "synth" / "test_sibling.py").unlink()
        self.module("test_skipmod_extra", PASSING.format(name="Extra"))  # a module whose name extends the skipped one
        for jobs in ("1", "2"):  # one shard with every class; one shard per class
            with self.subTest(jobs=jobs):
                proc = self.run_runner("--jobs", jobs)
                self.assertEqual(proc.returncode, 0, proc.stdout)
                self.assertRegex(self.summary(proc), r"^OK: ran 4 tests .*skipped=2\)")

    def test_a_failing_shard_still_counts_its_fixture_skips(self):
        self.module("test_mixed", """
            import unittest

            class NoTool(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    raise unittest.SkipTest("tool missing")

                def test_a(self):
                    pass

                def test_b(self):
                    pass

            class Fails(unittest.TestCase):
                def test_fails(self):
                    self.fail("must be reported")
            """)
        proc = self.run_runner("--jobs", "1")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: ran 3 tests in 1 shard \(failures=1, errors=0, skipped=2\)")

    def test_set_up_class_error_fails(self):
        self.module("test_setup_error", """
            import unittest

            class Broken(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    raise RuntimeError("setup broke")

                def test_a(self):
                    pass
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("setup broke", proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*failed")

    def test_tear_down_class_skip_fails(self):
        self.module("test_teardown_skip", """
            import unittest

            class LateSkip(unittest.TestCase):
                @classmethod
                def tearDownClass(cls):
                    raise unittest.SkipTest("too late")

                def test_a(self):
                    pass
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*unexpected fixture skip")

    def test_subtest_and_expected_outcomes(self):
        cases = {
            "failing subTest": ("""
                def test_sub(self):
                    for i in range(2):
                        with self.subTest(i=i):
                            self.assertEqual(i, 0)
                """, 1),
            "expected failure that fails": ("""
                @unittest.expectedFailure
                def test_xfail(self):
                    self.fail("known")
                """, 0),
            "unexpected success": ("""
                @unittest.expectedFailure
                def test_xpass(self):
                    pass
                """, 1),
        }
        for name, (body, code) in cases.items():
            with self.subTest(name):
                source = "import unittest\n\nclass Outcome(unittest.TestCase):\n" + textwrap.indent(textwrap.dedent(body), "    ")
                (self.top / "synth" / "test_outcome.py").write_text(source)
                proc = self.run_runner()
                self.assertEqual(proc.returncode, code, proc.stdout)

    def test_duplicate_test_ids_are_refused(self):
        self.module("test_dup", """
            import unittest

            class Case(unittest.TestCase):
                def test_a(self):
                    pass

            def load_tests(loader, tests, pattern):
                return unittest.TestSuite([Case("test_a"), Case("test_a")])
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*duplicate test id")

    def test_killed_shard_fails_the_run(self):
        self.module("test_kill", """
            import os
            import signal
            import unittest

            class Killed(unittest.TestCase):
                def test_kill(self):
                    os.kill(os.getpid(), signal.SIGKILL)
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1)
        self.assertRegex(self.summary(proc), r"^FAILED: .*crashed")

    def test_skips_are_counted_and_pass(self):
        self.module("test_skip", """
            import unittest

            class Skips(unittest.TestCase):
                def test_runs(self):
                    pass

                @unittest.skip("not here")
                def test_skipped(self):
                    pass

            @unittest.skip("whole class")
            class SkippedClass(unittest.TestCase):
                def test_a(self):
                    pass
            """)
        proc = self.run_runner("--jobs", "2")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertRegex(self.summary(proc), r"^OK: ran 3 tests .*skipped=2")

    def test_each_class_runs_alone_heaviest_first(self):
        sizes = {"Alpha": 1, "Bravo": 3, "Charlie": 2, "Delta": 2, "Echo": 1}
        source = "import unittest\n"
        for name, size in sizes.items():
            source += f"\nclass {name}(unittest.TestCase):\n" + "".join(f"    def test_{i}(self):\n        pass\n" for i in range(size))
        self.module("test_sizes", source)
        first, second = self.run_runner("--jobs", "2"), self.run_runner("--jobs", "2")
        self.assertEqual(first.returncode, 0, first.stdout)
        lines = self.shard_lines(first)
        shards = [(int(re.search(r": (\d+) tests", line).group(1)), re.findall(r"synth\.test_sizes\.(\w+)", line)) for line in lines]
        self.assertEqual(shards, [(3, ["Bravo"]), (2, ["Charlie"]), (2, ["Delta"]), (1, ["Alpha"]), (1, ["Echo"])])
        self.assertEqual([re.sub(r" in [0-9.]+s", "", line) for line in lines], [re.sub(r" in [0-9.]+s", "", line) for line in self.shard_lines(second)])

    def test_jobs_one_runs_one_process(self):
        self.classes(4)
        proc = self.run_runner("--jobs", "1")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(len(self.shard_lines(proc)), 1)
        self.assertRegex(self.summary(proc), r"^OK: ran 8 tests in 1 shard\b")

    def test_jobs_sets_the_exact_concurrency(self):
        """Each class waits until J classes have started (and briefly for a J+1th), then records how many are running.

        The peak must be exactly J: a smaller pool never reaches J and times out; a larger one overlaps J+1.
        """
        marks = self.top / "marks"
        marks.mkdir()
        body = """
            import os
            import time
            import unittest
            from pathlib import Path

            MARKS = Path(os.environ["SYNTH_MARKS"])

            class Case{i}(unittest.TestCase):
                def test_overlap(self):
                    want = int(os.environ["SYNTH_JOBS"])
                    (MARKS / "start-{i}").touch()
                    started = lambda: len(list(MARKS.glob("start-*")))
                    deadline = time.monotonic() + 10  # J classes must overlap: a smaller pool stalls here
                    while started() < want and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if started() < want:
                        (MARKS / "timeout-{i}").touch()
                    extra = time.monotonic() + 1.5  # a larger pool would start class J+1 meanwhile
                    while started() < want + 1 and time.monotonic() < extra:
                        time.sleep(0.01)
                    running = started() - len(list(MARKS.glob("end-*")))
                    (MARKS / "peak-{i}").write_text(str(running))
                    (MARKS / "end-{i}").touch()
            """
        for i in range(6):
            self.module(f"test_overlap{i}", body.replace("{i}", str(i)))
        for args, env, jobs in (((), {"SDLC_TEST_JOBS": "2"}, 2), (("--jobs", "4"), {"SDLC_TEST_JOBS": "2"}, 4)):
            with self.subTest(jobs=jobs):
                for mark in marks.iterdir():
                    mark.unlink()
                proc = self.run_runner(*args, env={**env, "SYNTH_MARKS": str(marks), "SYNTH_JOBS": str(jobs)})
                self.assertEqual(proc.returncode, 0, proc.stdout)
                self.assertEqual(sorted(m.name for m in marks.glob("timeout-*")), [], "fewer than J classes ever ran together")
                peak = max(int(m.read_text()) for m in marks.glob("peak-*"))
                self.assertEqual(peak, jobs)

    def test_warning_options_reach_the_shards(self):
        self.module("test_warn", """
            import unittest
            import warnings

            class Warns(unittest.TestCase):
                def test_warns(self):
                    warnings.warn("leak", ResourceWarning)
            """)
        proc = subprocess.run(
            [sys.executable, "-W", "error::ResourceWarning", str(RUN_PY), "--top", str(self.top), "--start", "synth"],
            cwd=self.top,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("ResourceWarning: leak", proc.stdout)


if __name__ == "__main__":
    unittest.main()
