"""Throwaway git repositories for control-plane fixtures."""

from __future__ import annotations

import atexit
import hashlib
import importlib.util
import io
import json
import locale
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest import mock

REPO_PY = Path(__file__).resolve().parents[1] / "repo.py"
UNESTABLISHED = "<!-- sdlc:baseline-unestablished -->\n"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    # `git commit` would start detached auto maintenance, which creates and removes
    # `objects/maintenance.lock` after commit returns and races copytree and cleanup.
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "maintenance.auto",
    "GIT_CONFIG_VALUE_0": "false",
}
# Snapshot before any test patches GIT_ENV, so the shared template never sees a patch.
DEFAULT_GIT_ENV = dict(GIT_ENV)
_TEMPLATE: Path | None = None


def digest(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _template() -> Path:
    """The initial repository, built once per process under DEFAULT_GIT_ENV and copied per test."""
    global _TEMPLATE
    if _TEMPLATE is None:
        tmp = tempfile.TemporaryDirectory()
        atexit.register(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        root.mkdir()
        env = {**os.environ, **DEFAULT_GIT_ENV}

        def git(*args):
            subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        # Every test repository is a copy, so Git calls made without GIT_ENV stay covered too.
        git("config", "maintenance.auto", "false")
        (root / "AGENTS.md").write_text("# Repository Agent Instructions\n")
        (root / "intent.md").write_text(UNESTABLISHED + "# Intent\n")
        (root / "spec.md").write_text(UNESTABLISHED + "# Specification\n")
        git("add", "-A")
        git("commit", "-q", "--allow-empty", "-m", "initial")
        _TEMPLATE = root
    return _TEMPLATE


# -- running control-plane scripts ---------------------------------------------
#
# Tests call repo.py and guard.py in-process by default: a subprocess per call
# dominated the suite's runtime. SDLC_TEST_SUBPROCESS=1 restores the old path;
# SDLC_TEST_EQUIVALENCE=1 runs every call both ways and compares the results.


def mode() -> str:
    if os.environ.get("SDLC_TEST_EQUIVALENCE") == "1":
        return "equivalence"
    if os.environ.get("SDLC_TEST_SUBPROCESS") == "1":
        return "subprocess"
    return "inprocess"


def run_subprocess(script: Path, args, stdin, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        input=stdin,
        capture_output=True,
        text=True,
    )


def load(script: Path):
    """The script's module, imported once under its own name (`close` already imports `repo` this way)."""
    name = script.stem
    module = sys.modules.get(name)
    if module is None or Path(module.__file__).resolve() != script.resolve():
        spec = importlib.util.spec_from_file_location(name, script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def _stream(errors: str) -> io.TextIOWrapper:
    # What a child Python writes to on a UTF-8 pipe: strict stdout, backslashreplace stderr.
    return io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors=errors)


def _text(stream: io.TextIOWrapper) -> str:
    # Decode as `subprocess.run(text=True)` does: locale encoding, universal newlines.
    stream.flush()
    data = stream.buffer.getvalue()
    return io.TextIOWrapper(io.BytesIO(data), encoding=locale.getpreferredencoding(False), newline=None).read()


def invoke(module, script: Path, args, stdin, cwd) -> subprocess.CompletedProcess:
    """Call `module.main(args)` as if `python3 <script> <args>` ran in `cwd` under GIT_ENV."""
    argv = list(args)
    saved = (os.getcwd(), sys.argv, sys.stdin, sys.stdout, sys.stderr)
    out, err = _stream("strict"), _stream("backslashreplace")
    try:
        os.chdir(cwd)
        sys.argv = [str(script), *argv]
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        sys.stdout, sys.stderr = out, err
        with mock.patch.dict(os.environ, GIT_ENV):
            try:
                code = module.main(argv)
            except SystemExit as exc:
                code = exc.code
            except Exception:
                traceback.print_exc()
                code = 1
        if code is None:
            code = 0
        elif not isinstance(code, int):
            print(code, file=sys.stderr)
            code = 1
    finally:
        os.chdir(saved[0])
        sys.argv, sys.stdin, sys.stdout, sys.stderr = saved[1:]
    return subprocess.CompletedProcess([sys.executable, str(script), *argv], code, _text(out), _text(err))


def tree_state(area: Path) -> dict:
    """Every path under `area` with its type, mode and content; for a .git directory, refs, HEAD and staged entries."""
    state = {}
    for dirpath, dirnames, filenames in os.walk(area):
        dirnames.sort()
        here = Path(dirpath)
        if ".git" in dirnames:
            dirnames.remove(".git")
            repo = here
            key = f"{repo.relative_to(area).as_posix()}/.git"
            env = {**os.environ, **GIT_ENV}
            # HEAD as written: a symbolic ref, or the commit of a detached HEAD.
            state[f"{key}:HEAD"] = (repo / ".git" / "HEAD").read_bytes()
            for args in (["for-each-ref", "--format=%(refname) %(objectname)"], ["ls-files", "-s"]):
                proc = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True)
                if proc.returncode != 0:
                    raise AssertionError(f"git {args} failed in {repo}: {proc.stderr.decode(errors='replace')}")
                state[f"{key}:{args[0]}"] = proc.stdout
        for name in sorted(dirnames) + sorted(filenames):
            path = here / name
            rel = path.relative_to(area).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                state[rel] = ("link", os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                state[rel] = ("dir", stat.S_IMODE(info.st_mode))
            else:
                state[rel] = ("file", stat.S_IMODE(info.st_mode), path.read_bytes())
    return state


def restore(area: Path, snapshot: Path) -> None:
    for entry in list(area.iterdir()):
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    shutil.copytree(snapshot, area, symlinks=True, dirs_exist_ok=True)


# Volatile values that differ between two identical runs, and nothing else.
RUN_ID = re.compile(r"\d{8}T\d{12}Z")  # repo.py verify run ids and the evidence directories named after them
AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")  # the `at` time approve echoes
AT_FIELD = re.compile(r'("at": ")\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z(")')  # the `at` field approve writes
DURATION = re.compile(r'("duration_seconds": )[0-9.]+')


def normalize(text: str, channel: str = "stdout") -> str:
    """Mask the volatile values of one output channel ("stdout", "stderr") or of a written "file"."""
    text = RUN_ID.sub("<run-id>", text)
    text = DURATION.sub(r"\1<duration>", text)
    if channel == "file":
        return AT_FIELD.sub(r"\1<at>\2", text)
    text = AT.sub("<at>", text)
    lines = text.rstrip("\n").splitlines()
    if channel == "stderr" and lines and "Traceback (most recent call last):" in text:
        # The outermost frames differ by construction (module level vs. the test runner); the error does not.
        return "<traceback>\n" + lines[-1]
    return text


def _normal_state(state: dict) -> dict:
    # Several verify runs can sit side by side; number their ids in time order so they stay distinct.
    ids = sorted({m for path in state for m in RUN_ID.findall(path)})
    number = {run: f"<run-id-{i}>" for i, run in enumerate(ids)}

    def runs(text: str) -> str:
        return RUN_ID.sub(lambda m: number.get(m.group(0), "<run-id>"), text)

    out = {}
    for path, value in state.items():
        if isinstance(value, tuple) and value[0] == "file":
            try:
                value = (*value[:2], normalize(runs(value[2].decode()), "file"))
            except UnicodeDecodeError:
                pass
        out[runs(path)] = value
    return out


def compare_runs(expected, actual) -> str | None:
    """Why two (CompletedProcess, tree_state) runs differ beyond the volatile values, or None."""
    (a, a_state), (b, b_state) = expected, actual
    if a.returncode != b.returncode:
        return f"exit {a.returncode} != {b.returncode}"
    for name in ("stdout", "stderr"):
        x, y = normalize(getattr(a, name), name), normalize(getattr(b, name), name)
        if x != y:
            return f"{name} differs:\n--- subprocess\n{x}\n--- in-process\n{y}"
    x, y = _normal_state(a_state), _normal_state(b_state)
    if x != y:
        changed = sorted(p for p in x.keys() | y.keys() if x.get(p) != y.get(p))
        return f"files differ: {changed}"
    return None


class RepoCase(unittest.TestCase):
    """Each test gets a fresh repository on `main` with an initial commit."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(_template(), self.root, symlinks=True)

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
            "tree_sha256": repo.candidate_digest(self.root, cid),
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

    def run_script(self, script: Path, args, stdin=None, cwd=None):
        """Run a control-plane script in-process, as a subprocess, or both and compare (see `mode`)."""
        cwd = cwd or self.root
        selected = mode()
        if selected == "subprocess":
            return run_subprocess(script, args, stdin, cwd)
        if selected == "inprocess":
            return invoke(load(script), script, args, stdin, cwd)
        return self.run_both(script, args, stdin, cwd)

    def run_both(self, script: Path, args, stdin, cwd):
        """Run the call as a subprocess, restore the temporary directory, run it in-process, compare."""
        area = Path(self._tmp.name)
        with tempfile.TemporaryDirectory() as spare:
            snapshot = Path(spare) / "snapshot"
            shutil.copytree(area, snapshot, symlinks=True)
            expected = run_subprocess(script, args, stdin, cwd)
            expected_state = tree_state(area)
            restore(area, snapshot)
        actual = invoke(load(script), script, args, stdin, cwd)
        problem = compare_runs((expected, expected_state), (actual, tree_state(area)))
        if problem:
            raise AssertionError(f"in-process and subprocess runs of {script.name} {list(args)} differ: {problem}")
        return actual

    def run_repo(self, *args, cwd=None):
        return self.run_script(REPO_PY, args, cwd=cwd)

    def run_repo_subprocess(self, *args, cwd=None):
        return run_subprocess(REPO_PY, args, None, cwd or self.root)

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
