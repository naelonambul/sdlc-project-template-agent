"""Fixtures for `repo.py status`: identity, lifecycle, approval, scope, closure."""

import json
import os
import subprocess
import unittest

from scripts.tests.support import RepoCase, digest


class ChangeIdentity(RepoCase):
    def setUp(self):
        super().setUp()
        self.packet("alpha", kind="repository", scope=["src/**"])
        self.commit("alpha packet")

    def pr(self, body):
        (self.root.parent / "body.md").write_text(body)
        return self.status("--pr-body", str(self.root.parent / "body.md"))

    def test_pr_without_change_id_is_blocked(self):
        self.assertFailed(self.pr("## Summary\n<!-- Change-ID: alpha -->\n"), "no `Change-ID")

    def test_pr_with_several_change_ids_is_blocked(self):
        self.assertFailed(self.pr("Change-ID: alpha\nChange-ID: beta\n"), "several Change-IDs")

    def test_pr_change_id_for_missing_packet_is_blocked(self):
        self.assertFailed(self.pr("Change-ID: ghost\n"), "has no packet")

    def test_branch_disagreeing_with_explicit_id_is_blocked(self):
        self.git("switch", "-q", "-c", "change/other")
        self.assertFailed(self.status("--change", "alpha"), "disagree")

    def test_branch_inference_agrees(self):
        self.git("switch", "-q", "-c", "change/alpha")
        result = self.status()
        self.assertEqual(result["active"], "alpha")
        self.assertEqual(result["active_source"], "branch")

    def test_require_change_blocks_without_identity(self):
        self.assertFailed(self.status("--require-change"), "no active change")

    def test_several_touched_packets_are_ambiguous(self):
        self.git("switch", "-q", "-c", "work")
        self.packet("beta", kind="repository")
        self.write("changes/alpha/plan.md", "# edited\n")
        self.assertFailed(self.status(), "several packets touched")


class Lifecycle(RepoCase):
    def test_product_init_missing_spec_blocks_before_plan(self):
        self.packet("init", kind="product-init", artifacts={"intent.md": "# I\n", "plan.md": "# P\n"})
        self.approve("init", "intent.md")
        result = self.status("--change", "init")
        change = result["by_id"]["init"]
        self.assertEqual(change["stage"], "spec")
        self.assertEqual(change["readiness"], "blocked")
        self.assertIn("missing-artifact", self.codes(result, "init"))

    def test_out_of_order_approval_is_blocked(self):
        self.packet("init", kind="product-init", artifacts={"intent.md": "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        self.approve("init", "intent.md", "plan.md")
        result = self.status("--change", "init")
        self.assertIn("out-of-order", self.codes(result, "init"))
        self.assertFailed(result, "approved before upstream spec.md")

    def test_out_of_order_timestamps_are_blocked(self):
        self.packet("init", kind="product-init", artifacts={"intent.md": "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        self.approve("init", "plan.md", "spec.md", "intent.md")  # later seconds for upstream artifacts
        self.assertIn("out-of-order", self.codes(self.status("--change", "init"), "init"))

    def test_ordered_product_init_reaches_implementation(self):
        self.packet("init", kind="product-init", artifacts={"intent.md": "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        self.approve("init", "intent.md", "spec.md", "plan.md")
        change = self.status("--change", "init")["by_id"]["init"]
        self.assertEqual((change["stage"], change["readiness"]), ("implementation", "ready"))

    def test_implementation_kind_needs_established_baseline(self):
        self.packet("impl", baseline={"intent.md": digest("x"), "spec.md": digest("y")})
        self.approve("impl", "plan.md")
        self.assertIn("baseline-unestablished", self.codes(self.status("--change", "impl"), "impl"))

    def test_stale_upstream_digest_is_stale_and_blocked(self):
        self.establish_baseline()
        self.packet("impl", scope=["src/**"])
        self.approve("impl", "plan.md")
        self.commit("impl packet")
        self.assertEqual(self.status("--change", "impl")["by_id"]["impl"]["freshness"], "current")
        self.write("spec.md", "# Spec\nchanged by someone else\n")
        result = self.status("--change", "impl")
        change = result["by_id"]["impl"]
        self.assertEqual((change["freshness"], change["readiness"]), ("stale", "blocked"))
        self.assertFailed(result, "changed since this change was authored")

    def test_missing_upstream_artifact_is_blocked(self):
        self.establish_baseline()
        self.packet("impl")
        self.approve("impl", "plan.md")
        (self.root / "spec.md").unlink()
        result = self.status("--change", "impl")
        self.assertIn("missing-upstream", self.codes(result, "impl"))
        self.assertEqual(result["by_id"]["impl"]["readiness"], "blocked")

    def test_stored_lifecycle_label_is_rejected(self):
        self.packet("alpha", kind="repository", status="accepted")
        self.assertIn("invalid-change", self.codes(self.status("--change", "alpha"), "alpha"))


class Approval(RepoCase):
    def setUp(self):
        super().setUp()
        self.packet("alpha", kind="repository", scope=["src/**"])

    def set_approvals(self, approvals):
        path = self.root / "changes/alpha/change.json"
        data = json.loads(path.read_text())
        data["approvals"] = approvals
        path.write_text(json.dumps(data))

    def test_bare_typed_approver_counts_as_none(self):
        self.set_approvals([{"artifact": "plan.md", "by": "owner"}])
        change = self.status("--change", "alpha")["by_id"]["alpha"]
        self.assertEqual((change["approval"], change["readiness"]), ("none", "blocked"))

    def test_digest_bound_claim_is_unverified_and_ready(self):
        self.approve("alpha", "plan.md")
        change = self.status("--change", "alpha")["by_id"]["alpha"]
        self.assertEqual((change["approval"], change["readiness"]), ("unverified", "ready"))

    def test_local_claim_never_becomes_verified(self):
        self.approve("alpha", "plan.md")
        path = self.root / "changes/alpha/change.json"
        data = json.loads(path.read_text())
        data["approvals"][0]["note"] = "approved on GitHub by a distinct reviewer"
        path.write_text(json.dumps(data))
        self.assertEqual(self.status("--change", "alpha")["by_id"]["alpha"]["approval"], "unverified")

    def test_claim_for_old_bytes_is_stale(self):
        self.approve("alpha", "plan.md")
        self.write("changes/alpha/plan.md", "# Plan, edited after approval\n")
        result = self.status("--change", "alpha")
        change = result["by_id"]["alpha"]
        self.assertEqual((change["freshness"], change["approval"]), ("stale", "none"))
        self.assertFailed(result, "bound to different bytes")


class WriteScope(RepoCase):
    def test_path_escape_in_scope_is_invalid(self):
        for bad in ("../outside", "/etc/passwd", "src/../../x", "C:/win", "a\\b"):
            with self.subTest(bad=bad):
                self.packet("alpha", kind="repository", scope=[bad])
                self.assertIn("scope-path-escape", self.codes(self.status("--change", "alpha"), "alpha"))

    def test_changed_file_outside_scope_is_blocked(self):
        self.packet("alpha", kind="repository", scope=["src/**"])
        self.approve("alpha", "plan.md")
        self.commit("packet")
        self.git("switch", "-q", "-c", "change/alpha")
        self.write("src/ok.txt", "in scope\n")
        self.assertTrue(self.status()["ok"])
        self.write("docs/elsewhere.txt", "out of scope\n")
        self.assertFailed(self.status(), "outside declared write_scope")

    def test_committed_diff_is_checked_against_explicit_base_and_head(self):
        base = self.git("rev-parse", "HEAD")
        self.packet("alpha", kind="repository", scope=["src/**"])
        self.approve("alpha", "plan.md")
        self.write("lib/x.txt", "x\n")
        head = self.commit("candidate")
        result = self.status("--change", "alpha", "--base", base, "--head", head)
        self.assertEqual(result["changed_paths"], ["changes/alpha/change.json", "changes/alpha/plan.md", "lib/x.txt"])
        self.assertFailed(result, "lib/x.txt")

    def test_implementation_before_approval_is_blocked(self):
        self.packet("alpha", kind="repository", scope=["src/**"])
        self.commit("packet")
        self.git("switch", "-q", "-c", "change/alpha")
        self.write("changes/alpha/plan.md", "# Plan, still drafting\n")
        self.assertTrue(self.status()["ok"], "authoring the packet alone is allowed while pending")
        self.write("src/early.txt", "too early\n")
        self.assertFailed(self.status(), "before the change is ready")

    def test_repository_change_cannot_edit_established_baseline(self):
        self.establish_baseline()
        self.packet("alpha", kind="repository", scope=["spec.md"])
        self.approve("alpha", "plan.md")
        self.commit("packet")
        self.git("switch", "-q", "-c", "change/alpha")
        self.write("spec.md", "# Spec\nsneaky\n")
        self.assertFailed(self.status(), "may not modify established root")


class Closure(RepoCase):
    def test_closure_before_delta_merged_is_blocked(self):
        self.packet("init", kind="product-init", artifacts={"intent.md": "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        self.approve("init", "intent.md", "spec.md", "plan.md")
        self.close("init")
        result = self.status("--change", "init")
        self.assertIn("closure-unmerged", self.codes(result, "init"))
        self.assertEqual(result["by_id"]["init"]["closure"], "invalid")

    def test_candidate_closure_is_valid_before_merge(self):
        self.packet("init", kind="product-init", artifacts={"intent.md": "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        self.approve("init", "intent.md", "spec.md", "plan.md")
        self.write("intent.md", "# I\n")
        self.write("spec.md", "# S\n")
        self.close("init")
        self.commit("base")  # nothing yet on another branch; anchor on main is this commit
        self.git("switch", "-q", "-c", "change/next")
        self.git("branch", "-q", "-f", "main", "HEAD~1")
        change = self.status("--change", "init")["by_id"]["init"]
        self.assertEqual((change["stage"], change["closure"], change["readiness"]), ("closed", "candidate", "ready"))

    def test_closure_before_approval_is_blocked(self):
        self.packet("alpha", kind="repository")
        self.close("alpha")
        result = self.status("--change", "alpha")
        self.assertIn("closure-before-approval", self.codes(result, "alpha"))
        self.assertEqual(result["by_id"]["alpha"]["readiness"], "blocked")

    def test_closure_naming_its_own_commit_is_rejected(self):
        self.packet("alpha", kind="repository")
        self.approve("alpha", "plan.md")
        self.close("alpha", commit="0" * 40)
        result = self.status("--change", "alpha")
        self.assertIn("closure-invalid", self.codes(result, "alpha"))
        self.assertTrue(any("never names its own commit" in r["message"] for r in result["by_id"]["alpha"]["reasons"]))

    def test_closure_without_evidence_is_invalid(self):
        self.packet("alpha", kind="repository")
        self.approve("alpha", "plan.md")
        self.close("alpha", evidence=())
        self.assertEqual(self.status("--change", "alpha")["by_id"]["alpha"]["closure"], "invalid")

    def test_squash_merge_anchor_is_frozen(self):
        anchor = self.establish_baseline()
        change = self.status()["by_id"]["init"]
        self.assertEqual((change["closure"], change["freshness"], change["closure_anchor"]), ("frozen", "frozen", anchor))

    def test_merge_commit_is_the_first_parent_anchor(self):
        self.git("switch", "-q", "-c", "change/alpha")
        self.packet("alpha", kind="repository")
        self.approve("alpha", "plan.md")
        self.commit("packet")
        self.close("alpha")
        self.commit("close alpha on the side branch")
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "merge alpha", "change/alpha")
        merge = self.git("rev-parse", "HEAD")
        change = self.status()["by_id"]["alpha"]
        self.assertEqual((change["closure"], change["closure_anchor"]), ("frozen", merge))

    def test_frozen_packet_edit_is_an_integrity_failure(self):
        self.establish_baseline()
        self.write("changes/init/plan.md", "# Plan, rewritten after closure\n")
        result = self.status()
        self.assertIn("frozen-integrity", self.codes(result, "init"))
        self.assertFailed(result, "closed packet changed after closure anchor")

    def test_frozen_change_survives_later_baseline_evolution(self):
        self.establish_baseline()
        self.packet("beh", kind="behavior", scope=["src/**"], artifacts={"spec.md": "# Spec\nv2\n", "plan.md": "# P\n"})
        self.approve("beh", "spec.md", "plan.md")
        self.write("spec.md", "# Spec\nv2\n")
        self.close("beh")
        self.commit("close beh")
        result = self.status()
        self.assertEqual(result["by_id"]["init"]["closure"], "frozen")
        self.assertEqual(result["by_id"]["beh"]["closure"], "frozen")
        self.assertTrue(result["ok"], result["failures"])

    def test_shallow_history_blocks_closure(self):
        self.establish_baseline()
        self.commit("one more")
        clone = self.root.parent / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{self.root}", str(clone)], check=True, capture_output=True)
        result = self.status(cwd=clone)
        self.assertEqual(result["by_id"]["init"]["closure"], "invalid")
        self.assertIn("closure-history", self.codes(result, "init"))
        self.assertFailed(result, "shallow history")


class Surfaces(RepoCase):
    def test_shadowing_claude_md_is_reported(self):
        self.write("CLAUDE.md", "# My rules\n")
        self.commit("shadow")
        self.assertFailed(self.status(), "shadows AGENTS.md")

    def test_claude_md_importing_agents_md_is_accepted(self):
        self.write(".claude/CLAUDE.md", "@../AGENTS.md\n\nExtra notes.\n")
        self.write("CLAUDE.md", "See @AGENTS.md for the rules.\n")
        self.commit("imports")
        self.assertTrue(self.status()["ok"])

    def test_local_claude_md_warns_only_locally(self):
        self.write("CLAUDE.local.md", "# private\n")
        self.write(".gitignore", "CLAUDE.local.md\n")
        self.commit("ignore")
        local = self.run_repo("status", "--json")
        warnings = [s for s in json.loads(local.stdout)["surface"] if s["code"] == "instruction-shadowed-local"]
        self.assertEqual((local.returncode, len(warnings)), (0, 1))
        self.assertEqual([s for s in self.status()["surface"] if s["code"] == "instruction-shadowed-local"], [])

    def adapters(self):
        self.write(".agents/skills/demo/SKILL.md", "---\nname: demo\n---\n")
        (self.root / ".claude/skills").mkdir(parents=True)

    def test_symlink_adapter_is_valid(self):
        self.adapters()
        os.symlink("../../.agents/skills/demo", self.root / ".claude/skills/demo")
        self.assertTrue(self.status()["ok"])

    def test_plain_file_adapter_is_broken(self):
        self.adapters()
        self.write(".claude/skills/demo", "../../.agents/skills/demo")  # what core.symlinks=false checks out
        self.assertFailed(self.status(), "core.symlinks=false")

    def test_copied_skill_adapter_is_broken(self):
        self.adapters()
        self.write(".claude/skills/demo/SKILL.md", "---\nname: demo\n---\n")
        self.assertFailed(self.status(), "is a copy")

    def settings(self, command):
        hooks = {"hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": command}]}]}}
        self.write(".claude/settings.json", json.dumps(hooks))

    def hook_script(self, name="guard.py", executable=True):
        self.write(f"scripts/hooks/{name}", "#!/usr/bin/env python3\n")
        if executable:
            (self.root / "scripts/hooks" / name).chmod(0o755)

    def surface_codes(self, result):
        return {s["code"] for s in result["surface"]}

    def test_wired_executable_hook_is_valid(self):
        self.hook_script()
        self.settings('python3 "$CLAUDE_PROJECT_DIR"/scripts/hooks/guard.py claude')
        self.commit("hooks")
        result = self.status()
        self.assertTrue(result["ok"], result["failures"])
        self.assertNotIn("hook-adapter-missing", self.surface_codes(result))

    def test_hook_pointing_at_missing_script_is_broken(self):
        self.settings("python3 scripts/hooks/missing.py claude")
        self.commit("hooks")
        self.assertFailed(self.status(), "scripts/hooks/missing.py, which is not tracked")

    def test_non_executable_hook_script_is_broken(self):
        self.hook_script(executable=False)
        self.settings("python3 scripts/hooks/guard.py claude")
        self.commit("hooks")
        self.assertFailed(self.status(), "is not executable")

    def test_invalid_settings_json_is_broken(self):
        self.write(".claude/settings.json", "{not json")
        self.commit("hooks")
        self.assertFailed(self.status(), "not valid JSON")

    def test_unwired_hook_script_is_informational(self):
        self.hook_script()
        self.commit("hooks")
        result = self.status()
        self.assertTrue(result["ok"])
        self.assertIn("hook-adapter-missing", self.surface_codes(result))


class RegisteredChecks(RepoCase):
    def configure(self):
        check = {"id": "control-plane", "argv": ["true"], "cwd": ".", "timeout_seconds": 5, "paths": ["scripts/**"]}
        self.write("checks.json", json.dumps({"schema": 1, "checks": [check]}))

    def warnings(self):
        return [s for s in self.status()["surface"] if s["code"] == "checks-unregistered"]

    def test_template_only_tree_does_not_warn(self):
        self.configure()
        self.write("scripts/repo.py", "")
        self.write("docs/notes.md", "")
        self.commit("template")
        self.assertEqual(self.warnings(), [])

    def test_product_files_with_only_control_plane_warn(self):
        self.configure()
        self.write("src/app.py", "print('hi')\n")
        self.commit("product")
        warnings = self.warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("'src/app.py'", warnings[0]["message"])
        self.assertTrue(self.status()["ok"])

    def test_registered_product_check_silences_warning(self):
        self.configure()
        config = json.loads(self.read("checks.json"))
        config["checks"].append({"id": "unit", "argv": ["true"], "cwd": ".", "timeout_seconds": 5, "paths": ["src/**"]})
        self.write("checks.json", json.dumps(config))
        self.write("src/app.py", "")
        self.commit("product")
        self.assertEqual(self.warnings(), [])


class CheckWiring(RepoCase):
    WORKFLOW = "jobs:\n  a:\n    steps:\n      - run: python3 scripts/repo.py verify --group core $ARGS\n"

    def configure(self, groups, workflow):
        checks = [
            {"id": f"c-{g}", "group": g, "argv": ["true"], "cwd": ".", "timeout_seconds": 5, "paths": ["**"]}
            for g in groups
        ]
        self.write("checks.json", json.dumps({"schema": 1, "checks": checks}))
        self.write(".github/workflows/repository.yml", workflow)
        self.commit("wiring")

    def test_wired_groups_pass(self):
        self.configure(["core"], self.WORKFLOW)
        self.assertTrue(self.status()["ok"])

    def test_group_without_ci_job_fails(self):
        self.configure(["core", "web"], self.WORKFLOW)
        self.assertFailed(self.status(), "check group 'web' has no")

    def test_ci_job_for_undeclared_group_fails(self):
        self.configure([], self.WORKFLOW)
        self.assertFailed(self.status(), "does not declare")

    def test_invalid_checks_json_fails_status(self):
        self.write("checks.json", json.dumps({"schema": 1, "checks": [{"id": "x", "argv": "make test"}]}))
        self.commit("bad")
        self.assertFailed(self.status(), "never a shell string")


if __name__ == "__main__":
    unittest.main()
