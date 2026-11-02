"""Tests for the test harness itself: the subprocess contract, the run comparator, and in-process isolation."""

from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import types
import unittest
import warnings
from pathlib import Path

from scripts.tests import support
from scripts.tests.support import REPO_PY, RepoCase

GUARD = REPO_PY.parent / "hooks" / "guard.py"
PROJECT = REPO_PY.parents[1]
SETTINGS = PROJECT / ".claude" / "settings.json"


class SubprocessContract(RepoCase):
    """Both entry points keep working as real processes, and the in-process path gives the same result."""

    def both(self, script, *args, stdin=None):
        real = support.run_subprocess(script, args, stdin, self.root)
        inproc = support.invoke(support.load(script), script, args, stdin, self.root)
        self.assertIsNone(support.compare_runs((real, {}), (inproc, {})))
        return real

    def test_repo_status_json(self):
        proc = self.both(REPO_PY, "status", "--json", "--ci")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_repo_refusal(self):
        proc = self.both(REPO_PY, "approve", "nope", "plan.md", "--by", "owner")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not found", proc.stderr)

    def test_repo_unknown_subcommand(self):
        proc = self.both(REPO_PY, "frobnicate")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage: repo.py", proc.stderr)

    def test_guard_usage_names_the_script(self):
        proc = self.both(GUARD)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage: guard.py", proc.stderr)

    def test_guard_path_deny_and_allow(self):
        proc = self.both(GUARD, "path", "intent.md", "--proposed", "-", stdin="x")
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["decision"]), (2, "deny"))
        proc = self.both(GUARD, "path", "src/app.py", "--proposed", "-", stdin="print(1)\n")
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["decision"]), (0, "allow"))

    def test_guard_command_ask(self):
        proc = self.both(GUARD, "command", "git push --force")
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["decision"]), (3, "ask"))

    def test_guard_claude_bash_payload(self):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push --force"}, "cwd": str(self.root)})
        proc = self.both(GUARD, "claude", stdin=payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_settings_hook_command_runs_the_guard(self):
        """Run each hook command from .claude/settings.json through a shell, as Claude Code does."""
        data = json.loads(SETTINGS.read_text())
        commands = {h["command"] for entry in data["hooks"]["PreToolUse"] for h in entry["hooks"]}
        payload = json.dumps(
            {"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "intent.md"), "old_string": "# Intent", "new_string": "# Hacked"}, "cwd": str(self.root)}
        )
        for command in commands:
            with self.subTest(command=command):
                proc = subprocess.run(
                    command,
                    shell=True,
                    cwd=self.root,
                    env={**os.environ, **support.GIT_ENV, "CLAUDE_PROJECT_DIR": str(PROJECT)},
                    input=payload,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn("root-baseline", proc.stderr)


def run(code=0, out="", err=""):
    return subprocess.CompletedProcess(["x"], code, out, err)


class CompareRuns(unittest.TestCase):
    """compare_runs ignores exactly the volatile values and catches a one-sided difference in anything else."""

    BASE_STATE = {"repo/a.txt": ("file", 0o644, b"a\n"), "repo/d": ("dir", 0o755), "repo/l": ("link", "a.txt")}

    def same(self, a, b, a_state=None, b_state=None):
        return support.compare_runs((a, a_state or self.BASE_STATE), (b, b_state or self.BASE_STATE))

    def test_identical_runs_match(self):
        self.assertIsNone(self.same(run(0, '{"ok": true}\n'), run(0, '{"ok": true}\n')))

    def test_volatile_values_are_ignored(self):
        cases = [
            ("evidence: .evidence/20261103T010203123456Z/evidence.json", "evidence: .evidence/20261103T090807654321Z/evidence.json"),
            ("recorded at (2026-11-03T01:02:03Z)", "recorded at (2026-11-03T09:08:07Z)"),
            ('"duration_seconds": 0.123,', '"duration_seconds": 4.5,'),
        ]
        for a, b in cases:
            with self.subTest(a=a):
                self.assertIsNone(self.same(run(0, a), run(0, b)))
        tb_a = 'Traceback (most recent call last):\n  File "repo.py", line 1677, in <module>\nUnicodeDecodeError: bad\n'
        tb_b = 'Traceback (most recent call last):\n  File "support.py", line 9, in invoke\nUnicodeDecodeError: bad\n'
        self.assertIsNone(self.same(run(1, err=tb_a), run(1, err=tb_b)))

    def test_run_ids_in_paths_stay_distinct(self):
        older, newer = "20261103T010203000000Z", "20261103T010204000000Z"
        a = {f"ev/{older}/e.json": ("file", 0o644, b"1"), f"ev/{newer}/e.json": ("file", 0o644, b"2")}
        b = {f"ev/{older}/e.json": ("file", 0o644, b"1"), f"ev/{newer}/e.json": ("file", 0o644, b"3")}
        self.assertIsNotNone(self.same(run(), run(), a, b))

    def test_one_sided_differences_are_caught(self):
        base = run(0, '{"ok": true}\n', "")
        outputs = {
            "exit code": run(1, '{"ok": true}\n', ""),
            "extra stdout key": run(0, '{"ok": true, "x": 1}\n', ""),
            "extra stderr line": run(0, '{"ok": true}\n', "warning\n"),
        }
        for name, other in outputs.items():
            with self.subTest(name):
                self.assertIsNotNone(self.same(base, other))
        tb = "Traceback (most recent call last):\n  File \"x\", line 1\nValueError: {}\n"
        self.assertIsNotNone(self.same(run(1, err=tb.format("a")), run(1, err=tb.format("b"))))
        states = {
            "file content": {**self.BASE_STATE, "repo/a.txt": ("file", 0o644, b"b\n")},
            "file mode": {**self.BASE_STATE, "repo/a.txt": ("file", 0o755, b"a\n")},
            "symlink target": {**self.BASE_STATE, "repo/l": ("link", "d")},
            "extra file": {**self.BASE_STATE, "repo/new": ("file", 0o644, b"")},
        }
        for name, state in states.items():
            with self.subTest(name):
                self.assertIsNotNone(self.same(base, base, self.BASE_STATE, state))

    def test_normalization_is_limited_to_its_channel(self):
        """Traceback folding applies only to stderr, and file timestamps only to the `at` field approve writes."""
        tb = "Traceback (most recent call last):\n  File \"x\", line 1\n{}\nValueError: same\n"
        self.assertIsNotNone(self.same(run(1, tb.format("a")), run(1, tb.format("b"))))

        def file(text):
            return {**self.BASE_STATE, "repo/f.txt": ("file", 0o644, text.encode())}

        cases = {
            "traceback marker in a file": (tb.format("a"), tb.format("b")),
            "timestamp outside the at field": ("seen 2026-11-03T01:02:03Z\n", "seen 2026-11-03T09:08:07Z\n"),
        }
        for name, (a, b) in cases.items():
            with self.subTest(name):
                self.assertIsNotNone(self.same(run(), run(), file(a), file(b)))
        at = '{{\n  "at": "{}"\n}}\n'
        self.assertIsNone(self.same(run(), run(), file(at.format("2026-11-03T01:02:03Z")), file(at.format("2026-11-03T09:08:07Z"))))


class TreeState(RepoCase):
    """tree_state records what a call can change in a repository, including a detached HEAD."""

    def test_detached_head_commit_is_recorded(self):
        first = self.git("rev-parse", "HEAD")
        self.git("commit", "--allow-empty", "-m", "second")
        second = self.git("rev-parse", "HEAD")
        area = self.root.parent
        self.git("checkout", "-q", "--detach", first)
        at_first = support.tree_state(area)
        self.git("checkout", "-q", "--detach", second)
        at_second = support.tree_state(area)
        self.assertIsNotNone(support.compare_runs((run(), at_first), (run(), at_second)))

    def test_git_failure_is_not_recorded_as_empty_state(self):
        (self.root / ".git" / "index").write_bytes(b"not an index")
        with self.assertRaises(AssertionError):
            support.tree_state(self.root.parent)


class InProcessIsolation(RepoCase):
    """An in-process call leaves the test process as it found it."""

    def snapshot(self):
        return (os.getcwd(), dict(os.environ), list(sys.argv), sys.stdin, sys.stdout, sys.stderr)

    def test_state_is_restored_on_every_exit_path(self):
        def raises(argv):
            raise RuntimeError("boom")

        def exits(argv):
            raise SystemExit("message")

        modules = {
            "returns": support.load(REPO_PY),
            "system exit": types.SimpleNamespace(main=exits),
            "exception": types.SimpleNamespace(main=raises),
        }
        for name, module in modules.items():
            with self.subTest(name):
                before = self.snapshot()
                proc = support.invoke(module, REPO_PY, ["status", "--json", "--ci"], "stdin text\n", self.root)
                self.assertEqual(self.snapshot(), before)
                if name == "exception":
                    self.assertEqual(proc.returncode, 1)
                    self.assertIn("RuntimeError: boom", proc.stderr)
                if name == "system exit":
                    self.assertEqual((proc.returncode, proc.stderr), (1, "message\n"))

    def test_no_object_process_outlives_the_call(self):
        """approve and close on a closed change read objects; the git process must be closed, not garbage-collected."""
        self.establish_baseline()
        for args in (["approve", "init", "plan.md", "--by", "owner"], ["close", "init", "--evidence", "ci"]):
            with self.subTest(args[0]), warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                proc = support.invoke(support.load(REPO_PY), REPO_PY, args, None, self.root)
                gc.collect()
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertIn("already closed", proc.stderr)
                leaks = [w for w in caught if issubclass(w.category, ResourceWarning)]
                self.assertEqual(leaks, [], [str(w.message) for w in leaks])
                self.assertEqual(self.object_children(), [])

    @staticmethod
    def object_children():
        ps = subprocess.run(["ps", "-A", "-o", "ppid=,stat=,command="], capture_output=True, text=True, check=True).stdout
        mine = str(os.getpid())
        return [line for line in ps.splitlines() if line.split(None, 1)[0] == mine and "cat-file" in line]


if __name__ == "__main__":
    unittest.main()
