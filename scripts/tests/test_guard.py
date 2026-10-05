"""Tests for the agent-neutral hook guard and its Claude Code adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.tests import support
from scripts.tests.support import RepoCase

GUARD = Path(__file__).resolve().parents[1] / "hooks" / "guard.py"
SETTINGS = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"


class GuardCase(RepoCase):
    def run_guard(self, *args, stdin=None, cwd=None):
        return subprocess.run(
            [sys.executable, str(GUARD), *args],
            cwd=cwd or self.root,
            env={**os.environ, **support.GIT_ENV},
            input=stdin,
            capture_output=True,
            text=True,
        )

    def path(self, rel, proposed=None):
        args = ["path", rel]
        stdin = None
        if proposed is not None:
            args += ["--proposed", "-"]
            stdin = proposed
        proc = self.run_guard(*args, stdin=stdin)
        return proc.returncode, json.loads(proc.stdout)

    def command(self, text):
        proc = self.run_guard("command", text)
        return proc.returncode, json.loads(proc.stdout)

    def claude(self, payload):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return self.run_guard("claude", stdin=stdin)

    def change_json(self, cid, **override):
        data = json.loads(self.read(f"changes/{cid}/change.json"))
        data.update(override)
        return json.dumps(data, indent=2) + "\n"


class PathRuleTests(GuardCase):
    def test_root_intent_and_spec_denied(self):
        for name in ("intent.md", "spec.md"):
            code, out = self.path(name, "# changed\n")
            self.assertEqual((code, out["decision"]), (2, "deny"), name)
            self.assertIn("root-baseline", out["reason"])

    def test_root_intent_denied_by_absolute_path(self):
        code, out = self.path(str(self.root / "intent.md"), "x")
        self.assertEqual((code, out["decision"]), (2, "deny"))

    def test_change_local_intent_allowed(self):
        code, out = self.path("changes/x/intent.md", "# local\n")
        self.assertEqual((code, out["decision"]), (0, "allow"))

    def test_closure_json_denied(self):
        self.packet("x")
        code, out = self.path("changes/x/closure.json", "{}")
        self.assertEqual((code, out["decision"]), (2, "deny"))
        self.assertIn("closure", out["reason"])

    def test_approvals_changed_denied(self):
        self.packet("x")
        forged = self.change_json("x", approvals=[{"artifact": "plan.md", "sha256": "sha256:0", "by": "me", "at": "now"}])
        code, out = self.path("changes/x/change.json", forged)
        self.assertEqual((code, out["decision"]), (2, "deny"))
        self.assertIn("change-approvals", out["reason"])

    def test_approvals_removed_denied(self):
        self.packet("x")
        self.write("changes/x/plan.md", "# Plan\n")
        self.approve("x", "plan.md")
        code, out = self.path("changes/x/change.json", self.change_json("x", approvals=[]))
        self.assertEqual((code, out["decision"]), (2, "deny"))

    def test_write_scope_only_change_allowed(self):
        self.packet("x")
        code, out = self.path("changes/x/change.json", self.change_json("x", write_scope=["src/**"]))
        self.assertEqual((code, out["decision"]), (0, "allow"))

    def test_existing_approvals_kept_allowed(self):
        self.packet("x")
        self.approve("x", "plan.md")
        code, out = self.path("changes/x/change.json", self.change_json("x", write_scope=["a"]))
        self.assertEqual((code, out["decision"]), (0, "allow"))

    def test_no_proposed_content_denied(self):
        self.packet("x")
        code, out = self.path("changes/x/change.json")
        self.assertEqual((code, out["decision"]), (2, "deny"))

    def test_unparseable_proposed_denied(self):
        self.packet("x")
        code, out = self.path("changes/x/change.json", "{not json")
        self.assertEqual((code, out["decision"]), (2, "deny"))

    def test_new_change_json_without_approvals_allowed(self):
        code, out = self.path("changes/new/change.json", json.dumps({"schema": 1, "approvals": []}))
        self.assertEqual((code, out["decision"]), (0, "allow"))

    def test_proposed_from_file(self):
        self.packet("x")
        target = self.root.parent / "proposed.json"
        target.write_text(self.change_json("x", write_scope=["b"]))
        proc = self.run_guard("path", "changes/x/change.json", "--proposed", str(target))
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_frozen_packet_denied_when_baseline_has_closure(self):
        self.packet("x")
        self.close("x")
        self.commit("closed x")
        self.git("switch", "-q", "-c", "followup")
        code, out = self.path("changes/x/plan.md", "# edited\n")
        self.assertEqual((code, out["decision"]), (2, "deny"))
        self.assertIn("frozen-packet", out["reason"])

    def test_open_packet_allowed_when_baseline_has_no_closure(self):
        self.packet("x")
        self.commit("open x")
        self.git("switch", "-q", "-c", "followup")
        code, out = self.path("changes/x/plan.md", "# edited\n")
        self.assertEqual((code, out["decision"]), (0, "allow"))

    def test_frozen_uses_checks_json_baseline_branch(self):
        self.write("checks.json", json.dumps({"baseline_branch": "trunk"}))
        self.packet("x")
        self.close("x")
        self.commit("closed x on main")
        self.git("switch", "-q", "-c", "followup")
        code, out = self.path("changes/x/plan.md", "# edited\n")
        self.assertEqual((code, out["decision"]), (0, "allow"))
        self.git("branch", "trunk", "main")
        code, out = self.path("changes/x/plan.md", "# edited\n")
        self.assertEqual((code, out["decision"]), (2, "deny"))

    def test_path_outside_repository_allowed(self):
        code, out = self.path("/etc/hosts", "x")
        self.assertEqual((code, out["decision"]), (0, "allow"))
        code, out = self.path("../intent.md", "x")
        self.assertEqual((code, out["decision"]), (0, "allow"))

    def test_ordinary_source_file_allowed(self):
        code, out = self.path("src/app.py", "print(1)\n")
        self.assertEqual((code, out["decision"]), (0, "allow"))

    def test_no_repository_allows_with_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_guard("path", "intent.md", "--proposed", "-", stdin="x", cwd=tmp)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["decision"], "allow")
        self.assertTrue(proc.stderr.strip())


class CommandRuleTests(GuardCase):
    ASK = [
        "git push --force origin x",
        "git push -f origin x",
        "git push origin x --force-with-lease",
        "git push origin +main",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git clean -fdx",
        "git branch -D old",
        "git rebase main",
        "git commit --amend --no-edit",
        "git filter-branch --all",
        "git push --delete origin old",
        "git push origin :old",
        "git -C sub push --force",
        "cd sub && git reset --hard",
        "python3 scripts/repo.py approve x plan.md --by me",
        "echo '{}' > changes/x/change.json",
        "sed -i 's/a/b/' changes/x/closure.json",
        "echo x | tee changes/x/change.json",
        "mv /tmp/c.json changes/x/change.json",
        "cp /tmp/c.json changes/x/closure.json",
        "rm changes/x/closure.json",
        "python3 -c 'open(\"changes/x/change.json\", \"w\")'",
        "git status\ngit reset --hard",
        "git status\ngit push -f origin x",
        "bash -c 'git reset --hard'",
        "sh -c \"git push -f origin x\"",
        "python3 scripts/repo.py  approve x plan.md --by me",
        "jq . /tmp/in.json > changes/x/change.json",
    ]
    ALLOW = [
        "git status",
        "git push origin HEAD",
        "git push -u origin feature",
        "git reset --soft HEAD~1",
        "git clean -n",
        "git branch -d merged",
        "git commit -m 'git push --force and rebase'",
        "git commit -m 'docs: repo.py approve'",
        "grep 'repo.py approve' README.md",
        "cat changes/x/change.json",
        "cat changes/x/change.json 2>/dev/null",
        "jq . changes/x/change.json > /dev/null",
        "git diff changes/x/change.json > /tmp/p",
        "cp changes/x/change.json /tmp/backup.json",
        "python3 scripts/repo.py status --change x",
        "python3 scripts/repo.py close x --evidence y",
        "ls 2>&1",
    ]

    def test_ask_commands(self):
        for text in self.ASK:
            with self.subTest(command=text):
                code, out = self.command(text)
                self.assertEqual((code, out["decision"]), (3, "ask"))
                self.assertTrue(out["reason"])

    def test_allow_commands(self):
        for text in self.ALLOW:
            with self.subTest(command=text):
                code, out = self.command(text)
                self.assertEqual((code, out["decision"]), (0, "allow"))


class ClaudeAdapterTests(GuardCase):
    def test_edit_root_intent_denied_with_stderr(self):
        proc = self.claude(
            {"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "intent.md"), "old_string": "# Intent", "new_string": "# Hacked"}, "cwd": str(self.root)}
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("root-baseline", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_write_changing_approvals_denied(self):
        self.packet("x")
        forged = self.change_json("x", approvals=[{"artifact": "plan.md", "sha256": "sha256:0", "by": "me", "at": "now"}])
        proc = self.claude(
            {"tool_name": "Write", "tool_input": {"file_path": str(self.root / "changes/x/change.json"), "content": forged}, "cwd": str(self.root)}
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("change-approvals", proc.stderr)

    def test_edit_keeping_approvals_allowed(self):
        self.packet("x")
        self.approve("x", "plan.md")
        proc = self.claude(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(self.root / "changes/x/change.json"), "old_string": '"write_scope": []', "new_string": '"write_scope": ["src/**"]'},
                "cwd": str(self.root),
            }
        )
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_edit_changing_approvals_denied(self):
        self.packet("x")
        proc = self.claude(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(self.root / "changes/x/change.json"), "old_string": '"approvals": []', "new_string": '"approvals": [{"artifact": "plan.md"}]'},
                "cwd": str(self.root),
            }
        )
        self.assertEqual(proc.returncode, 2)

    def test_multiedit_applies_edits_in_order(self):
        self.packet("x")
        edits = [
            {"old_string": '"write_scope": []', "new_string": '"write_scope": ["a"]'},
            {"old_string": '"approvals": []', "new_string": '"approvals": ["forged"]'},
        ]
        proc = self.claude(
            {"tool_name": "MultiEdit", "tool_input": {"file_path": str(self.root / "changes/x/change.json"), "edits": edits}, "cwd": str(self.root)}
        )
        self.assertEqual(proc.returncode, 2)
        proc = self.claude(
            {"tool_name": "MultiEdit", "tool_input": {"file_path": str(self.root / "changes/x/change.json"), "edits": edits[:1]}, "cwd": str(self.root)}
        )
        self.assertEqual(proc.returncode, 0)

    def test_edit_of_missing_file_uses_new_string(self):
        proc = self.claude(
            {"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "changes/n/change.json"), "old_string": "", "new_string": '{"approvals": ["x"]}'}, "cwd": str(self.root)}
        )
        self.assertEqual(proc.returncode, 2)

    def test_bash_force_push_asks(self):
        proc = self.claude({"tool_name": "Bash", "tool_input": {"command": "git push --force"}, "cwd": str(self.root)})
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PreToolUse")
        self.assertEqual(out["permissionDecision"], "ask")
        self.assertIn("force-push", out["permissionDecisionReason"])

    def test_bash_cwd_defaults_to_process_cwd(self):
        proc = self.claude({"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}})
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_bash_benign_allowed_silently(self):
        proc = self.claude({"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": str(self.root)})
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_unknown_tool_allowed(self):
        proc = self.claude({"tool_name": "Read", "tool_input": {"file_path": str(self.root / "intent.md")}, "cwd": str(self.root)})
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_garbage_stdin_allowed_with_note(self):
        for garbage in ("not json", "", "[1, 2]"):
            with self.subTest(stdin=garbage):
                proc = self.claude(garbage)
                self.assertEqual((proc.returncode, proc.stdout), (0, ""))
                self.assertTrue(proc.stderr.strip())

    def test_malformed_tool_input_allowed_with_note(self):
        self.packet("x")
        payloads = [
            {"tool_name": "MultiEdit", "tool_input": {"file_path": "changes/x/change.json", "edits": "oops"}, "cwd": str(self.root)},
            {"tool_name": "Edit", "tool_input": {"file_path": "changes/x/change.json", "old_string": 5, "new_string": None}, "cwd": str(self.root)},
            {"tool_name": "Bash", "tool_input": {"command": ["not", "a", "string"]}, "cwd": str(self.root)},
        ]
        for payload in payloads:
            with self.subTest(tool=payload["tool_name"]):
                proc = self.claude(payload)
                self.assertEqual((proc.returncode, proc.stdout), (0, ""), proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)


class SettingsAdapterTests(unittest.TestCase):
    def test_settings_holds_only_hooks_calling_the_guard(self):
        data = json.loads(SETTINGS.read_text())
        self.assertEqual(list(data), ["hooks"])
        self.assertEqual(list(data["hooks"]), ["PreToolUse"])
        commands = [h["command"] for entry in data["hooks"]["PreToolUse"] for h in entry["hooks"]]
        self.assertTrue(commands)
        for command in commands:
            self.assertTrue(command.endswith("scripts/hooks/guard.py claude"), command)
        self.assertEqual({e["matcher"] for e in data["hooks"]["PreToolUse"]}, {"Edit|Write|MultiEdit", "Bash"})

    def test_guard_is_executable_python(self):
        self.assertTrue(os.access(GUARD, os.X_OK))
        self.assertTrue(GUARD.read_text().startswith("#!/usr/bin/env python3\n"))


if __name__ == "__main__":
    unittest.main()
