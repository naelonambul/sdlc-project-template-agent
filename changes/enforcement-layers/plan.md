# Implementation Plan

## Summary

The template enforces its *process* deterministically (`repo.py status`, CI), but it has none of the two in-the-loop layers that both source documents insist on: there are no hooks (nothing stops an agent mid-session from editing approvals, a frozen packet, or the root baseline) and there are no evals (nothing regression-tests `AGENTS.md`, the skills, or the hook behaviour against a real harness). Approval and closure are also still hand-written JSON, which is where the only recorded pilot mistake happened.

This change adds four things, all agent-neutral and standard-library only:

1. **Hooks.** `scripts/hooks/guard.py` decides `allow`/`deny`/`ask` for a proposed file edit or shell command from repository rules alone. `.claude/settings.json` is a thin adapter that calls it from Claude Code's `PreToolUse` event. `repo.py status` checks that the adapter points at existing hook scripts, as it already does for skill adapters.
2. **Evals.** `scripts/evals.py` runs `evals/<case>/eval.json` cases against whichever harness CLI is installed (`claude`, `codex`), in a scratch copy of the working tree, and records evidence. Five first cases cover the agent surface (AGENTS.md delivery, CLAUDE.md shadowing), the hook (root baseline edit, approval edit) and the worker brief (stays inside FILES, reports BLOCKED). A separate, non-gating workflow runs them on changes to agent configuration and weekly.
3. **Mechanical approval and closure.** `repo.py approve <id> <artifact> --by <name>` records a digest-bound claim for the current bytes, in chain order. `repo.py close <id> --evidence <ref>...` computes `packet_sha256` and the carried baseline digests and refuses when the root has not been updated. Neither command changes what counts as approval: a local claim stays `unverified`.
4. **A registered-check warning.** `status` warns when product files are tracked but only the template's `control-plane` check is registered, so the soft `repository-quality` skill has a deterministic nudge behind it.

This is a `repository` change. It touches no root `intent.md` or `spec.md`.

## Files and components that change

| Path | Change |
|---|---|
| `scripts/hooks/guard.py` | New. Policy engine plus `claude` stdin adapter (contract below). |
| `scripts/hooks/README.md` | Describe the guard, its decisions, and how another harness adapts it. |
| `.claude/settings.json` | New. `PreToolUse` hooks for `Edit|Write|MultiEdit` and `Bash` calling `guard.py claude`. |
| `scripts/evals.py` | New. Eval runner (contract below). |
| `evals/README.md` | Rewrite: case format, running, when to add a case, the tripwire case. |
| `evals/*/eval.json` | Five initial cases. |
| `.github/workflows/agent-evals.yml` | New. Non-gating: runs `evals.py` on agent-config changes and weekly when an API key secret is present. |
| `scripts/repo.py` | `approve` and `close` subcommands; `hook-broken` / `hook-adapter-missing` surface findings; `checks-unregistered` warning. |
| `scripts/tests/test_guard.py`, `test_evals.py`, `test_approve_close.py` | New unit tests; `test_status.py` gains the new surface cases. |
| `scripts/README.md`, `AGENTS.md`, `README.md`, `changes/README.md`, `.agents/skills/sdlc-artifacts/SKILL.md`, `docs/agent-surfaces.md` | Document the commands, the hook adapter, the evals, and state that the Maintain stage is out of the template's scope. |

Out of scope: `checks.json` semantics, `repository.yml`, `REVIEW.md` content, the tool skills, any `verified` approval path, and any change to what `status` accepts as approval.

## Contracts

### `guard.py`

```text
python3 scripts/hooks/guard.py path <path> [--proposed FILE|-]   # file edit about to happen
python3 scripts/hooks/guard.py command <string>                  # shell command about to run
python3 scripts/hooks/guard.py claude                            # Claude Code PreToolUse JSON on stdin
```

`path` and `command` print `{"decision": "allow"|"deny"|"ask", "reason": "..."}` and exit 0 / 2 / 3 respectively. Paths may be absolute or relative to the repository root (`git rev-parse --show-toplevel` from the current directory).

Rules, evaluated in order, first match wins:

| Target | Decision | Reason |
|---|---|---|
| root `intent.md` or `spec.md` | deny | edit the change-local copy; the root is replaced whole at closure |
| `changes/<id>/**` when the baseline branch already contains `changes/<id>/closure.json` | deny | the packet is frozen; record follow-up work as a new change |
| `changes/<id>/closure.json` | deny | closures are written by `repo.py close` |
| `changes/<id>/change.json` when the proposed content's `approvals` differ from the current file's (or cannot be parsed) | deny | approvals are recorded by `repo.py approve`, by the owner |
| anything else | allow | |

Commands: history rewrites and force pushes (`push --force*`, `reset --hard`, `clean -f`, `branch -D`, `rebase`, `commit --amend`, `filter-branch`, `push --delete`), `repo.py approve`, and shell writes that name `change.json` or `closure.json` return **ask**, never deny: the human confirms in session. Everything else is allow.

`claude` maps `Edit`/`Write`/`MultiEdit` to `path` with the proposed content computed from `tool_input`, and `Bash` to `command`. Deny exits 2 with the reason on stderr; ask prints `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": ...}}`; allow exits 0 silently. A guard that cannot evaluate (no repository, unreadable input) allows and says why on stderr: the guard adds friction, it is not the enforcement boundary.

### `evals.py`

```text
python3 scripts/evals.py [--case ID]... [--harness claude|codex]... [--require-harness] [--json] [--evidence-dir DIR]
```

Each `evals/<case>/eval.json` has `schema: 1`, `harnesses` (subset of `claude`, `codex`), `prompt`, optional `files` (relative path to content, written into the scratch copy), optional per-harness `args`, `timeout_seconds` (default 300), and `expect` with any of `stdout_contains`, `stdout_not_contains`, `files_unchanged`, `files_changed`. The runner copies the working tree (tracked and untracked, unignored; symlinks preserved) into a scratch directory with a fresh `git init` and commit, writes `files`, runs the harness non-interactively with the scratch directory as working directory, and compares file digests before and after. Results are `passed`, `failed`, `error` (harness crashed or timed out) or `skipped` (harness not installed; `--require-harness` turns it into `failed`). Evidence goes to `.evidence/evals/<run>/`. Exit 1 if any case failed or errored.

Initial cases:

| Case | Harness | Expect |
|---|---|---|
| `agents-md-delivered` | claude, codex | `AGENTS=yes` and the four core skill names in stdout |
| `claude-md-shadows-agents-md` | claude | with a `CLAUDE.md` written: `AGENTS=no` (tripwire for the documented shadowing) |
| `guard-blocks-root-baseline-edit` | claude | asked to append to root `intent.md` with Edit allowed: `intent.md` unchanged |
| `guard-blocks-approval-edit` | claude | asked to add an approval claim with Edit allowed: `change.json` unchanged |
| `worker-brief-stays-in-files` | claude, codex | a filled worker brief whose goal needs a file outside FILES: stdout contains `BLOCKED`, the file unchanged |

### `repo.py approve` and `close`

```text
python3 scripts/repo.py approve <id> <artifact> --by <name> [--note TEXT]
python3 scripts/repo.py close <id> --evidence <ref>...
```

`approve` refuses when the packet or artifact is missing, when an upstream chain artifact is not currently approved (approve in order), or when `by` is empty. It replaces any earlier claim for the same artifact and records the current digest with a UTC timestamp. `close` refuses when any chain artifact lacks a current approval, when a carried `intent.md`/`spec.md` differs from the root (print the copy command), or when no evidence is given. It writes `closure.json` with `baseline`, `packet_sha256` and `evidence`; an evidence reference that is an existing file is recorded with its sha256. Rewriting an existing closure is allowed (fixes after closure). Both print the next `status` command and never commit.

## Order of work

1. **Plan approval (owner).** The owner approves this `plan.md` digest.
2. **Guard** (`scripts/hooks/guard.py`, `README.md`, `.claude/settings.json`, `scripts/tests/test_guard.py`). Verify: `python3 -m unittest scripts.tests.test_guard`.
3. **Evals** (`scripts/evals.py`, `evals/`, `.github/workflows/agent-evals.yml`, `scripts/tests/test_evals.py`). Verify: `python3 -m unittest scripts.tests.test_evals`, then `python3 scripts/evals.py --harness claude` where a harness is available.
4. **repo.py** (`approve`, `close`, surface and config findings, tests). Verify: `python3 -m unittest discover -s scripts/tests -t .`.
5. **Docs** listed above.
6. **Verification.** `repo.py status --change enforcement-layers`, `repo.py verify --change enforcement-layers`, `repo.py verify --full`; the eval suite against the installed harness.
7. **Selective review.** Verification and tests' oracles change, so one read-only reviewer from a different context reads the diff.
8. **Candidate closure** with `repo.py close`, then the pull request with `Change-ID: enforcement-layers`.

Steps 2 and 3 are independent units with disjoint FILES and may run in parallel as worker units under the `change-execution` skill; step 4 is coordinator work because it shares `repo.py` with nothing else in this change.

## Tests and proof

| Contract item | Proof |
|---|---|
| Each guard rule denies / asks / allows | one negative and one positive case per rule in `test_guard.py`; the `claude` adapter's exit codes and JSON |
| Guard is a thin adapter | `.claude/settings.json` contains no policy, only `guard.py claude` invocations; `status` reports `hook-broken` when a referenced script is missing |
| Runner semantics | `test_evals.py` with a stub harness on `PATH`: pass, fail, error, skipped, `--require-harness`, `files_unchanged`, evidence written, every shipped case parses |
| Live behaviour | `scripts/evals.py --harness claude` run recorded in the pull request |
| `approve` / `close` refusals and outputs | `test_approve_close.py`; a `close` output validates as `closure=candidate` under `status` |
| `checks-unregistered` warning | `test_status.py`: warns with product files and only `control-plane`; silent otherwise |
| No regression | full `control-plane` suite |

## Risks and mitigations

- **A hook mistaken for authentication.** README, hook README and `changes/README.md` keep saying it is friction. `status` never reads hook state when computing approval.
- **Evals cost tokens and need credentials.** The workflow is not in `repository.yml`, is not a required check, and skips with a notice when the key is absent. Locally, a missing harness is `skipped`, never `passed`.
- **Hook blocks legitimate work.** Every deny names the command to use instead. Nothing is denied for the `Bash` tool; destructive commands only `ask`.
- **Harness behaviour drifts.** That is what the tripwire case is for; when it fails, `docs/agent-surfaces.md` is updated in a new change.

## Rollback or recovery

Revert the squash commit. Removing `.claude/settings.json` alone disables the hook without touching the policy.

## Open questions

None.
