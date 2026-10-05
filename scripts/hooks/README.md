# Hook Implementations

`guard.py` is the agent-neutral guard. Agent-specific hook configuration calls it rather than duplicating its policy.

A hook adds friction and an audit trail, but it is **not authentication**. An agent that can edit the hook, its configuration, or the repository can bypass it. `repo.py` therefore never upgrades an approval to `verified` because a hook exists. Enforcement is `repo.py status`, tests and CI.

## What it decides

Rules for a file edit, evaluated in order; the first match wins.

| Target | Decision | Why |
|---|---|---|
| root `intent.md` or `spec.md` | deny | edit the change-local copy; the root is replaced whole at closure |
| `changes/<id>/**` when the baseline branch already has `changes/<id>/closure.json` | deny | the packet is frozen; record follow-up work as a new change |
| `changes/<id>/closure.json` | deny | closures are written by `repo.py close` |
| `changes/<id>/change.json` whose proposed `approvals` differ from the current file's (or cannot be parsed, or no proposed content is given) | deny | approvals are recorded by `repo.py approve`, by the owner |
| anything else, or a path outside the repository | allow | |

Shell commands return **ask**, never deny: force pushes (`push --force`, `--force-with-lease`, `-f`, `+refspec`), `push --delete`, `reset --hard`, `clean -f`, `branch -D`, `rebase`, `commit --amend`, `filter-branch`, `repo.py approve`, and shell writes whose target is `change.json` or `closure.json` (redirects, `tee`, `sed -i`, `rm`, `mv`/`cp` destinations, inline Python). Multi-line commands and `sh -c`/`bash -c` scripts are inspected too. Everything else is allow, including reads of those files and redirects elsewhere.

The file rules apply to the agent's file tools only. A shell write to the root baseline or a frozen packet file other than `change.json`/`closure.json` is not intercepted; `repo.py status` reports it after the fact. When the guard cannot evaluate (no repository, unreadable or malformed input) it allows and says why on stderr.

## Use

```text
python3 scripts/hooks/guard.py path <path> [--proposed FILE|-]   # --proposed: full content after the edit
python3 scripts/hooks/guard.py command <string>
python3 scripts/hooks/guard.py claude                            # Claude Code PreToolUse JSON on stdin
```

`path` and `command` print `{"decision": ..., "reason": ...}` and exit 0 (allow), 2 (deny) or 3 (ask).

## Wiring

- **Claude Code:** `.claude/settings.json` is a thin adapter that runs `guard.py claude` on `PreToolUse` for `Edit|Write|MultiEdit` and `Bash`. It holds no policy. `repo.py status` reports `hook-broken` if it points at an untracked script.
- **Another harness:** call `guard.py path` or `guard.py command` from its pre-edit or pre-command hook and map exit codes 0 to proceed, 2 to block, 3 to prompt the human.
- **Codex:** no hook integration has been observed, so for Codex the guard applies only after the fact, through `repo.py status`.

Long-running suites belong in `repo.py verify` and CI, not in per-edit hooks. Routine human approval prompts do not belong in hooks either.
