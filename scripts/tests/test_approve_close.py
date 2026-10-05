"""`repo.py approve` and `repo.py close`: mechanical, order-checked, never an authority."""

import json

from scripts.tests.support import RepoCase, digest


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


class Close(RepoCase):
    def ready_repository_change(self):
        self.packet("imp", kind="repository", scope=["src/**"])
        self.approve("imp", "plan.md")
        self.commit("packet")

    def test_writes_candidate_closure(self):
        self.write(".gitignore", ".evidence/\n")
        self.ready_repository_change()
        evidence_text = "{}\n"
        self.write(".evidence/run/evidence.json", evidence_text)
        proc = self.run_repo("close", "imp", "--evidence", ".evidence/run/evidence.json", "--evidence", "review: none needed")
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
        proc = self.run_repo("close", "beh", "--evidence", "local verify")
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

    def test_rewrite_refreshes_evidence_and_keeps_packet_digest(self):
        self.ready_repository_change()
        self.assertEqual(self.run_repo("close", "imp", "--evidence", "run 1").returncode, 0)
        first = json.loads(self.read("changes/imp/closure.json"))
        proc = self.run_repo("close", "imp", "--evidence", "run 2")
        self.assertIn("rewrote", proc.stdout)
        second = json.loads(self.read("changes/imp/closure.json"))
        self.assertEqual((first["packet_sha256"], second["evidence"]), (second["packet_sha256"], ["run 2"]))
