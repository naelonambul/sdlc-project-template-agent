"""Invariants of the repository's own CI workflow (plain text; no YAML dependency)."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/repository.yml"


# The only lines the control-plane-tests job may contain, after comments are removed. Anything else
# (a quoted key, if, continue-on-error, env, shell, a continuation line, a block scalar) could change
# what runs or mute a failure in a way this plain-text check cannot read, so it is refused.
JOB_LINES = [
    ("job", re.compile(r"    runs-on: ubuntu-latest")),
    ("job", re.compile(r"    timeout-minutes: \d+")),
    ("job", re.compile(r"    steps:")),
    ("uses", re.compile(r"      - uses: [\w.-]+/[\w.-]+@[0-9a-f]{40}")),
    ("with", re.compile(r"        with:")),
    ("input", re.compile(r"          [a-z][a-z0-9-]*: \S.*")),
    ("run", re.compile(r"      - run: ([^\s|>'\"].*)")),
]
TOP_LEVEL_ENV = {"REPO_ARGS", "VERIFY_ARGS"}


def control_plane_job_findings(text: str, argv: list[str]) -> list[str]:
    """Why the control-plane-tests job could pass without running the tests outside repo.py, or []."""
    findings = []
    if re.search(r"(?m)^defaults:", text):
        findings.append("top-level defaults: can change the shell of every run step")
    env = re.search(r"(?ms)^env:\n(.*?)(?=^\S)", text)
    env_keys = set(re.findall(r"(?m)^  ([A-Za-z_][A-Za-z0-9_]*):", env.group(1))) if env else set()
    if env_keys != TOP_LEVEL_ENV:
        findings.append(f"top-level env keys {sorted(env_keys)} != {sorted(TOP_LEVEL_ENV)}")
    match = re.search(r"(?ms)^  control-plane-tests:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", text)
    if not match:
        return findings + ["no control-plane-tests job"]
    runs, previous = [], None
    for line in match.group(1).splitlines():
        line = re.sub(r"\s+#.*$", "", line).rstrip()
        if not line:
            continue
        kind = next((k for k, pattern in JOB_LINES if pattern.fullmatch(line)), None)
        if kind == "with" and previous not in ("uses", "input"):
            kind = None
        if kind == "input" and previous not in ("with", "input"):
            kind = None
        if kind is None:
            findings.append(f"unexpected line in control-plane-tests: {line.strip()}")
            continue
        if kind == "run":
            runs.append(JOB_LINES[-1][1].fullmatch(line).group(1))
        previous = kind
    expected = ["python3 -m unittest scripts.tests.test_run", " ".join(argv)]
    if runs != expected:
        findings.append(f"run steps {runs} != {expected}")
    findings += [f"run step uses repo.py: {r}" for r in runs if "repo.py" in r]
    return findings


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

    def test_control_plane_job_runs_the_registered_command_without_repo_py(self):
        """The job's pass/fail must not depend on repo.py verify: fixed commands, and no way to mute a failure."""
        argv = json.loads((ROOT / "checks.json").read_text())["checks"]
        argv = next(c for c in argv if c["id"] == "control-plane")["argv"]
        self.assertEqual(control_plane_job_findings(self.text, argv), [])
        runner, unit = " ".join(argv), "python3 -m unittest scripts.tests.test_run"
        mutations = {
            "muted with || true": (f"run: {runner}", f"run: {runner} || true"),
            "echoed": (f"run: {runner}", f"run: echo {runner}"),
            "runner's own tests dropped": (f"      - run: {unit}\n", ""),
            "step if": (f"      - run: {runner}", f"      - if: false\n        run: {runner}"),
            "continue-on-error": (f"      - run: {runner}", f"      - continue-on-error: true\n        run: {runner}"),
            "through repo.py": (f"run: {runner}", "run: python3 scripts/repo.py verify --group core"),
            "continuation line": (f"      - run: {runner}\n", f"      - run: {runner}\n          || true\n"),
            "block scalar": (f"      - run: {runner}\n", f"      - run: |\n          {runner} || true\n"),
            "quoted if": (f"      - run: {runner}", f'      - "if": false\n        run: {runner}'),
            "quoted continue-on-error": (f"      - run: {runner}", f'      - "continue-on-error": true\n        run: {runner}'),
            "shell": (f"      - run: {runner}", f"      - shell: bash\n        run: {runner}"),
            "job env": ("    timeout-minutes: 15\n    steps:", "    timeout-minutes: 15\n    env:\n      SDLC_TEST_JOBS: 1\n    steps:"),
            "top-level defaults": ("\njobs:\n", "\ndefaults:\n  run:\n    shell: bash -c 'exit 0' {0}\n\njobs:\n"),
            "extra top-level env": ("\nenv:\n", "\nenv:\n  PYTHONPATH: /tmp/evil\n"),
        }
        for name, (old, new) in mutations.items():
            with self.subTest(name):
                self.assertEqual(self.text.count(old), 1, old)
                self.assertNotEqual(control_plane_job_findings(self.text.replace(old, new), argv), [])
        with self.subTest("checks.json argv no longer matches"):
            self.assertNotEqual(control_plane_job_findings(self.text, ["python3", "scripts/tests/other.py"]), [])

    def test_every_check_group_is_run(self):
        groups = {c.get("group", "core") for c in json.loads((ROOT / "checks.json").read_text())["checks"]}
        wired = set(re.findall(r"repo\.py verify --group (\S+)", self.text))
        self.assertEqual(groups, wired)


if __name__ == "__main__":
    unittest.main()
