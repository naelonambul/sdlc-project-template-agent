#!/usr/bin/env python3
"""Agent-neutral guard: decide allow / deny / ask for a file edit or a shell command.

    guard.py path <path> [--proposed FILE|-]   file edit about to happen
    guard.py command <string>                  shell command about to run
    guard.py claude                            Claude Code PreToolUse JSON on stdin

`path` and `command` print {"decision", "reason"} and exit 0 (allow), 2 (deny) or 3 (ask).
The guard adds friction and an audit trail; it is not authentication and not the
enforcement boundary. When it cannot evaluate, it allows and says why on stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
from pathlib import Path

ALLOW, DENY, ASK = "allow", "deny", "ask"
EXIT = {ALLOW: 0, DENY: 2, ASK: 3}


def decision(kind: str, reason: str = "") -> tuple[str, str]:
    return kind, reason


# --------------------------------------------------------------------------
# repository facts
# --------------------------------------------------------------------------


def git(root: Path | str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def find_root(cwd: str) -> Path | None:
    try:
        proc = git(cwd, "rev-parse", "--show-toplevel")
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).resolve()


def baseline_ref(root: Path) -> str | None:
    branch = "main"
    try:
        config = json.loads((root / "checks.json").read_text())
        branch = config.get("baseline_branch", "main") or "main"
    except (OSError, ValueError, AttributeError):
        pass
    for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        if git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}").stdout.strip():
            return ref
    return None


def is_frozen(root: Path, change_id: str) -> bool:
    ref = baseline_ref(root)
    if ref is None:
        return False
    return git(root, "cat-file", "-e", f"{ref}:changes/{change_id}/closure.json").returncode == 0


def relative_path(root: Path, path: str) -> str | None:
    """POSIX path relative to the repository root, or None when it lies outside."""
    raw = Path(path)
    absolute = raw if raw.is_absolute() else root / raw
    resolved = Path(os.path.realpath(absolute))
    try:
        rel = resolved.relative_to(root).as_posix()
    except ValueError:
        return None
    return posixpath.normpath(rel)


# --------------------------------------------------------------------------
# path rules
# --------------------------------------------------------------------------


def approvals_of(text: str) -> object:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data.get("approvals", [])


def decide_path(root: Path, path: str, proposed: str | None) -> tuple[str, str]:
    rel = relative_path(root, path)
    if rel is None:
        return decision(ALLOW, "path is outside the repository")
    parts = rel.split("/")

    if rel in ("intent.md", "spec.md"):
        return decision(DENY, "root-baseline: edit the change-local copy; the root is replaced whole at closure")
    if parts[0] == "changes" and len(parts) >= 3 and is_frozen(root, parts[1]):
        return decision(DENY, "frozen-packet: the packet is closed on the baseline branch; record follow-up work as a new change")
    if len(parts) == 3 and parts[0] == "changes" and parts[2] == "closure.json":
        return decision(DENY, "closure: closures are written by repo.py close")
    if len(parts) == 3 and parts[0] == "changes" and parts[2] == "change.json":
        approvals_reason = "change-approvals: approvals are recorded by repo.py approve, by the owner"
        if proposed is None:
            return decision(DENY, approvals_reason + " (no proposed content to compare)")
        try:
            current = approvals_of((root / rel).read_text())
        except (OSError, ValueError):
            current = []
        try:
            new = approvals_of(proposed)
        except ValueError:
            return decision(DENY, approvals_reason + " (proposed content is not valid JSON)")
        if new != current:
            return decision(DENY, approvals_reason)
    return decision(ALLOW)


# --------------------------------------------------------------------------
# command rules
# --------------------------------------------------------------------------

PACKET_FILE = re.compile(r"(?:^|/)(?:change|closure)\.json$")
APPROVE = re.compile(r"repo\.py\s+approve\b")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}


def tokenize(command: str) -> list[str]:
    """Shell-ish tokens, operators kept as their own tokens; newlines count as separators."""
    try:
        lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return command.split()


def is_operator(token: str) -> bool:
    return bool(token) and all(c in "();<>|&" for c in token)


def split_segments(tokens: list[str]) -> list[list[str]]:
    """Simple commands between operators, with redirection targets dropped."""
    segments: list[list[str]] = [[]]
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if is_operator(token):
            if ">" in token or "<" in token:
                skip = True
            else:
                segments.append([])
        else:
            segments[-1].append(token)
    return [s for s in segments if s]


def names_packet_file(token: str) -> bool:
    return bool(PACKET_FILE.search(token))


def packet_write(tokens: list[str]) -> bool:
    """A redirect, tee, in-place edit, move, copy, delete or inline script that targets change.json or closure.json."""
    for i, token in enumerate(tokens):
        if is_operator(token) and ">" in token and i + 1 < len(tokens) and names_packet_file(tokens[i + 1]):
            return True
    for segment in split_segments(tokens):
        cmd, args = posixpath.basename(segment[0]), segment[1:]
        if cmd == "tee" and any(names_packet_file(a) for a in args):
            return True
        if cmd == "sed" and any(a == "--in-place" or (a.startswith("-") and not a.startswith("--") and "i" in a) for a in args):
            if any(names_packet_file(a) for a in args):
                return True
        if cmd == "rm" and any(names_packet_file(a) for a in args):
            return True
        if cmd in ("mv", "cp") and args and names_packet_file(args[-1]):
            return True
        if cmd in ("python", "python3") and "-c" in args and any(names_packet_file(a) or "change.json" in a or "closure.json" in a for a in args):
            return True
    return False


def git_invocation(segment: list[str]) -> tuple[str, list[str]] | None:
    """Return (subcommand, arguments) when the segment runs git."""
    for i, token in enumerate(segment):
        if posixpath.basename(token) != "git":
            continue
        rest = segment[i + 1 :]
        j = 0
        while j < len(rest) and rest[j].startswith("-"):
            j += 2 if rest[j] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
        if j < len(rest):
            return rest[j], rest[j + 1 :]
        return None
    return None


def short_flags(args: list[str]) -> str:
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def git_rule(sub: str, args: list[str]) -> str | None:
    flags = short_flags(args)
    if sub == "push":
        if (
            any(a == "--force" or a.startswith("--force-") for a in args)
            or "f" in flags
            or any(len(a) > 1 and a.startswith("+") for a in args)
        ):
            return "force-push"
        if "--delete" in args or "d" in flags or any(len(a) > 1 and a.startswith(":") for a in args):
            return "push-delete"
    elif sub == "reset" and "--hard" in args:
        return "reset-hard"
    elif sub == "clean" and ("--force" in args or "f" in flags):
        return "clean-force"
    elif sub == "branch" and "D" in flags:
        return "branch-delete"
    elif sub == "rebase":
        return "rebase"
    elif sub == "commit" and "--amend" in args:
        return "commit-amend"
    elif sub == "filter-branch":
        return "filter-branch"
    return None


def decide_command(command: str, depth: int = 0) -> tuple[str, str]:
    tokens = tokenize(command)
    segments = split_segments(tokens)
    for segment in segments:
        invocation = git_invocation(segment)
        if invocation:
            rule = git_rule(*invocation)
            if rule:
                return decision(ASK, f"{rule}: history rewrite or destructive git command; the human confirms")
        if APPROVE.search(" ".join(segment)) and any(a.endswith("repo.py") for a in segment):
            return decision(ASK, "approve: approvals are recorded by the owner; the human confirms")
    if packet_write(tokens):
        return decision(ASK, "packet-write: shell write to change.json or closure.json; the human confirms")
    if depth < 3:
        for segment in segments:
            if posixpath.basename(segment[0]) in SHELLS and "-c" in segment:
                script = segment[segment.index("-c") + 1 :]
                if script:
                    nested = decide_command(script[0], depth + 1)
                    if nested[0] != ALLOW:
                        return nested
    return decision(ALLOW)


# --------------------------------------------------------------------------
# Claude Code adapter
# --------------------------------------------------------------------------


def apply_edit(text: str, old: str, new: str, replace_all: bool) -> str:
    return text.replace(old, new) if replace_all else text.replace(old, new, 1)


def read_current(root: Path, file_path: str) -> str | None:
    raw = Path(file_path)
    target = raw if raw.is_absolute() else root / raw
    try:
        return target.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def claude_decision(payload: dict) -> tuple[str, str]:
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if tool not in ("Edit", "Write", "MultiEdit", "Bash") or not isinstance(tool_input, dict):
        return decision(ALLOW)
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
    root = find_root(cwd)
    if root is None:
        print("guard: no git repository found; allowing", file=sys.stderr)
        return decision(ALLOW, "no repository")

    if tool == "Bash":
        command = tool_input.get("command")
        return decide_command(command) if isinstance(command, str) else decision(ALLOW)

    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return decision(ALLOW)
    if tool == "Write":
        proposed = tool_input.get("content")
        if not isinstance(proposed, str):
            return decision(ALLOW)
    elif tool == "Edit":
        current = read_current(root, file_path)
        new = tool_input.get("new_string", "")
        if current is None:
            proposed = new
        else:
            proposed = apply_edit(current, tool_input.get("old_string", ""), new, bool(tool_input.get("replace_all")))
    else:
        proposed = read_current(root, file_path) or ""
        for edit in tool_input.get("edits") or []:
            proposed = apply_edit(proposed, edit.get("old_string", ""), edit.get("new_string", ""), bool(edit.get("replace_all")))
    return decide_path(root, file_path, proposed)


def run_claude() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("not an object")
    except ValueError:
        print("guard: unreadable hook input; allowing", file=sys.stderr)
        return 0
    try:
        kind, reason = claude_decision(payload)
    except Exception as exc:  # the guard is friction, never a crash in the agent's loop
        print(f"guard: cannot evaluate ({type(exc).__name__}: {exc}); allowing", file=sys.stderr)
        return 0
    if kind == DENY:
        print(reason, file=sys.stderr)
        return 2
    if kind == ASK:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "ask",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def emit(result: tuple[str, str]) -> int:
    kind, reason = result
    print(json.dumps({"decision": kind, "reason": reason}))
    return EXIT[kind]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    p_path = sub.add_parser("path", help="decide a file edit")
    p_path.add_argument("path")
    p_path.add_argument("--proposed", metavar="FILE|-", help="full content after the edit; '-' reads stdin")
    p_command = sub.add_parser("command", help="decide a shell command")
    p_command.add_argument("command")
    sub.add_parser("claude", help="Claude Code PreToolUse hook on stdin")
    args = parser.parse_args(argv)

    if args.mode == "claude":
        return run_claude()

    root = find_root(os.getcwd())
    if root is None:
        print("guard: no git repository found; allowing", file=sys.stderr)
        return emit(decision(ALLOW, "no repository"))
    if args.mode == "command":
        return emit(decide_command(args.command))

    proposed = None
    if args.proposed == "-":
        proposed = sys.stdin.read()
    elif args.proposed is not None:
        try:
            proposed = Path(args.proposed).read_text()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"guard: cannot read proposed content: {exc}", file=sys.stderr)
    return emit(decide_path(root, args.path, proposed))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
