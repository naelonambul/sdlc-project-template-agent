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
        self.assertRegex(self.summary(proc), r"^OK: ran 10 tests in 3 shards")

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
        self.assertRegex(self.summary(proc), r"^FAILED: .*no test summary")

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

    def test_test_output_cannot_stand_in_for_the_summary(self):
        self.module("test_fake", """
            import sys
            import unittest

            class Fake(unittest.TestCase):
                def test_prints_a_summary(self):
                    sys.stderr.write("Ran 5 tests in 0.001s\\n\\nOK\\n")
            """)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertRegex(self.summary(proc), r"^FAILED: .*ambiguous test summary")

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

    def test_classes_stay_whole_and_assignment_is_deterministic(self):
        self.classes(7)
        first, second = self.run_runner("--jobs", "3"), self.run_runner("--jobs", "3")
        self.assertEqual(first.returncode, 0, first.stdout)
        lines = self.shard_lines(first)
        self.assertEqual(len(lines), 3)
        self.assertEqual([re.sub(r" in [0-9.]+s", "", line) for line in lines], [re.sub(r" in [0-9.]+s", "", line) for line in self.shard_lines(second)])
        named = re.findall(r"Case\d+", " ".join(lines))
        self.assertEqual(sorted(named), sorted(f"Case{i}" for i in range(7)))  # each class appears in exactly one shard
        for line in lines:
            tests = int(re.search(r": (\d+) tests", line).group(1))
            classes = len(re.findall(r"Case\d+", line))
            self.assertEqual(tests, 2 * classes)

    def test_jobs_one_runs_one_process(self):
        self.classes(4)
        proc = self.run_runner("--jobs", "1")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(len(self.shard_lines(proc)), 1)
        self.assertRegex(self.summary(proc), r"^OK: ran 8 tests in 1 shard\b")

    def test_jobs_from_environment_and_flag(self):
        self.classes(6)
        proc = self.run_runner(env={"SDLC_TEST_JOBS": "2"})
        self.assertEqual(len(self.shard_lines(proc)), 2, proc.stdout)
        proc = self.run_runner("--jobs", "4", env={"SDLC_TEST_JOBS": "2"})
        self.assertEqual(len(self.shard_lines(proc)), 4, proc.stdout)

    def test_never_more_shards_than_classes(self):
        self.classes(2)
        proc = self.run_runner("--jobs", "8")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(len(self.shard_lines(proc)), 2)

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
