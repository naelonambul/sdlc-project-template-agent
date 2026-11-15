from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.tests.support import GIT_ENV, REPO_PY, RepoCase, checks_json

PROJECT = REPO_PY.parents[1]
MIGRATIONS = ".agents/skills/template-upgrade/references/migrations.md"
BASELINE_ERRORS = {
    "adapter-broken", "artifact-not-allowed", "baseline-established", "baseline-unestablished", "checks-invalid",
    "checks-unwired", "diff-base", "hook-broken", "instruction-shadowed", "instructions-missing", "invalid-approval",
    "invalid-change", "missing-upstream", "not-ready", "out-of-order", "out-of-scope", "placeholder-artifact",
    "scope-path-escape", "stale-approval", "stale-baseline", "unbound-scope",
}


def lists_source(skills, merge, version) -> str:
    return f"UPGRADE_SKILLS = {tuple(skills)!r}\nUPGRADE_MERGE = {tuple(merge)!r}\nVERSION = {version!r}\n"


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def expected_digest(entries: dict) -> str:
    lines = "".join(f"{path}\0{mode}\0{blob}\n" for path, (mode, blob) in sorted(entries.items()))
    return "sha256:" + hashlib.sha256(lines.encode()).hexdigest()


def snapshot(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            out[rel] = ("link", os.readlink(path))
        elif path.is_file():
            out[rel] = (os.access(path, os.X_OK), path.read_bytes())
    return out


class Template:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.commits = {}

    def git(self, *args) -> str:
        proc = subprocess.run(["git", *args], cwd=self.root, env={**os.environ, **GIT_ENV}, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"git {args}: {proc.stderr}")
        return proc.stdout.strip()

    def write(self, rel: str, text: str, executable: bool = False):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755 if executable else 0o644)

    def link(self, rel: str, target: str):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)

    def remove(self, rel: str):
        (self.root / rel).unlink()

    def commit(self, name: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", name)
        self.commits[name] = self.git("rev-parse", "HEAD")
        return self.commits[name]


def build_template(root: Path) -> Template:
    t = Template(root)
    t.write("changes/mig-old/change.json", "{}\n")
    t.write("scripts/repo.py", "VERSION = 'v0'\n")
    t.commit("c0")
    t.write("scripts/repo.py", lists_source(["sdlc-artifacts"], ["AGENTS.md", "checks.json"], "v1"))
    t.write("scripts/tests/test_a.py", "a1\n")
    t.write("scripts/tests/gone.py", "gone\n")
    t.write("scripts/hooks/guard.py", "g1\n")
    t.write("changes/README.md", "r1\n")
    t.write(".agents/skills/sdlc-artifacts/SKILL.md", "s1\n")
    t.link(".claude/skills/sdlc-artifacts", "../../.agents/skills/sdlc-artifacts")
    t.write("AGENTS.md", "agents1\n")
    t.write("checks.json", checks_json())
    t.write("README.md", "template readme\n")
    t.commit("c1")
    t.write("changes/mig-one/change.json", "{}\n")
    t.write("scripts/tests/test_a.py", "a2\n")
    t.commit("c2")
    skills = ["sdlc-artifacts", "template-upgrade"]
    t.write("scripts/repo.py", lists_source(skills, ["AGENTS.md", "checks.json"], "v3"))
    t.write("changes/mig-two/change.json", "{}\n")
    t.write(MIGRATIONS, "# Template migrations\n\n## mig-old\n\nold\n\n## mig-two\n\ntwo\n\n## mig-one\n\none\n")
    t.write(".agents/skills/template-upgrade/SKILL.md", "u1\n")
    t.link(".claude/skills/template-upgrade", "../../.agents/skills/template-upgrade")
    t.write("scripts/hooks/guard.py", "g1\n", executable=True)
    t.remove("scripts/tests/gone.py")
    t.write("AGENTS.md", "agents3\n")
    t.write("README.md", "template readme 3\n")
    t.commit("c3")
    return t


class Upgrade(RepoCase):
    def setUp(self):
        super().setUp()
        self.template = build_template(Path(self._tmp.name) / "template")
        self.c = self.template.commits
        self.install("c1")
        self.write("scripts/tests/test_local.py", "mine\n")
        self.commit("adopt c1")

    def install(self, name: str):
        commit = self.c[name]
        listing = self.template.git("ls-tree", "-r", commit, "--", "scripts", "changes/README.md", ".agents", ".claude")
        for line in listing.splitlines():
            meta, rel = line.split("\t", 1)
            mode = meta.split()[0]
            data = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=self.template.root, capture_output=True, check=True).stdout
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.exists():
                path.unlink()
            if mode == "120000":
                path.symlink_to(data.decode())
            else:
                path.write_bytes(data)
                path.chmod(0o755 if mode == "100755" else 0o644)

    def upgrade(self, *args):
        return self.run_repo("upgrade", "--template", str(self.template.root), *args)

    def report(self, *args) -> str:
        proc = self.upgrade(*args)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def lines(self, out: str, name: str) -> list[str]:
        block = re.search(rf"(?m)^{name}: .*\n((?:  .*\n)*)", out)
        self.assertIsNotNone(block, out)
        return [line.strip() for line in block.group(1).splitlines()]

    def test_verified_base_reports_every_section(self):
        out = self.report("--to", self.c["c3"], "--from", self.c["c1"])
        self.assertIn(f"base:   {self.c['c1']}  7 of 7 template-owned copy files match", out)
        self.assertIn("drift: none", out)
        self.assertEqual(self.lines(out, "copy"), [
            "added    .agents/skills/template-upgrade/SKILL.md",
            "added    .agents/skills/template-upgrade/references/migrations.md",
            "added    .claude/skills/template-upgrade",
            "changed  scripts/hooks/guard.py (mode 100644 -> 100755)",
            "changed  scripts/repo.py",
            "removed  scripts/tests/gone.py",
            "changed  scripts/tests/test_a.py",
        ])
        merge = self.lines(out, "merge")
        self.assertTrue(merge[0].startswith("AGENTS.md: git -C "), merge)
        self.assertIn(f"diff {self.c['c1']} {self.c['c3']} -- AGENTS.md", merge[0])
        self.assertTrue(merge[1].startswith("git merge-file -p AGENTS.md "), merge)
        self.assertEqual(len(merge), 2, merge)
        self.assertEqual(self.lines(out, "local"), ["scripts/tests/test_local.py"])
        self.assertNotIn("README.md", "\n".join(self.lines(out, "copy") + merge))

    def test_migrations_are_those_merged_after_the_base_in_merge_order(self):
        out = self.report("--to", self.c["c3"], "--from", self.c["c1"])
        names = [line.split()[0] for line in self.lines(out, "migrations")]
        self.assertEqual(names, ["mig-one", "mig-two"])

    def test_a_later_base_skips_earlier_migrations(self):
        out = self.report("--to", self.c["c3"], "--from", self.c["c2"])
        self.assertEqual([line.split()[0] for line in self.lines(out, "migrations")], ["mig-two"])

    def test_the_pin_is_the_default_base(self):
        self.write_checks(template={"commit": self.c["c1"], "digest": "sha256:" + "0" * 64})
        self.commit("pin")
        out = self.report("--to", self.c["c3"])
        self.assertIn(f"base:   {self.c['c1']}", out)

    def test_without_a_base_it_lists_candidates_and_stops(self):
        proc = self.upgrade("--to", self.c["c3"])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("pass --from", proc.stdout)
        candidates = [line.split()[0] for line in proc.stdout.splitlines()[1:]]
        self.assertEqual(candidates[0], self.c["c1"], proc.stdout)
        self.assertNotIn(self.c["c3"], candidates)

    def test_drift_is_reported_and_carried_gets_a_merge_recipe(self):
        self.write("scripts/tests/test_a.py", "a1 local\n")
        (self.root / "scripts/hooks/guard.py").unlink()
        out = self.report("--to", self.c["c3"], "--from", self.c["c1"])
        self.assertEqual(self.lines(out, "drift"), ["scripts/hooks/guard.py: missing", "scripts/tests/test_a.py: differs from the base"])
        self.write_checks(template={"commit": self.c["c1"], "digest": "sha256:" + "0" * 64, "carried": ["scripts/tests/test_a.py"]})
        out = self.report("--to", self.c["c3"])
        self.assertEqual(self.lines(out, "drift"), ["scripts/hooks/guard.py: missing"])
        carried = self.lines(out, "carried")
        self.assertEqual(len(carried), 1)
        self.assertTrue(carried[0].startswith("scripts/tests/test_a.py: git merge-file -p scripts/tests/test_a.py "), carried)
        self.assertNotIn("test_a.py", "\n".join(self.lines(out, "copy")))
        self.assertIn('"carried": ["scripts/tests/test_a.py"]', out)

    def test_a_base_that_is_not_an_ancestor_is_refused(self):
        self.template.git("switch", "-q", "-c", "side", self.c["c0"])
        self.template.write("scripts/repo.py", lists_source(["sdlc-artifacts"], ["AGENTS.md"], "side"))
        side = self.template.commit("side")
        proc = self.upgrade("--to", self.c["c3"], "--from", side)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("is not an ancestor of target", proc.stderr)

    def test_bad_inputs_exit_one(self):
        missing = self.run_repo("upgrade", "--template", str(self.root.parent / "nowhere"), "--to", "main")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("is not a Git clone", missing.stderr)
        unknown = self.upgrade("--to", "no-such-ref", "--from", self.c["c1"])
        self.assertEqual(unknown.returncode, 1)
        self.assertIn("'no-such-ref' is not a commit", unknown.stderr)
        old = self.upgrade("--to", self.c["c0"], "--from", self.c["c0"])
        self.assertEqual(old.returncode, 1)
        self.assertIn("predates upgrade support", old.stderr)

    def test_the_report_writes_nothing(self):
        self.write("scripts/tests/test_a.py", "dirty\n")
        self.write("untracked.txt", "x\n")
        before = (snapshot(self.root), snapshot(self.template.root))
        self.report("--to", self.c["c3"], "--from", self.c["c1"])
        self.upgrade("--to", self.c["c3"])
        self.assertEqual((snapshot(self.root), snapshot(self.template.root)), before)

    def drift(self) -> list:
        return [r for r in self.status()["surface"] if r["code"] == "template-drift"]

    def test_the_printed_pin_is_what_status_accepts_after_applying(self):
        out = self.report("--to", self.c["c3"], "--from", self.c["c1"])
        pin = json.loads(re.search(r'"template": (\{.*\})', out).group(1))
        self.assertEqual(pin["commit"], self.c["c3"])
        self.install("c3")
        (self.root / "scripts/tests/gone.py").unlink()
        self.write_checks(template=pin)
        self.commit("apply c3")
        installed = {}
        for rel in self.git("ls-files").splitlines():
            if rel.startswith(("scripts/", ".agents/skills/", ".claude/skills/", "changes/README.md")):
                path = self.root / rel
                data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
                mode = "120000" if path.is_symlink() else ("100755" if os.access(path, os.X_OK) else "100644")
                installed[rel] = (mode, blob_id(data))
        self.assertEqual(sorted(installed), sorted([
            ".agents/skills/sdlc-artifacts/SKILL.md", ".agents/skills/template-upgrade/SKILL.md", MIGRATIONS,
            ".claude/skills/sdlc-artifacts", ".claude/skills/template-upgrade", "changes/README.md",
            "scripts/hooks/guard.py", "scripts/repo.py", "scripts/tests/test_a.py", "scripts/tests/test_local.py",
        ]))
        self.assertEqual(pin["digest"], expected_digest(installed))
        self.assertEqual(self.drift(), [])
        self.write("scripts/tests/test_a.py", "edited\n")
        self.assertEqual(len(self.drift()), 1)
        self.assertIn(f"--to {self.c['c3']}", self.drift()[0]["message"])
        self.write_checks(template={**pin, "carried": ["scripts/tests/test_a.py"]})
        self.assertEqual(len(self.drift()), 1)
        self.write_checks(template={**pin, "carried": ["scripts/tests/test_a.py"], "digest": expected_digest(
            {k: v for k, v in installed.items() if k != "scripts/tests/test_a.py"})})
        self.assertEqual(self.drift(), [])
        os.chmod(self.root / "scripts/hooks/guard.py", 0o644)
        self.assertEqual(len(self.drift()), 1)


class Completeness(unittest.TestCase):
    def tracked(self) -> set:
        return set(subprocess.run(["git", "ls-files", "-z"], cwd=PROJECT, capture_output=True, text=True, check=True).stdout.split("\0"))

    def test_every_listed_path_exists_in_the_template(self):
        from scripts import repo
        tracked = self.tracked()
        for entry in repo.UPGRADE_COPY + repo.UPGRADE_MERGE:
            present = entry in tracked or (entry.endswith("/") and any(p.startswith(entry) for p in tracked))
            self.assertTrue(present, f"{entry} is listed for upgrades but not tracked")

    def test_every_new_status_error_has_a_migration_entry(self):
        source = REPO_PY.read_text()
        codes = set(re.findall(r'(?:Reason\(|\.add\()\s*"error",\s*"([a-z-]+)"', source))
        self.assertIn("checks-invalid", codes, "the error-code scan found nothing; fix its pattern")
        text = (PROJECT / MIGRATIONS).read_text()
        missing = sorted(code for code in codes - BASELINE_ERRORS if f"`{code}`" not in text)
        self.assertEqual(missing, [], f"add a section to {MIGRATIONS} naming each new status error")

    def test_every_migration_heading_names_a_change_packet(self):
        text = (PROJECT / MIGRATIONS).read_text()
        ids = re.findall(r"(?m)^## (\S+)\s*$", text)
        self.assertGreater(len(ids), 0)
        for cid in ids:
            self.assertTrue((PROJECT / "changes" / cid / "change.json").is_file(), f"{MIGRATIONS}: ## {cid} names no changes/{cid}/")


if __name__ == "__main__":
    unittest.main()
