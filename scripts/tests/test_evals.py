"""scripts/evals.py against a stub harness on PATH (no real harness needed)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import evals
from scripts.tests.support import GIT_ENV, RepoCase

EVALS_PY = Path(__file__).resolve().parents[1] / "evals.py"
ROOT = Path(__file__).resolve().parents[2]

STUB = f"""#!{sys.executable}
import os, sys, time
if os.environ.get("EVAL_STUB_SLEEP"):
    time.sleep(float(os.environ["EVAL_STUB_SLEEP"]))
if os.environ.get("EVAL_STUB_TOUCH"):
    with open(os.environ["EVAL_STUB_TOUCH"], "a") as f:
        f.write("touched by stub\\n")
out = os.environ.get("EVAL_STUB_STDOUT", "")
if os.environ.get("EVAL_STUB_ARGV"):
    out += "\\nARGV=" + repr(sys.argv[1:])
if os.environ.get("EVAL_STUB_ENV"):
    name = os.environ["EVAL_STUB_ENV"]
    out += "\\n" + name + "=" + os.environ.get(name, "<unset>")
if os.environ.get("EVAL_STUB_LS"):
    out += "\\nLS=" + repr(sorted(os.listdir(".")))
    for p in os.environ["EVAL_STUB_LS"].split(","):
        out += "\\nLINK " + p + "=" + (os.readlink(p) if os.path.islink(p) else "<not a link>")
print(out)
sys.exit(int(os.environ.get("EVAL_STUB_EXIT", "0")))
"""


class EvalCase(RepoCase):
    def setUp(self):
        super().setUp()
        self._bins = tempfile.TemporaryDirectory()
        bins = Path(self._bins.name)
        self.git_only = bins / "git-only"
        self.stub_bin = bins / "stub"
        for d in (self.git_only, self.stub_bin):
            d.mkdir()
            os.symlink(shutil.which("git"), d / "git")
        for name in evals.HARNESSES:
            stub = self.stub_bin / name
            stub.write_text(STUB)
            stub.chmod(0o755)
        self.evidence = Path(self._tmp.name) / "evidence"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("EVAL_STUB_")}
        self.env.update(GIT_ENV)
        self.env["PATH"] = str(self.stub_bin)

    def tearDown(self):
        self._bins.cleanup()
        super().tearDown()

    def case(self, cid="sample", harnesses=("claude",), expect=None, **extra):
        data = {
            "schema": 1,
            "harnesses": list(harnesses),
            "prompt": "say hello",
            "expect": expect or {"stdout_contains": ["hello"]},
            **extra,
        }
        self.write(f"evals/{cid}/eval.json", json.dumps(data, indent=2) + "\n")

    def run_evals(self, *args, evidence=True, **env):
        extra = ["--evidence-dir", str(self.evidence)] if evidence else []
        proc = subprocess.run(
            [sys.executable, str(EVALS_PY), *args, *extra],
            cwd=self.root,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc

    def results(self, *args, **env):
        proc = self.run_evals("--json", *args, **env)
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise AssertionError(f"no JSON (exit {proc.returncode}): {proc.stdout}{proc.stderr}")
        report["exit"] = proc.returncode
        report["by"] = {(r["case"], r["harness"]): r for r in report["results"]}
        return report

    def only(self, report):
        self.assertEqual(len(report["results"]), 1, report["results"])
        return report["results"][0]


class Outcomes(EvalCase):
    def test_passed_when_stdout_contains(self):
        self.case()
        report = self.results(EVAL_STUB_STDOUT="hello world")
        self.assertEqual(self.only(report)["status"], "passed")
        self.assertEqual(report["exit"], 0)

    def test_failed_when_text_missing(self):
        self.case()
        report = self.results(EVAL_STUB_STDOUT="goodbye")
        r = self.only(report)
        self.assertEqual(r["status"], "failed")
        self.assertIn("'hello'", r["reason"])
        self.assertEqual(report["exit"], 1)

    def test_stdout_not_contains(self):
        self.case(expect={"stdout_not_contains": ["DONE"]})
        self.assertEqual(self.only(self.results(EVAL_STUB_STDOUT="BLOCKED: no"))["status"], "passed")
        self.assertEqual(self.only(self.results(EVAL_STUB_STDOUT="DONE"))["status"], "failed")

    def test_files_unchanged_passes_when_untouched(self):
        self.case(expect={"files_unchanged": ["intent.md"]})
        self.assertEqual(self.only(self.results())["status"], "passed")

    def test_files_unchanged_fails_when_touched(self):
        self.case(expect={"files_unchanged": ["intent.md"]})
        r = self.only(self.results(EVAL_STUB_TOUCH="intent.md"))
        self.assertEqual(r["status"], "failed")
        self.assertIn("intent.md changed", r["reason"])
        self.assertNotIn("touched by stub", self.read("intent.md"))

    def test_files_changed(self):
        self.case(expect={"files_changed": ["new.txt", "intent.md"]})
        self.assertEqual(self.only(self.results(EVAL_STUB_TOUCH="new.txt"))["status"], "failed")
        self.case(expect={"files_changed": ["new.txt"]})
        self.assertEqual(self.only(self.results(EVAL_STUB_TOUCH="new.txt"))["status"], "passed")
        self.assertFalse((self.root / "new.txt").exists())

    def test_case_files_are_written_into_scratch(self):
        self.case(files={"notes/a.md": "x\n"}, expect={"files_unchanged": ["notes/a.md"]})
        self.assertEqual(self.only(self.results())["status"], "passed")
        self.assertFalse((self.root / "notes").exists())

    def test_skipped_when_harness_missing(self):
        self.case()
        report = self.results(PATH=str(self.git_only))
        r = self.only(report)
        self.assertEqual(r["status"], "skipped")
        self.assertEqual(report["exit"], 0)

    def test_require_harness_turns_skip_into_failure(self):
        self.case()
        report = self.results("--require-harness", PATH=str(self.git_only))
        self.assertEqual(self.only(report)["status"], "failed")
        self.assertEqual(report["exit"], 1)

    def test_error_on_timeout(self):
        self.case(timeout_seconds=1)
        report = self.results(EVAL_STUB_SLEEP="30", EVAL_STUB_STDOUT="hello")
        r = self.only(report)
        self.assertEqual(r["status"], "error")
        self.assertIn("timed out", r["reason"])
        self.assertIsNone(r["exit_code"])
        self.assertLess(r["duration_seconds"], 20)
        self.assertEqual(report["exit"], 1)

    def test_error_on_nonzero_exit(self):
        self.case()
        r = self.only(self.results(EVAL_STUB_STDOUT="hello", EVAL_STUB_EXIT="3"))
        self.assertEqual((r["status"], r["exit_code"]), ("error", 3))

    def test_error_on_malformed_case(self):
        self.write("evals/broken/eval.json", "{not json")
        self.case(cid="bad", harnesses=["vim"], expect={"stdout_has": ["x"]})
        report = self.results(EVAL_STUB_STDOUT="hello")
        self.assertEqual(report["by"][("broken", None)]["status"], "error")
        bad = report["by"][("bad", None)]
        self.assertEqual(bad["status"], "error")
        self.assertIn("harnesses", bad["reason"])
        self.assertIn("expect", bad["reason"])
        self.assertEqual(report["exit"], 1)


class Selection(EvalCase):
    def test_case_and_harness_filters(self):
        self.case(cid="one", harnesses=["claude", "codex"])
        self.case(cid="two")
        report = self.results("--case", "one", EVAL_STUB_STDOUT="hello")
        self.assertEqual(set(report["by"]), {("one", "claude"), ("one", "codex")})
        report = self.results("--case", "one", "--harness", "codex", EVAL_STUB_STDOUT="hello")
        self.assertEqual(set(report["by"]), {("one", "codex")})
        self.assertEqual(self.run_evals("--case", "nope").returncode, 2)

    def test_list(self):
        self.case(cid="one", harnesses=["claude", "codex"])
        self.case(cid="two")
        proc = self.run_evals("--list", evidence=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ["one  claude,codex", "two  claude"])
        self.assertFalse((self.root / ".evidence").exists())


class Evidence(EvalCase):
    def test_evidence_files_and_results_shape(self):
        self.case(harnesses=["claude", "codex"])
        report = self.results(EVAL_STUB_STDOUT="hello")
        on_disk = json.loads((self.evidence / "results.json").read_text())
        self.assertEqual(on_disk["results"], report["results"])
        self.assertEqual(on_disk["schema"], 1)
        self.assertRegex(on_disk["run_id"], r"^\d{8}T\d{12}Z$")
        self.assertEqual(on_disk["source"], {"commit": self.git("rev-parse", "HEAD"), "dirty": True})
        for r in report["results"]:
            self.assertEqual(
                set(r), {"case", "harness", "status", "reason", "duration_seconds", "exit_code", "stdout_log", "stderr_log"}
            )
            self.assertIn("hello", Path(r["stdout_log"]).read_text())
            self.assertTrue(Path(r["stderr_log"]).is_file())
        self.assertTrue((self.evidence / "sample.codex.stdout.log").is_file())

    def test_default_evidence_dir_and_human_output(self):
        self.case()
        proc = self.run_evals(evidence=False, EVAL_STUB_STDOUT="hello")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0], "passed  sample  claude  (all expectations met)")
        self.assertRegex(lines[1], r"^evidence: \.evidence/evals/\d{8}T\d{12}Z$")
        run = self.root / lines[1].split(": ", 1)[1]
        self.assertTrue((run / "results.json").is_file())
        self.assertTrue((run / "sample.claude.stdout.log").is_file())


class Scratch(EvalCase):
    def test_symlink_preserved_and_untracked_file_included(self):
        os.symlink("intent.md", self.root / "link.md")
        self.commit("link")
        self.write("untracked.txt", "u\n")
        self.write(".gitignore", "ignored.txt\n")
        self.write("ignored.txt", "i\n")
        self.case()
        r = self.only(self.results(EVAL_STUB_STDOUT="hello", EVAL_STUB_LS="link.md"))
        out = Path(r["stdout_log"]).read_text()
        self.assertIn("LINK link.md=intent.md", out)
        self.assertIn("'untracked.txt'", out)
        self.assertNotIn("ignored.txt'", out)

    def test_claudecode_removed_from_child_env(self):
        self.case()
        r = self.only(self.results(EVAL_STUB_STDOUT="hello", EVAL_STUB_ENV="CLAUDECODE", CLAUDECODE="1"))
        self.assertIn("CLAUDECODE=<unset>", Path(r["stdout_log"]).read_text())

    def test_harness_argv(self):
        self.case(harnesses=["claude", "codex"], args={"claude": ["--x"], "codex": ["--json"]})
        report = self.results(EVAL_STUB_STDOUT="hello", EVAL_STUB_ARGV="1")
        claude = Path(report["by"][("sample", "claude")]["stdout_log"]).read_text()
        codex = Path(report["by"][("sample", "codex")]["stdout_log"]).read_text()
        self.assertIn("ARGV=['-p', 'say hello', '--output-format', 'text', '--x']", claude)
        self.assertIn("ARGV=['exec', '--sandbox', 'read-only', '--json', 'say hello']", codex)


class ShippedCases(unittest.TestCase):
    def test_every_shipped_case_validates(self):
        cases = evals.discover_cases(ROOT)
        self.assertGreaterEqual(len(cases), 5)
        for case in cases:
            self.assertEqual(case.problems, [], case.id)

    def test_validation_rejects_unsafe_paths(self):
        base = {"schema": 1, "harnesses": ["claude"], "prompt": "p", "expect": {"stdout_contains": ["x"]}}
        self.assertEqual(evals.validate_case(base), [])
        for rel in ("../x", "/etc/passwd", ".git/config"):
            self.assertTrue(evals.validate_case({**base, "files": {rel: "x"}}), rel)
        self.assertTrue(evals.validate_case({**base, "timeout_seconds": 0}))
        self.assertTrue(evals.validate_case({**base, "schema": 2}))
