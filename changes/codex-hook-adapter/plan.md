# Implementation Plan

## Summary

Codex CLI has supported hooks since v0.114 (March 2026) as an experimental feature: a repository-level `.codex/hooks.json` merged with the user's `~/.codex/hooks.json`, a `PreToolUse` event that receives `tool_name`, `tool_input` and `cwd` as JSON on stdin, and a denial signalled by exit code 2 with the reason on stderr or by `permissionDecision: "deny"` JSON. The shape is the same as Claude Code's, with two differences: there is no `ask` decision at the hook layer, and the file-edit tool is `apply_patch` with a V4A patch body rather than Edit/Write with a path and strings. The repository currently states that Codex has no hook integration and that the guard applies only after the fact there. This change adds a thin Codex adapter so the same guard runs in Codex sessions, and corrects the documentation.

The guard's policy does not change. `ask` becomes `deny` in Codex with a reason that names the command the owner runs instead. Enforcement remains `repo.py status`, tests and CI; the hook stays friction and an audit trail.

This session cannot run Codex (not installed, network restricted), so the adapter is built against the documented input shape and unit-tested, and `docs/agent-surfaces.md` marks it **not yet observed** until the owner runs the smoke probe once and records the row. That probe also settles the one open fact: whether this Codex version fires `PreToolUse` for `apply_patch` as well as for shell commands.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/hooks/guard.py`:
  - a `codex` subcommand reading `PreToolUse` JSON from stdin. Shell tools (`tool_name` of `Bash`, `shell`, `local_shell` or `exec_command`, `tool_input.command` as a string or an argv list) go through `decide_command`; a `V4A` patch (any string in `tool_input` containing `*** Begin Patch`) is parsed into per-file operations and each path goes through `decide_path`; the first `deny` wins. `ask` is downgraded to `deny` with the reason suffixed by "Codex hooks cannot prompt; run it yourself or in Claude Code".
  - `parse_v4a(text)`: `*** Add File`, `*** Delete File`, `*** Update File` with optional `*** Move to`, hunks starting at `@@`. `apply_hunks(current, hunks)`: best-effort application by matching each hunk's context-plus-removed lines in order; a hunk that does not match yields no proposed content, which `decide_path` already treats as a denial for `change.json` and which does not matter for the paths denied unconditionally.
  - Output: deny prints the reason to stderr and exits 2; allow exits 0 silently; unreadable or unevaluable input allows with a note, as the Claude adapter does.
- `.codex/hooks.json` (new): one `PreToolUse` entry, matcher `.*`, command `python3 scripts/hooks/guard.py codex`, timeout 30. No policy.
- `scripts/repo.py`: `hook_findings` checks every tracked adapter in `HOOK_ADAPTERS = (".claude/settings.json", ".codex/hooks.json")`: invalid JSON or an untracked script is `hook-broken`; a guard script not referenced by any tracked adapter is `hook-adapter-missing` (info).
- `scripts/tests/test_guard.py`: `CodexAdapterTests` (shell deny instead of ask, with the reason; benign shell allowed; `apply_patch` updating the root `intent.md` denied; `apply_patch` adding `closure.json` denied; `apply_patch` changing `approvals` denied; `apply_patch` changing `write_scope` with approvals untouched allowed; a non-matching hunk on `change.json` denied; unknown tool and garbage input allowed with a note); `SettingsAdapterTests` gains the same shape check for `.codex/hooks.json`; direct unit tests of `parse_v4a` and `apply_hunks`.
- `scripts/tests/test_status.py`: a wired `.codex/hooks.json` is valid; one pointing at an untracked script is `hook-broken`; invalid JSON is `hook-broken`; a script wired by only one of the two adapters is not reported missing.
- `scripts/hooks/README.md`: Use and Wiring sections cover `guard.py codex` and the `ask`-to-`deny` rule; the Codex line no longer says "no hook integration".
- `docs/agent-surfaces.md`: the Codex section gets a Hooks subsection: feature flag `[features] hooks = true` in the user's `~/.codex/config.toml` (a machine setting the repository cannot make; some versions spell it `codex_hooks`), the `.codex/` directory is read-only inside Codex's `workspace-write` sandbox, no `ask`, status **not yet observed**, and the smoke probe to run (scratch copy, `codex exec` asked to edit the root `intent.md` and to append an approval, expect both denied with the guard's messages). The results table gets no new row until the owner runs it.
- `AGENTS.md`: the guard paragraph says it runs through `.claude/settings.json` in Claude Code and through `.codex/hooks.json` in Codex when hooks are enabled.
- `README.md`: the guard bullet and the agent-neutrality paragraph name both adapters and drop "no observed hook integration".

## Order of work

1. `parse_v4a`, `apply_hunks`, the `codex` subcommand, and their unit tests. Proof: `python3 -m unittest scripts.tests.test_guard -v` passes, including the new `CodexAdapterTests`.
2. `.codex/hooks.json`, the `repo.py` adapter generalisation, and the `test_status.py` cases. Proof: `python3 -m unittest scripts.tests.test_status -v` passes; `python3 scripts/repo.py status` on this branch reports no `hook-broken` and no `hook-adapter-missing`.
3. Documentation. Proof: `grep -rn "no hook integration\|no observed hook" --exclude-dir=changes .` matches nothing; `grep -n "not yet observed" docs/agent-surfaces.md` matches the Codex hooks subsection.
4. `python3 scripts/repo.py verify --change codex-hook-adapter --full` passes.

## Tests and proof

- `python3 scripts/repo.py verify --change codex-hook-adapter --full` (control-plane suite; expected about 150 tests).
- The greps in step 3.
- Live Codex behaviour is **not** proven by this change. The pull request says so, and `docs/agent-surfaces.md` carries the probe for the owner to run. If the probe shows `apply_patch` is not intercepted on the installed version, the shell rules still apply and the file rules fall back to `repo.py status`, which the documentation states.

## Risks and mitigations

- **Unknown `tool_name` and field names for `apply_patch`.** The adapter recognises a patch by its `*** Begin Patch` envelope anywhere in `tool_input`, not by field name, and recognises shell tools by several known names. The probe confirms or corrects this.
- **Hook command working directory.** The adapter uses a repository-relative script path. If Codex runs project hooks from another directory, the probe will show the hook failing; the fix is an absolute path or an environment variable, decided from the observation, not guessed now.
- **Hunk application mistakes.** A wrong application could only turn an allow into a deny (no proposed content denies `change.json`); it can never turn a deny into an allow for the unconditionally denied paths. Denial messages tell the agent what to do instead.
- **Experimental feature.** The hook does nothing until the owner enables the flag. Without it, Codex sessions behave exactly as today.

## Rollback or recovery

Revert the squash commit. No state outside git is involved; the user-level Codex flag is independent of the repository.

## Open questions

None for the change. One for the owner after merge: run the probe and add the row.
