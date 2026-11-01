"""Invariants of the repository's own CI workflow (plain text; no YAML dependency)."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/repository.yml"


@unittest.skipUnless(WORKFLOW.is_file(), "repository has no CI workflow")
class WorkflowInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()
        on = cls.text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        cls.triggers = on
        jobs = cls.text.split("\njobs:\n", 1)[1]
        cls.jobs = re.findall(r"(?m)^  ([a-z0-9-]+):\n", jobs)

    def test_no_path_filters(self):
        self.assertNotRegex(self.triggers, r"paths(-ignore)?:")
        self.assertNotRegex(self.triggers, r"branches-ignore:")

    def test_pull_request_types_include_edited(self):
        types = re.search(r"types:\s*\[([^\]]*)\]", self.triggers).group(1)
        self.assertTrue({"opened", "reopened", "synchronize", "edited"} <= {t.strip() for t in types.split(",")})

    def test_actions_are_pinned_to_commit_shas(self):
        uses = re.findall(r"uses:\s*(\S+)", self.text)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", ref)

    def test_every_checkout_fetches_full_history(self):
        checkouts = self.text.count("uses: actions/checkout@")
        self.assertEqual(checkouts, len(re.findall(r"fetch-depth:\s*0\b", self.text)))

    def test_concurrency_cancels_superseded_runs(self):
        self.assertRegex(self.text, r"(?m)^concurrency:\n(?:  .*\n)*  cancel-in-progress: true")

    def test_no_job_is_skipped_by_condition(self):
        # Job-level `if:` would turn "not applicable" into a provider skip; only the summary may use always().
        job_ifs = re.findall(r"(?m)^    if: (.*)$", self.text)
        self.assertEqual(job_ifs, ["always()"])

    def test_summary_needs_every_job_and_requires_success(self):
        needs = re.search(r"(?m)^  summary:\n(?:    .*\n)*?    needs: \[([^\]]*)\]", self.text).group(1)
        self.assertEqual({n.strip() for n in needs.split(",")}, set(self.jobs) - {"summary"})
        self.assertIn('v["result"] == "success"', self.text)

    def test_identity_job_compares_the_author_with_the_variable(self):
        self.assertIn("identity", self.jobs)
        self.assertIn("AGENT_LOGIN: ${{ vars.AGENT_LOGIN }}", self.text)
        self.assertIn("PR_AUTHOR: ${{ github.event.pull_request.user.login }}", self.text)
        self.assertIn('[ "$PR_AUTHOR" != "$AGENT_LOGIN" ]', self.text)

    def test_every_check_group_is_run(self):
        groups = {c.get("group", "core") for c in json.loads((ROOT / "checks.json").read_text())["checks"]}
        wired = set(re.findall(r"repo\.py verify --group (\S+)", self.text))
        self.assertEqual(groups, wired)


if __name__ == "__main__":
    unittest.main()
