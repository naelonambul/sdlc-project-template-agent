#!/usr/bin/env python3
"""Agent eval runner: run `evals/<case>/eval.json` against installed harness CLIs.

Standard library only. Each case runs in a scratch copy of the working tree
(tracked and untracked, unignored files; symlinks preserved) with a fresh git
history, so a harness can never touch the real checkout. Results are
`passed`, `failed`, `error` or `skipped`; `skipped` is never a pass. Evidence
(stdout/stderr logs and `results.json`) goes to `.evidence/evals/<run>/`.
See `evals/README.md`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SCHEMA = 1
EVALS = "evals"
CASE_FILE = "eval.json"
HARNESSES = ("claude", "codex")
DEFAULT_TIMEOUT = 300
EXPECT_KEYS = ("stdout_contains", "stdout_not_contains", "files_unchanged", "files_changed")
CASE_KEYS = {"schema", "harnesses", "prompt", "files", "args", "timeout_seconds", "expect", "description"}
SCRATCH_GIT_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


@dataclass
class Case:
    id: str
    path: Path
    data: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def harnesses(self) -> list[str]:
        return list(self.data.get("harnesses", [])) if not self.problems else []


# -- validation ----------------------------------------------------------------


def _bad_relpath(rel: object) -> str | None:
    if not isinstance(rel, str) or not rel:
        return "must be a non-empty string"
    if "\\" in rel:
        return "must use forward slashes"
    pure = PurePosixPath(rel)
    if pure.is_absolute():
        return "must be relative"
    if ".." in pure.parts:
        return "must not contain '..'"
    if pure.parts and pure.parts[0] == ".git":
        return "must not be inside .git"
    return None


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def validate_case(data: object) -> list[str]:
    """Return the problems with an `eval.json` document; empty means valid."""
    if not isinstance(data, dict):
        return ["eval.json must be a JSON object"]
    problems = []
    unknown = sorted(set(data) - CASE_KEYS)
    if unknown:
        problems.append(f"unknown field(s): {unknown}")
    if data.get("schema") != SCHEMA or isinstance(data.get("schema"), bool):
        problems.append(f"schema must be {SCHEMA}")
    harnesses = data.get("harnesses")
    if not _is_str_list(harnesses) or not harnesses:
        problems.append("harnesses must be a non-empty list of strings")
    elif set(harnesses) - set(HARNESSES):
        problems.append(f"harnesses must be a subset of {list(HARNESSES)}")
    elif len(set(harnesses)) != len(harnesses):
        problems.append("harnesses must not repeat")
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        problems.append("prompt must be a non-empty string")
    if "files" in data:
        files = data["files"]
        if not isinstance(files, dict):
            problems.append("files must be an object of relative path -> string content")
        else:
            for rel, content in files.items():
                why = _bad_relpath(rel)
                if why:
                    problems.append(f"files path {rel!r} {why}")
                if not isinstance(content, str):
                    problems.append(f"files content for {rel!r} must be a string")
    if "args" in data:
        args = data["args"]
        if not isinstance(args, dict):
            problems.append("args must be an object of harness -> list of strings")
        else:
            for name, values in args.items():
                if name not in HARNESSES:
                    problems.append(f"args names unknown harness {name!r}")
                if not _is_str_list(values):
                    problems.append(f"args for {name!r} must be a list of strings")
    if "timeout_seconds" in data:
        t = data["timeout_seconds"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
            problems.append("timeout_seconds must be a positive number")
    if "description" in data and not isinstance(data["description"], str):
        problems.append("description must be a string")
    expect = data.get("expect")
    if not isinstance(expect, dict):
        problems.append("expect must be an object")
    else:
        unknown = sorted(set(expect) - set(EXPECT_KEYS))
        if unknown:
            problems.append(f"expect has unknown key(s): {unknown}")
        present = [k for k in EXPECT_KEYS if k in expect]
        if not present:
            problems.append(f"expect needs at least one of {list(EXPECT_KEYS)}")
        for key in present:
            if not _is_str_list(expect[key]):
                problems.append(f"expect.{key} must be a list of strings")
            elif key.startswith("files_"):
                for rel in expect[key]:
                    why = _bad_relpath(rel)
                    if why:
                        problems.append(f"expect.{key} path {rel!r} {why}")
    return problems


def load_case(case_dir: Path) -> Case:
    case = Case(id=case_dir.name, path=case_dir / CASE_FILE)
    try:
        case.data = json.loads(case.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        case.problems = [f"cannot read {CASE_FILE}: {exc}"]
        return case
    case.problems = validate_case(case.data)
    return case


def discover_cases(root: Path) -> list[Case]:
    base = root / EVALS
    if not base.is_dir():
        return []
    return [load_case(d) for d in sorted(base.iterdir()) if d.is_dir() and (d / CASE_FILE).is_file()]


# -- git / scratch copy ----------------------------------------------------------


def git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True)


def repo_root() -> Path | None:
    proc = git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(proc.stdout.decode().strip()) if proc.returncode == 0 else None


def source_identity(root: Path) -> dict:
    commit = git(root, "rev-parse", "HEAD")
    dirty = git(root, "status", "--porcelain", "--untracked-files=normal")
    return {
        "commit": commit.stdout.decode().strip() if commit.returncode == 0 else None,
        "dirty": bool(dirty.returncode == 0 and dirty.stdout.strip()),
    }


def worktree_paths(root: Path) -> list[str]:
    proc = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {proc.stderr.decode(errors='replace').strip()}")
    names = [n for n in proc.stdout.decode("utf-8", errors="surrogateescape").split("\0") if n]
    return list(dict.fromkeys(names))


def make_scratch(root: Path, files: dict, exclude: Path | None = None) -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="eval-"))
    for rel in worktree_paths(root):
        src = root / rel
        if exclude is not None and (src == exclude or exclude in src.parents):
            continue
        if not os.path.lexists(src) or (src.is_dir() and not src.is_symlink()):
            continue
        dst = scratch / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
        else:
            shutil.copy2(src, dst)
    env = {**os.environ, **SCRATCH_GIT_ENV}
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "--allow-empty", "-m", "eval")):
        proc = git(scratch, *args, env=env)
        if proc.returncode != 0:
            shutil.rmtree(scratch, ignore_errors=True)
            raise RuntimeError(f"git {' '.join(args)} failed in scratch copy: {proc.stderr.decode(errors='replace').strip()}")
    for rel, content in files.items():
        path = scratch / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return scratch


def snapshot(tree: Path) -> dict[str, str]:
    digests = {}
    for dirpath, dirnames, filenames in os.walk(tree):
        if Path(dirpath) == tree and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            digests[path.relative_to(tree).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


# -- running a case ----------------------------------------------------------------


ENV_NAMES = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "TMPDIR", "TMP", "TEMP", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE"}
ENV_PREFIXES = ("LC_", "XDG_", "ANTHROPIC_", "CLAUDE_", "CODEX_", "OPENAI_", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy", "EVAL_")


def harness_env(environ) -> dict[str, str]:
    """The harness sees only what it needs to run and authenticate, never the caller's other secrets.

    `EVAL_*` passes through for test stubs. `CLAUDECODE` is dropped so the runner works inside a Claude Code session.
    """
    return {
        k: v
        for k, v in environ.items()
        if (k in ENV_NAMES or k.startswith(ENV_PREFIXES)) and k != "CLAUDECODE"
    }


def harness_argv(harness: str, prompt: str, args: list[str]) -> list[str]:
    if harness == "claude":
        return ["claude", "-p", prompt, "--output-format", "text", *args]
    if not any(a == "--sandbox" or a.startswith("--sandbox=") for a in args):
        args = ["--sandbox", "read-only", *args]
    return ["codex", "exec", *args, prompt]


def check_expectations(expect: dict, stdout: str, before: dict, after: dict) -> list[str]:
    misses = []
    for text in expect.get("stdout_contains", []):
        if text not in stdout:
            misses.append(f"stdout lacks {text!r}")
    for text in expect.get("stdout_not_contains", []):
        if text in stdout:
            misses.append(f"stdout contains {text!r}")
    for rel in expect.get("files_unchanged", []):
        if rel not in before or rel not in after:
            misses.append(f"{rel} missing {'before' if rel not in before else 'after'} the run")
        elif before[rel] != after[rel]:
            misses.append(f"{rel} changed")
    for rel in expect.get("files_changed", []):
        if rel not in after:
            misses.append(f"{rel} missing after the run")
        elif before.get(rel) == after[rel]:
            misses.append(f"{rel} unchanged")
    return misses


def display_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def run_case(root: Path, case: Case, harness: str, evidence: Path, require_harness: bool, keep: bool) -> dict:
    result = {
        "case": case.id,
        "harness": harness,
        "status": None,
        "reason": None,
        "duration_seconds": None,
        "exit_code": None,
        "stdout_log": None,
        "stderr_log": None,
    }
    if shutil.which(harness) is None:
        status = "failed" if require_harness else "skipped"
        return {**result, "status": status, "reason": f"harness {harness!r} is not installed"}
    data = case.data
    try:
        scratch = make_scratch(root, data.get("files", {}), exclude=evidence)
    except (OSError, RuntimeError) as exc:
        return {**result, "status": "error", "reason": f"cannot build scratch copy: {exc}"}
    stdout_log = evidence / f"{case.id}.{harness}.stdout.log"
    stderr_log = evidence / f"{case.id}.{harness}.stderr.log"
    result["stdout_log"] = display_path(stdout_log, root)
    result["stderr_log"] = display_path(stderr_log, root)
    timeout = data.get("timeout_seconds", DEFAULT_TIMEOUT)
    argv = harness_argv(harness, data["prompt"], list(data.get("args", {}).get(harness, [])))
    env = harness_env(os.environ)
    try:
        before = snapshot(scratch)
        started = time.monotonic()
        timed_out = False
        with open(stdout_log, "wb") as out, open(stderr_log, "wb") as err:
            try:
                proc = subprocess.Popen(
                    argv, cwd=scratch, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True
                )
            except OSError as exc:
                return {**result, "status": "error", "reason": f"cannot start {harness}: {exc}"}
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                code = proc.wait()
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        result["exit_code"] = None if timed_out else code
        if timed_out:
            return {**result, "status": "error", "reason": f"timed out after {timeout}s"}
        if code != 0:
            return {**result, "status": "error", "reason": f"{harness} exited with code {code}"}
        after = snapshot(scratch)
        stdout = stdout_log.read_bytes().decode("utf-8", errors="replace")
        misses = check_expectations(data["expect"], stdout, before, after)
    finally:
        if keep:
            result["scratch"] = str(scratch)
        else:
            shutil.rmtree(scratch, ignore_errors=True)
    if misses:
        return {**result, "status": "failed", "reason": "; ".join(misses)}
    return {**result, "status": "passed", "reason": "all expectations met"}


# -- CLI ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run agent evals from evals/<case>/eval.json against installed harnesses.")
    parser.add_argument("--case", action="append", default=[], metavar="ID", help="run only this case (repeatable)")
    parser.add_argument("--harness", action="append", default=[], choices=HARNESSES, help="run only this harness (repeatable)")
    parser.add_argument("--require-harness", action="store_true", help="a missing harness is a failure, not a skip")
    parser.add_argument("--json", action="store_true", help="print results.json to stdout")
    parser.add_argument("--evidence-dir", metavar="DIR", help="evidence directory (default .evidence/evals/<run>/)")
    parser.add_argument("--list", action="store_true", help="list cases and their harnesses, then exit")
    parser.add_argument("--keep", action="store_true", help="keep scratch copies and record their paths")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    if root is None:
        print("evals.py: not inside a git repository", file=sys.stderr)
        return 2
    cases = discover_cases(root)
    if args.list:
        for case in cases:
            detail = ",".join(case.harnesses) if not case.problems else "invalid: " + "; ".join(case.problems)
            print(f"{case.id}  {detail}")
        return 0
    known = {c.id for c in cases}
    unknown = [c for c in args.case if c not in known]
    if unknown:
        print(f"evals.py: unknown case(s): {unknown}; known: {sorted(known)}", file=sys.stderr)
        return 2
    selected = [c for c in cases if not args.case or c.id in args.case]
    run_id = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = Path(args.evidence_dir).resolve() if args.evidence_dir else root / ".evidence" / "evals" / run_id
    evidence.mkdir(parents=True, exist_ok=True)
    results = []
    for case in selected:
        if case.problems:
            results.append(
                {
                    "case": case.id,
                    "harness": None,
                    "status": "error",
                    "reason": "invalid eval.json: " + "; ".join(case.problems),
                    "duration_seconds": None,
                    "exit_code": None,
                    "stdout_log": None,
                    "stderr_log": None,
                }
            )
            continue
        for harness in case.harnesses:
            if args.harness and harness not in args.harness:
                continue
            results.append(run_case(root, case, harness, evidence, args.require_harness, args.keep))
    if not results:
        print("evals.py: no case matches the selection", file=sys.stderr)
        return 2
    report = {"schema": SCHEMA, "run_id": run_id, "source": source_identity(root), "results": results}
    (evidence / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in results:
            print(f"{r['status']}  {r['case']}  {r['harness'] or '-'}  ({r['reason']})")
        print(f"evidence: {display_path(evidence, root)}")
    return 1 if any(r["status"] in ("failed", "error") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
