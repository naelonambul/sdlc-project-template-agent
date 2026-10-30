"""`repo.py approve` and `repo.py close`: mechanical, order-checked, never an authority."""

import json

from scripts.tests.support import UNESTABLISHED, RepoCase, digest


class Approve(RepoCase):
    def test_records_digest_of_current_bytes(self):
        self.packet("imp", kind="repository", scope=["src/**"])
        proc = self.run_repo("approve", "imp", "plan.md", "--by", "owner", "--note", "reviewed in chat")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("unverified", proc.stdout)
        claims = json.loads(self.read("changes/imp/change.json"))["approvals"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["sha256"], digest(self.read("changes/imp/plan.md")))
        self.assertEqual((claims[0]["artifact"], claims[0]["by"], claims[0]["note"]), ("plan.md", "owner", "reviewed in chat"))
        self.assertRegex(claims[0]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        result = self.status("--change", "imp")
        self.assertEqual((result["by_id"]["imp"]["readiness"], result["by_id"]["imp"]["approval"]), ("ready", "unverified"))

    def test_replaces_stale_claim_for_same_artifact(self):
        self.packet("imp", kind="repository")
        self.approve("imp", "plan.md")
        self.write("changes/imp/plan.md", "# Plan v2\n")
        self.assertIn("stale-approval", self.codes(self.status(), "imp"))
        proc = self.run_repo("approve", "imp", "plan.md", "--by", "owner")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("replaced 1 earlier claim", proc.stdout)
        claims = json.loads(self.read("changes/imp/change.json"))["approvals"]
        self.assertEqual([c["sha256"] for c in claims], [digest("# Plan v2\n")])
        self.assertNotIn("stale-approval", self.codes(self.status(), "imp"))

    def test_plan_claim_binds_write_scope_and_upstream_claims_do_not(self):
        self.packet("init", kind="product-init", scope=["src/**"], artifacts={"intent.md": "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        for name in ("intent.md", "spec.md", "plan.md"):
            proc = self.run_repo("approve", "init", name, "--by", "owner")
            self.assertEqual(proc.returncode, 0, proc.stderr)
        claims = {c["artifact"]: c for c in json.loads(self.read("changes/init/change.json"))["approvals"]}
        self.assertNotIn("write_scope_sha256", claims["intent.md"])
        self.assertNotIn("write_scope_sha256", claims["spec.md"])
        self.assertRegex(claims["plan.md"]["write_scope_sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_reapproval_rebinds_a_changed_scope_without_an_artifact_edit(self):
        self.packet("imp", kind="repository", scope=["src/**"])
        self.run_repo("approve", "imp", "plan.md", "--by", "owner")
        self.set_scope("imp", ["src/**", "docs/**"])
        self.assertIn("stale-approval", self.codes(self.status(), "imp"))
        proc = self.run_repo("approve", "imp", "plan.md", "--by", "owner")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.status("--change", "imp")["by_id"]["imp"]["readiness"], "ready")

    def test_refuses_out_of_order(self):
        self.packet("init", kind="product-init", artifacts={"intent.md": "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        proc = self.run_repo("approve", "init", "plan.md", "--by", "owner")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("approve intent.md before plan.md", proc.stderr)
        self.assertEqual(json.loads(self.read("changes/init/change.json"))["approvals"], [])
        for name in ("intent.md", "spec.md", "plan.md"):
            self.assertEqual(self.run_repo("approve", "init", name, "--by", "owner").returncode, 0)
        self.assertEqual(self.status()["by_id"]["init"]["stage"], "implementation")

    def test_refuses_artifact_outside_chain_or_missing(self):
        self.packet("imp", kind="repository")
        proc = self.run_repo("approve", "imp", "spec.md", "--by", "owner")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not in the chain", proc.stderr)
        self.packet("beh", kind="behavior", artifacts={"plan.md": "# P\n"})
        self.establish_baseline()
        proc = self.run_repo("approve", "beh", "spec.md", "--by", "owner")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("does not exist yet", proc.stderr)

    def test_refuses_blank_approver_unknown_packet_and_closed_change(self):
        self.packet("imp", kind="repository")
        self.assertIn("--by must name", self.run_repo("approve", "imp", "plan.md", "--by", "  ").stderr)
        self.assertIn("not found", self.run_repo("approve", "nope", "plan.md", "--by", "owner").stderr)
        self.approve("imp", "plan.md")
        self.close("imp")
        proc = self.run_repo("approve", "imp", "plan.md", "--by", "owner")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("already has a closure", proc.stderr)


class PlaceholderProductInit(RepoCase):
    def test_refuses_artifacts_that_keep_the_marker(self):
        self.packet("init", kind="product-init", artifacts={"intent.md": UNESTABLISHED + "# I\n", "spec.md": "# S\n", "plan.md": "# P\n"})
        proc = self.run_repo("approve", "init", "intent.md", "--by", "owner")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unestablished marker", proc.stderr)
        self.write("changes/init/intent.md", "# I\n")
        self.assertEqual(self.run_repo("approve", "init", "intent.md", "--by", "owner").returncode, 0)
        self.write("changes/init/spec.md", UNESTABLISHED + "# S\n")
        proc = self.run_repo("approve", "init", "spec.md", "--by", "owner")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unestablished marker", proc.stderr)


class Close(RepoCase):
    def ready_repository_change(self):
        self.packet("imp", kind="repository", scope=["src/**"])
        self.approve("imp", "plan.md")
        self.commit("packet")

    def test_writes_candidate_closure(self):
        self.write(".gitignore", ".evidence/\n")
        self.ready_repository_change()
        ref = self.verify_evidence("imp")
        evidence_text = self.read(ref)
        proc = self.run_repo("close", "imp", "--evidence", ref, "--evidence", "review: none needed")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        closure = json.loads(self.read("changes/imp/closure.json"))
        self.assertEqual(closure["baseline"], {})
        self.assertEqual(closure["evidence"], [".evidence/run/evidence.json " + digest(evidence_text), "review: none needed"])
        self.assertEqual(set(closure), {"schema", "baseline", "packet_sha256", "evidence"})
        result = self.status("--change", "imp")
        self.assertEqual((result["by_id"]["imp"]["stage"], result["by_id"]["imp"]["closure"]), ("closed", "candidate"))
        self.assertTrue(result["ok"], result["failures"])

    def test_requires_evidence(self):
        self.ready_repository_change()
        proc = self.run_repo("close", "imp")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--evidence is required", proc.stderr)
        self.assertFalse((self.root / "changes/imp/closure.json").exists())

    def test_refuses_before_approval(self):
        self.packet("imp", kind="repository")
        proc = self.run_repo("close", "imp", "--evidence", "x")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not ready to close", proc.stderr)

    def test_refuses_until_carried_artifact_is_merged_into_root(self):
        self.establish_baseline()
        self.packet("beh", kind="behavior", artifacts={"spec.md": "# Spec\nv2\n", "plan.md": "# P\n"})
        self.approve("beh", "spec.md", "plan.md")
        proc = self.run_repo("close", "beh", "--evidence", "local verify")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cp changes/beh/spec.md spec.md", proc.stderr)
        self.write("spec.md", "# Spec\nv2\n")
        proc = self.run_repo("close", "beh", "--evidence", self.verify_evidence("beh"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        closure = json.loads(self.read("changes/beh/closure.json"))
        self.assertEqual(closure["baseline"], {"spec.md": digest("# Spec\nv2\n")})
        self.assertEqual(self.status("--change", "beh")["by_id"]["beh"]["closure"], "candidate")

    def test_refuses_frozen_change(self):
        self.establish_baseline()
        before = self.read("changes/init/closure.json")
        proc = self.run_repo("close", "init", "--evidence", "late")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("already closed on 'main'", proc.stderr)
        self.assertEqual(self.read("changes/init/closure.json"), before)
        self.assertEqual(self.status()["by_id"]["init"]["closure"], "frozen")

    def assertEvidenceRefused(self, fragment, ref):
        proc = self.run_repo("close", "imp", "--evidence", ref)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn(fragment, proc.stderr)
        self.assertFalse((self.root / "changes/imp/closure.json").exists())

    def test_refuses_free_text_and_missing_evidence_files(self):
        self.ready_repository_change()
        self.assertEvidenceRefused("repo.py verify", "made-up-ref")
        self.assertEvidenceRefused("repo.py verify", ".evidence/none/evidence.json")

    def test_refuses_evidence_that_is_not_a_json_object(self):
        self.ready_repository_change()
        self.write(".evidence/a.json", "not json\n")
        self.assertEvidenceRefused("not JSON", ".evidence/a.json")
        self.write(".evidence/b.json", "[]\n")
        self.assertEvidenceRefused("not JSON", ".evidence/b.json")

    def test_refuses_evidence_of_another_change_or_commit(self):
        self.ready_repository_change()
        self.assertEvidenceRefused("verify --change imp", self.verify_evidence("other"))
        self.assertEvidenceRefused("verify --change imp", self.verify_evidence(None))
        self.assertEvidenceRefused("not HEAD", self.verify_evidence("imp", source={"commit": "0" * 40, "dirty": False}))

    def test_refuses_incomplete_or_failing_evidence(self):
        self.ready_repository_change()
        self.assertEvidenceRefused("incomplete", self.verify_evidence("imp", complete=False))
        for status in ("failed", "blocked"):
            ref = self.verify_evidence("imp", checks=[{"id": "check", "status": status}])
            self.assertEvidenceRefused(status, ref)

    def test_free_text_is_kept_beside_a_valid_run(self):
        self.ready_repository_change()
        ref = self.verify_evidence("imp")
        proc = self.run_repo("close", "imp", "--evidence", "ci link", "--evidence", ref)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(self.read("changes/imp/closure.json"))["evidence"][0], "ci link")

    def test_rewrite_refreshes_evidence_and_keeps_packet_digest(self):
        self.ready_repository_change()
        run_1, run_2 = self.verify_evidence("imp", "run-1.json"), self.verify_evidence("imp", "run-2.json")
        self.assertEqual(self.run_repo("close", "imp", "--evidence", run_1).returncode, 0)
        first = json.loads(self.read("changes/imp/closure.json"))
        proc = self.run_repo("close", "imp", "--evidence", run_2)
        self.assertIn("rewrote", proc.stdout)
        second = json.loads(self.read("changes/imp/closure.json"))
        self.assertEqual((first["packet_sha256"], second["evidence"]), (second["packet_sha256"], [f"{run_2} {digest(self.read(run_2))}"]))
