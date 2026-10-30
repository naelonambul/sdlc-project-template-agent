"""Throwaway git repositories for control-plane fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_PY = Path(__file__).resolve().parents[1] / "repo.py"
UNESTABLISHED = "<!-- sdlc:baseline-unestablished -->\n"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def digest(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


class RepoCase(unittest.TestCase):
    """Each test gets a fresh repository on `main` with an initial commit."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write("AGENTS.md", "# Repository Agent Instructions\n")
        self.write("intent.md", UNESTABLISHED + "# Intent\n")
        self.write("spec.md", UNESTABLISHED + "# Specification\n")
        self.commit("initial")

    def tearDown(self):
        self._tmp.cleanup()

    # -- git / files ---------------------------------------------------------

    def git(self, *args, cwd=None) -> str:
        env = {**os.environ, **GIT_ENV}
        proc = subprocess.run(["git", *args], cwd=cwd or self.root, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"git {args} failed: {proc.stderr}")
        return proc.stdout.strip()

    def write(self, rel: str, text: str):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    # -- change packets --------------------------------------------------------

    def packet(self, cid, kind="implementation", scope=(), baseline=None, approvals=(), artifacts=None, **extra):
        artifacts = artifacts if artifacts is not None else {"plan.md": f"# Plan for {cid}\n"}
        for name, text in artifacts.items():
            self.write(f"changes/{cid}/{name}", text)
        if baseline is None and kind not in ("product-init", "repository"):
            baseline = {n: digest(self.read(n)) for n in ("intent.md", "spec.md")}
        data = {
            "schema": 1,
            "id": cid,
            "kind": kind,
            "base": {"ref": "main", "commit": ""},
            "baseline": baseline or {},
            "write_scope": list(scope),
            "approvals": list(approvals),
            **extra,
        }
        self.write(f"changes/{cid}/change.json", json.dumps(data, indent=2) + "\n")

    def set_scope(self, cid, scope):
        path = self.root / "changes" / cid / "change.json"
        data = json.loads(path.read_text())
        data["write_scope"] = list(scope)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def approve(self, cid, *names, at="2026-09-23T10:00:{:02d}Z", by="owner", bind_scope=True):
        path = self.root / "changes" / cid / "change.json"
        data = json.loads(path.read_text())
        for i, name in enumerate(names):
            claim = {"artifact": name, "sha256": digest(self.read(f"changes/{cid}/{name}")), "by": by, "at": at.format(i)}
            if name == "plan.md" and bind_scope:
                claim["write_scope_sha256"] = digest(json.dumps(sorted(data["write_scope"]), separators=(",", ":")))
            data["approvals"].append(claim)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def establish_baseline(self):
        """Close a product-init change so root intent/spec are established."""
        self.packet(
            "init",
            kind="product-init",
            artifacts={"intent.md": "# Intent\nreal\n", "spec.md": "# Spec\nreal\n", "plan.md": "# Plan\n"},
        )
        self.approve("init", "intent.md", "spec.md", "plan.md")
        self.write("intent.md", "# Intent\nreal\n")
        self.write("spec.md", "# Spec\nreal\n")
        self.close("init")
        return self.commit("close init")

    def close(self, cid, evidence=("ci run 1",), **override):
        sys.path.insert(0, str(REPO_PY.parent))
        import repo  # noqa: E402

        files = repo.worktree_packet(self.root, cid)
        carried = [n for n in ("intent.md", "spec.md") if n in files]
        data = {
            "schema": 1,
            "baseline": {n: digest(self.read(n)) for n in carried},
            "packet_sha256": repo.packet_digest(files),
            "evidence": list(evidence),
            **override,
        }
        self.write(f"changes/{cid}/closure.json", json.dumps(data, indent=2) + "\n")

    def verify_evidence(self, cid, rel=".evidence/run/evidence.json", **override):
        sys.path.insert(0, str(REPO_PY.parent))
        import repo  # noqa: E402

        tree = repo.candidate_digest(self.root, cid)
        data = {
            "schema": 1,
            "source": {"commit": self.git("rev-parse", "HEAD"), "dirty": True, "tree_sha256": tree},
            "change": cid,
            "complete": True,
            "checks": [{"id": "check", "status": "passed"}],
            **override,
        }
        self.write(rel, json.dumps(data, indent=2) + "\n")
        return rel

    # -- running repo.py -------------------------------------------------------

    def run_repo(self, *args, cwd=None):
        proc = subprocess.run(
            [sys.executable, str(REPO_PY), *args],
            cwd=cwd or self.root,
            env={**os.environ, **GIT_ENV},
            capture_output=True,
            text=True,
        )
        return proc

    def status(self, *args, cwd=None):
        proc = self.run_repo("status", "--json", "--ci", *args, cwd=cwd)
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise AssertionError(f"no JSON from repo.py (exit {proc.returncode}): {proc.stdout}{proc.stderr}")
        result["exit"] = proc.returncode
        result["by_id"] = {c["id"]: c for c in result["changes"]}
        return result

    def codes(self, result, cid):
        return {r["code"] for r in result["by_id"][cid]["reasons"]}

    def assertFailed(self, result, fragment):
        self.assertEqual(result["exit"], 1, result)
        self.assertTrue(any(fragment in f for f in result["failures"]), result["failures"])
