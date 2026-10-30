# Implementation Plan

## Summary

The analysis of main reproduced these remaining gaps in `scripts/hooks/guard.py`:

1. `bash -lc 'git reset --hard'` returns `allow`, because the nested-shell check looks for an exact `-c` token.
2. `git branch --delete --force x`, `git checkout -- .` and `git restore .` return `allow`, although each discards work.
3. `echo git reset --hard` returns `ask`, because `git_invocation` scans every token of a segment.
4. Edit tools from MCP servers never reach the guard, because `.claude/settings.json` matches only `Edit|Write|MultiEdit` and `Bash`, and `claude_decision` ignores other tools. This one is from reading the code, not from a run.

The change closes all four. The guard stays friction: it still fails open and still returns `ask`, never `deny`, for shell commands.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `scripts/hooks/guard.py`:
  - `decide_command`: a new `shell_script(segment)` finds the script of a shell invocation. It accepts a short flag cluster containing `c`, such as `-c`, `-lc` or `-ec`, and takes the next token. Long options such as `--login` are skipped. Any other shape returns nothing, so behavior there is unchanged.
  - `git_rule`:
    - `branch` also asks on `--delete` together with `--force`, and on `-d` with `-f` or `--force`, as well as on `-D` as today.
    - `checkout` asks when `--` or `.` is among its arguments.
    - `restore` asks unless the arguments are limited to the index, meaning `--staged` or `-S` is present and `--worktree` or `-W` is not.
  - `git_invocation`: returns nothing when the segment's first word is in a new `INERT_COMMANDS = {"echo", "printf"}`. A list of inert commands, rather than requiring `git` as the first word, keeps `env git ...`, `sudo git ...`, `xargs git ...` and `find -exec git ...` inspected.
  - `claude_decision`: a tool whose name starts with `mcp__` takes its path from `relative_path`, `file_path` or `path`, and goes to `decide_path` with no proposed content. So a root baseline, frozen packet, `closure.json` or `change.json` edit is denied, and a tool with no such key is allowed.
- `.claude/settings.json`: a third matcher, `mcp__.*(write|edit|replace|insert|create|delete|rename).*`, so read-only MCP tools do not start the guard.
- `scripts/tests/test_guard.py`: the new cases below, and `SettingsAdapterTests` allows the new matcher.
- `scripts/hooks/README.md`: the new rules, and the limit on MCP tools.
- `docs/agent-surfaces.md`: the probe row, required when the guard changes.

## Order of work

1. Add failing tests to `scripts/tests/test_guard.py`. Proof: `python3 -m unittest scripts.tests.test_guard` fails only on the new tests.
2. Change `decide_command`, `git_rule` and `git_invocation`. Proof: the same command passes, except the MCP cases.
3. Change `claude_decision` and `.claude/settings.json`. Proof: the same command passes.
4. Update `scripts/hooks/README.md`, run the smoke probe, and add the row to `docs/agent-surfaces.md`. Proof: the new row exists.
5. `python3 scripts/repo.py status --change guard-remaining-gaps` and `python3 scripts/repo.py verify --change guard-remaining-gaps --full` pass, then close per `changes/README.md`.

## Tests and proof

Expect `ask`:

- `bash -lc 'git reset --hard'`, `sh -ec 'git push --force origin main'`, `bash --login -c 'git reset --hard'`.
- `git branch --delete --force x`, `git branch -d -f x`, `git checkout -- .`, `git checkout .`, `git checkout main -- src/a.py`, `git restore .`, `git restore src/a.py`, `git restore --staged --worktree src/a.py`.
- `env git reset --hard`, `sudo git reset --hard`, `xargs git reset --hard`, `find . -exec git reset --hard ;`.

Expect `allow`:

- `echo git reset --hard`, `printf 'git push --force'`.
- `git branch -d x`, `git checkout main`, `git checkout -b new`, `git restore --staged src/a.py`, `bash -lc 'ls'`, `bash script.sh -c x`.

Adapter cases through `guard.py claude`:

- `mcp__x__replace_content` on root `intent.md` and on `changes/x/closure.json` exits 2.
- The same tool on `src/a.py`, with no path key, or with a path outside the repository, exits 0.
- `mcp__x__find_symbol` on `intent.md` exits 0 if it reaches the guard.

## Risks and rollback

- **Riskiest step: `INERT_COMMANDS`.** It turns `ask` into `allow`, the only change that does. `echo` and `printf` run nothing, and command substitution inside them, such as `echo $(git reset --hard)`, was not reliably seen before either. The set stays at these two.
- **More `ask` prompts.** `git checkout -- <file>` and `git restore <file>` now ask, which is routine for an agent undoing its own edit. This is deliberate, because both discard uncommitted work, and each prompt costs one confirmation.
- **MCP coverage is partial.** It depends on tool names matching the pattern and on the three path keys. A tool that names its path differently, or changes many files like `rename_symbol`, is not caught, and `repo.py status` still reports those changes after the fact. Live MCP behavior is unit-tested only, and the pull request will say so.
- **`change.json` through an MCP edit tool** is always denied, because no proposed content is available. The agent uses a file tool instead.
- Rollback: revert the squash commit.

## Out of scope

- A Codex hook adapter.
- Full shell parsing, including `eval` and command substitution.
- Evidence checks in `repo.py close`, and approval of placeholder `product-init` artifacts, which are the next change.
