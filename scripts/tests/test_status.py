"""Fixtures for `repo.py status`: identity, lifecycle, approval, scope, closure."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest

from scripts.tests.support import REPO_PY, UNESTABLISHED, RepoCase, digest


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


class Revision(RepoCase):
    def implementing(self):
        self.git("switch", "-q", "-c", "change/imp")
        self.packet("imp", kind="repository", scope=["src/**"])
        self.commit("packet")
        self.write("src/a.txt", "x\n")

    def test_a_stale_plan_does_not_report_the_work_as_premature(self):
        self.implementing()
        self.approve("imp", "plan.md")
        self.write("changes/imp/plan.md", "# Plan v2\n")
        result = self.status("--change", "imp")
        self.assertEqual(result["exit"], 1)
        self.assertIn("stale-approval", self.codes(result, "imp"))
        self.assertEqual(result["by_id"]["imp"]["readiness"], "blocked")
        self.assertNotIn("not-ready", self.codes(result, "imp"))
        self.assertNotIn("awaiting-approval", self.codes(result, "imp"))

    def test_a_never_approved_plan_still_reports_premature_work(self):
        self.implementing()
        self.assertIn("not-ready", self.codes(self.status("--change", "imp"), "imp"))

    def test_a_reapproved_spec_blocks_until_the_plan_follows(self):
        self.establish_baseline()
        self.packet("beh", kind="behavior", artifacts={"spec.md": "# Spec\nnew\n", "plan.md": "# P\n"})
        self.approve("beh", "spec.md", "plan.md")
        self.write("changes/beh/spec.md", "# Spec\nnewer\n")
        self.assertEqual(self.run_repo("approve", "beh", "spec.md", "--by", "owner").returncode, 0)
        result = self.status("--change", "beh")
        self.assertIn("out-of-order", self.codes(result, "beh"))
        self.assertTrue(any("re-approve" in f for f in result["failures"]), result["failures"])
        self.assertEqual(self.run_repo("approve", "beh", "plan.md", "--by", "owner").returncode, 0)
        self.assertNotIn("out-of-order", self.codes(self.status("--change", "beh"), "beh"))


class SmallGates(RepoCase):
    def wiring(self, comment):
        checks = [{"id": g, "group": g, "argv": ["python3", "-c", "1"], "cwd": ".", "timeout_seconds": 9, "paths": ["**"], "requires": []} for g in ("core", "web")]
        self.write("checks.json", json.dumps({"schema": 1, "baseline_branch": "main", "checks": checks}))
        self.write(".github/workflows/repository.yml", f"jobs:\n  a:\n    steps:\n      - run: python3 scripts/repo.py verify --group core\n{comment}\n")

    def test_the_marker_cannot_unestablish_an_established_baseline(self):
        self.establish_baseline()
        self.git("switch", "-q", "-c", "change/r")
        self.packet("r", kind="repository", scope=["spec.md"])
        self.approve("r", "plan.md")
        self.write("spec.md", UNESTABLISHED + "# gone\n")
        self.assertFailed(self.status("--change", "r"), "may not modify established root")

    def test_an_unestablished_baseline_can_still_be_reshaped(self):
        self.git("switch", "-q", "-c", "change/r")
        self.packet("r", kind="repository", scope=["spec.md"])
        self.approve("r", "plan.md")
        self.write("spec.md", UNESTABLISHED + "# Spec\nreshaped\n")
        self.assertNotIn("out-of-scope", self.codes(self.status("--change", "r"), "r"))

    def test_identical_repeated_change_ids_fail(self):
        self.packet("imp", kind="repository")
        self.write("../body.md", "Change-ID: imp\nChange-ID: imp\n")
        result = self.status("--branch=", "--pr-body", str(self.root.parent / "body.md"))
        self.assertFailed(result, "several Change-IDs")

    def test_malformed_config_is_reported_not_raised(self):
        for text in ("{bad", "[]"):
            with self.subTest(text=text):
                self.write("checks.json", text)
                result = self.status()
                self.assertEqual(result["exit"], 1)
                self.assertTrue(any("checks.json" in f for f in result["failures"]), result["failures"])

    def test_a_non_string_baseline_digest_is_reported_not_raised(self):
        self.establish_baseline()
        self.packet("imp", baseline={"intent.md": 7, "spec.md": 7})
        self.assertIn("stale-baseline", self.codes(self.status("--change", "imp"), "imp"))

    def test_an_unhashable_check_id_is_reported_not_raised(self):
        self.write("checks.json", json.dumps({"schema": 1, "checks": [{"id": ["x"]}]}))
        self.assertEqual(self.status()["exit"], 1)

    def test_a_commented_group_line_is_not_a_job(self):
        self.wiring("      # - run: python3 scripts/repo.py verify --group web")
        self.assertFailed(self.status(), "check group 'web' has no")

    def test_a_trailing_comment_is_not_a_job(self):
        self.wiring("      - run: echo hi # python3 scripts/repo.py verify --group web")
        self.assertFailed(self.status(), "check group 'web' has no")


class ScopeBinding(RepoCase):
    def approved(self):
        self.packet("imp", kind="repository", scope=["src/**", "docs/**"])
        self.run_repo("approve", "imp", "plan.md", "--by", "owner")

    def test_widened_scope_is_stale_and_blocked(self):
        self.approved()
        self.set_scope("imp", ["src/**", "docs/**", "**"])
        result = self.status("--change", "imp")
        change = result["by_id"]["imp"]
        self.assertIn("stale-approval", self.codes(result, "imp"))
        self.assertEqual((change["readiness"], change["freshness"]), ("blocked", "stale"))

    def test_reordered_scope_stays_ready(self):
        self.approved()
        self.set_scope("imp", ["docs/**", "src/**"])
        self.assertEqual(self.status("--change", "imp")["by_id"]["imp"]["readiness"], "ready")

    def test_plan_claim_without_scope_binding_blocks_an_open_packet(self):
        self.packet("imp", kind="repository", scope=["src/**"])
        self.approve("imp", "plan.md", bind_scope=False)
        result = self.status("--change", "imp")
        self.assertIn("unbound-scope", self.codes(result, "imp"))
        self.assertEqual(result["by_id"]["imp"]["readiness"], "blocked")

    def test_frozen_packet_without_scope_binding_stays_frozen(self):
        self.packet("imp", kind="repository")
        self.approve("imp", "plan.md", bind_scope=False)
        self.close("imp")
        self.commit("close imp")
        change = self.status()["by_id"]["imp"]
        self.assertEqual((change["closure"], change["freshness"]), ("frozen", "frozen"))
        self.assertNotIn("unbound-scope", self.codes(self.status(), "imp"))


class TextOutput(RepoCase):
    def frozen(self, *ids):
        for cid in ids:
            self.packet(cid, kind="repository")
            self.approve(cid, "plan.md")
            self.close(cid)
        self.commit("close")

    def text(self, *args):
        return self.run_repo("status", *args)

    def test_frozen_packets_fold_into_one_line(self):
        self.frozen("alpha", "beta")
        out = self.text().stdout
        self.assertIn("frozen: 2\n", out)
        self.assertNotIn("alpha", out)
        self.assertNotIn("closure anchor", out)

    def test_active_change_prints_in_full_when_frozen(self):
        self.frozen("alpha", "beta")
        out = self.text("--change", "alpha").stdout
        self.assertIn("* alpha [repository]", out)
        self.assertIn("closure anchor", out)
        self.assertIn("frozen: 1\n", out)

    def test_frozen_packet_with_a_reason_prints_in_full(self):
        sys.path.insert(0, str(REPO_PY.parent))
        import repo  # noqa: E402

        change = {"id": "alpha", "kind": "repository", "stage": "closed", "freshness": "frozen", "approval": "unverified",
                  "readiness": "ready", "closure": "frozen", "closure_anchor": "abc", "artifacts": {},
                  "reasons": [{"level": "warn", "code": "x", "message": "look here"}]}
        result = {"active": None, "identity_errors": [], "changes": [change], "surface": [], "changed_paths": [], "ok": True, "failures": []}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            repo.print_status(result)
        self.assertIn("look here", out.getvalue())
        self.assertNotIn("frozen:", out.getvalue())

    def test_edited_frozen_packet_prints_in_full_and_fails(self):
        self.frozen("alpha")
        self.write("changes/alpha/plan.md", "# edited\n")
        proc = self.text()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("alpha [repository]", proc.stdout)
        self.assertNotIn("frozen: ", proc.stdout)

    def test_no_frozen_line_without_frozen_packets(self):
        self.packet("alpha", kind="repository")
        self.assertNotIn("frozen: ", self.text().stdout)

    def test_json_lists_every_packet(self):
        self.frozen("alpha", "beta")
        self.assertEqual({c["id"] for c in self.status()["changes"]}, {"alpha", "beta"})


class PlaceholderArtifacts(RepoCase):
    def marked(self):
        marked = {"intent.md": UNESTABLISHED + "# Intent\n", "spec.md": UNESTABLISHED + "# Specification\n", "plan.md": "# P\n"}
        self.packet("init", kind="product-init", artifacts=marked)
        self.approve("init", "intent.md", "spec.md", "plan.md")

    def test_hand_written_claim_on_a_marked_artifact_blocks(self):
        self.marked()
        result = self.status("--change", "init")
        self.assertIn("placeholder-artifact", self.codes(result, "init"))
        self.assertEqual(result["by_id"]["init"]["readiness"], "blocked")

    def test_frozen_packet_with_the_marker_stays_frozen(self):
        self.marked()
        self.close("init")
        self.commit("close init")
        result = self.status()
        self.assertEqual(result["by_id"]["init"]["closure"], "frozen")
        self.assertNotIn("placeholder-artifact", self.codes(result, "init"))

    def test_other_kinds_are_unaffected(self):
        self.establish_baseline()
        self.packet("arch", kind="architecture", artifacts={"spec.md": UNESTABLISHED + "# S\n", "plan.md": "# P\n"})
        self.approve("arch", "spec.md", "plan.md")
        self.assertNotIn("placeholder-artifact", self.codes(self.status("--change", "arch"), "arch"))


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
        self.git("switch", "-q", "-c", "change/init")
        self.packet("init", kind="product-init", scope=["intent.md", "spec.md"], artifacts={"intent.md": "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        self.approve("init", "intent.md", "spec.md", "plan.md")
        self.write("intent.md", "# I\n")
        self.write("spec.md", "# S\n")
        self.close("init")
        self.commit("close on the branch")
        result = self.status("--change", "init")
        change = result["by_id"]["init"]
        self.assertEqual((change["stage"], change["closure"], change["readiness"]), ("closed", "candidate", "ready"))
        self.assertTrue(result["ok"], result["failures"])

    def closed_candidate(self):
        self.establish_baseline()
        self.git("switch", "-q", "-c", "change/imp")
        self.packet("imp", kind="repository", scope=["src/**"])
        self.approve("imp", "plan.md")
        self.write("src/a.txt", "x\n")
        self.close("imp")
        self.commit("close imp")

    def test_a_code_commit_after_closure_makes_it_stale(self):
        self.closed_candidate()
        self.assertEqual(self.status("--change", "imp")["by_id"]["imp"]["closure"], "candidate")
        self.write("src/a.txt", "y\n")
        self.commit("edit after closure")
        result = self.status("--change", "imp")
        self.assertEqual(result["by_id"]["imp"]["closure"], "invalid")
        self.assertIn("closure-stale", self.codes(result, "imp"))
        self.assertEqual(result["exit"], 1)

    def test_a_refreshed_closure_is_current_again(self):
        self.closed_candidate()
        self.write("src/a.txt", "y\n")
        self.close("imp")
        self.commit("edit and refresh")
        self.assertEqual(self.status("--change", "imp")["by_id"]["imp"]["closure"], "candidate")

    def test_a_candidate_closure_needs_a_tree_digest(self):
        self.closed_candidate()
        closure = json.loads(self.read("changes/imp/closure.json"))
        del closure["tree_sha256"]
        self.write("changes/imp/closure.json", json.dumps(closure))
        self.assertIn("closure-stale", self.codes(self.status("--change", "imp"), "imp"))

    def test_a_frozen_closure_needs_no_tree_digest(self):
        self.establish_baseline()
        closure = json.loads(self.read("changes/init/closure.json"))
        del closure["tree_sha256"]
        self.git("reset", "-q", "--soft", "HEAD~1")
        self.write("changes/init/closure.json", json.dumps(closure))
        self.commit("close init")
        self.assertEqual(self.status()["by_id"]["init"]["closure"], "frozen")

    def test_an_ignored_packet_file_leaves_the_packet_digest_alone(self):
        self.write(".gitignore", "*.tmp\n")
        self.closed_candidate()
        self.write("changes/imp/scratch.tmp", "x\n")
        self.assertEqual(self.status("--change", "imp")["by_id"]["imp"]["closure"], "candidate")

    def test_a_packet_symlink_digests_the_same_in_the_worktree_and_a_commit(self):
        sys.path.insert(0, str(REPO_PY.parent))
        import repo  # noqa: E402

        self.packet("imp", kind="repository")
        (self.root / "changes/imp/link").symlink_to("plan.md")
        head = self.commit("packet")
        self.assertEqual(repo.worktree_packet(self.root, "imp"), repo.tree_packet(self.root, head, "imp"))

    def test_a_branch_behind_the_baseline_is_told_so(self):
        self.establish_baseline()
        self.git("switch", "-q", "-c", "change/imp")
        self.packet("imp", kind="repository")
        self.approve("imp", "plan.md")
        self.commit("packet")
        self.git("switch", "-q", "main")
        self.packet("other", kind="repository")
        self.approve("other", "plan.md")
        self.close("other")
        self.commit("close other")
        self.git("switch", "-q", "change/imp")
        self.assertFailed(self.status("--change", "imp"), "if this branch is behind the baseline, update it")

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

    def test_deleted_frozen_closure_fails(self):
        self.establish_baseline()
        self.git("switch", "-q", "-c", "change/init")
        self.git("rm", "-q", "changes/init/closure.json")
        self.commit("reopen")
        self.assertFailed(self.status("--change", "init"), "removed from the candidate")
        self.write("pr.md", "Change-ID: init\n")
        self.assertFailed(self.status("--branch=", "--pr-body", "pr.md", "--base", "main", "--head", "HEAD"), "removed from the candidate")

    def test_deleted_frozen_packet_fails_for_another_change(self):
        self.establish_baseline()
        self.git("switch", "-q", "-c", "change/alpha")
        self.packet("alpha", kind="repository", scope=["changes/**"])
        self.approve("alpha", "plan.md")
        self.git("rm", "-rq", "changes/init")
        self.commit("remove init")
        self.assertFailed(self.status("--change", "alpha"), "init: frozen packet removed from the candidate")

    def test_deletion_on_the_baseline_branch_passes(self):
        self.establish_baseline()
        self.git("rm", "-rq", "changes/init")
        self.commit("remove the closed packet")
        self.assertTrue(self.status()["ok"])

    def test_deleted_id_can_be_reused(self):
        self.establish_baseline()
        self.git("rm", "-rq", "changes/init")
        self.commit("remove the closed packet")
        self.git("switch", "-q", "-c", "change/init")
        self.packet("init", kind="repository", scope=["src/**"])
        self.approve("init", "plan.md")
        self.close("init")
        self.commit("reuse the id")
        result = self.status("--change", "init")
        self.assertEqual(result["by_id"]["init"]["closure"], "candidate")
        self.assertTrue(result["ok"], result["failures"])
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--squash", "change/init")
        anchor = self.commit("merge the reused id")
        change = self.status()["by_id"]["init"]
        self.assertEqual((change["closure"], change["closure_anchor"]), ("frozen", anchor))

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

    def test_hook_script_without_exec_bit_is_still_valid(self):
        self.hook_script(executable=False)  # the adapter runs it through python3
        self.settings("python3 scripts/hooks/guard.py claude")
        self.commit("hooks")
        self.assertTrue(self.status()["ok"])

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


class PullRequestGate(RepoCase):
    def setUp(self):
        super().setUp()
        self.git("switch", "-q", "-c", "change/alpha")
        self.packet("alpha", kind="repository", scope=["src/**", "changes/**"])

    def pr(self):
        body = self.root.parent / "body.md"
        body.write_text("Change-ID: alpha\n")
        return self.status("--branch=", "--pr-body", str(body), "--base", "main", "--head", "HEAD")

    def ready(self):
        self.approve("alpha", "plan.md")

    def test_unapproved_packet_fails(self):
        self.commit("draft")
        self.assertFailed(self.pr(), "needs a candidate closure")
        self.assertTrue(self.status("--change", "alpha")["ok"], "local drafting stays allowed")

    def test_approved_packet_without_closure_fails(self):
        self.ready()
        self.commit("approved")
        self.assertFailed(self.pr(), "needs a candidate closure")
        self.assertTrue(self.status("--change", "alpha")["ok"], "local work stays allowed")

    def test_invalid_closure_fails(self):
        self.ready()
        self.close("alpha", packet_sha256="sha256:" + "0" * 64)
        self.commit("closed")
        self.assertFailed(self.pr(), "needs a candidate closure")

    def test_candidate_closure_passes(self):
        self.ready()
        self.close("alpha")
        self.commit("closed")
        result = self.pr()
        self.assertTrue(result["ok"], result["failures"])

    def test_second_packet_fails(self):
        self.ready()
        self.packet("beta", kind="repository")
        self.close("alpha")
        self.commit("two packets")
        self.assertFailed(self.pr(), "touches other packets: ['beta']")

    def test_template_packet_edit_passes(self):
        self.write("changes/_template/plan.md", "# Plan\n")
        self.commit("template")
        self.ready()
        self.close("alpha")
        self.commit("closed")
        result = self.pr()
        self.assertTrue(result["ok"], result["failures"])


if __name__ == "__main__":
    unittest.main()
